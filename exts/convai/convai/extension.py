from asyncio import constants
import math
import omni.ext
from omni.kit.widget.stage.event import EventSubscription
import omni.ui as ui
from omni.kit.window.property.templates import HORIZONTAL_SPACING, LABEL_HEIGHT, LABEL_WIDTH, SimplePropertyWidget
import omni.kit.commands
from pxr import Sdf, Usd, UsdSkel
import weakref
from functools import partial
import threading

import queue
import requests
import json
import time
import subprocess
import sys, os
import base64
import sounddevice as sd
from scipy.io.wavfile import write, WAVE_FORMAT
import wavio as wv
import struct
import omni.kit.app
import carb.events
import numpy as np
from omni.usd.commands.stage_helper import UsdStageHelper


class Constant:
    def __setattr__(self, name, value):
        raise Exception(f"Can't change Constant.{name}")

    MIXED = "Mixed"
    MIXED_COLOR = 0xFFCC9E61
    LABEL_COLOR = 0xFF9E9E9E
    LABEL_FONT_SIZE = 14
    LABEL_WIDTH = 80
    ADD_BUTTON_SIZE = 52


def _get_plus_glyph():
    return omni.kit.ui.get_custom_glyph_code("${glyphs}/menu_context.svg")


# omni.kit.commands.execute('AssignAnimation',
# 	skeleton_path='/World/party_m_0001/ManRoot/Party_M_0001/Party_M_0001/Party_M_0001',
# 	animprim_path='/World/aerobic_dance_315220')

# omni.kit.commands.execute('SetAnimCurveKey',
# 	paths=['/World/Cone.xformOp:translate', '/World/Cone.xformOp:rotateXYZ', '/World/Cone.xformOp:scale', '/World/Cone.visibility'])


# omni.kit.commands.execute('AddRelationshipTarget',
# 	relationship=Usd.Prim(</World/party_m_0001/ManRoot/Party_M_0001/Party_M_0001/Party_M_0001>).GetRelationship('skel:animationSource'),
# 	target=Sdf.Path('/World/stand_talk_251115'))

# omni.kit.commands.execute('ChangeProperty',
# 	prop_path=Sdf.Path('/World/party_m_0001/ManRoot/Party_M_0001/Party_M_0001/Party_M_0001.purpose'),
# 	value='render',
# 	prev=None)


# omni.kit.commands.execute('SetAnimCurveKey',
# 	paths=['/World/party_m_0001/ManRoot/Party_M_0001/Party_M_0001/Party_M_0001.visibility'])




# def registered_event_name(event_name):
#     """Returns the internal name used for the given custom event name"""
#     n = "omni.graph.action." + event_name
#     return carb.events.type_from_string(n)

# event_name = 'go'
# reg_event_name = registered_event_name(event_name)
# message_bus = omni.kit.app.get_app().get_message_bus_event_stream()

# message_bus.push(reg_event_name, payload={})

def GetStartEndTimeForAnim(AnimPath):
    # not tested yet ...

    UsdStageHelper = UsdStageHelper()
    stage = UsdStageHelper._get_stage()
    src_skel_prim = stage.GetPrimAtPath(AnimPath)
    startTime = endTime = 0
    src_skel_anim = UsdSkel.Animation(src_skel_prim)
    if src_skel_anim:
        attrs = [src_skel_prim.GetAttribute(attr_name) for attr_name in src_skel_anim.GetSchemaAttributeNames()]
        for attr in attrs:
            time_samples = attr.GetTimeSamples()
            if len(time_samples) > 0:
                enabled = True
                if time_samples[0] < startTime:
                    startTime = time_samples[0]
                if time_samples[-1] > endTime:
                    endTime = time_samples[-1]

    return startTime, endTime
        


def PCM2WAV(rate, data):
    """
    Write a NumPy array as a WAV file.

    Parameters
    ----------
    filename : string or open file handle
        Output wav file.
    rate : int
        The sample rate (in samples/sec).
    data : ndarray
        A 1-D or 2-D NumPy array of either integer or float data-type.

    Notes
    -----
    * Writes a simple uncompressed WAV file.
    * To write multiple-channels, use a 2-D array of shape
      (Nsamples, Nchannels).
    * The bits-per-sample and PCM/float will be determined by the data-type.

    Common data types: [1]_

    =====================  ===========  ===========  =============
         WAV format            Min          Max       NumPy dtype
    =====================  ===========  ===========  =============
    32-bit floating-point  -1.0         +1.0         float32
    32-bit PCM             -2147483648  +2147483647  int32
    16-bit PCM             -32768       +32767       int16
    8-bit PCM              0            255          uint8
    =====================  ===========  ===========  =============

    Note that 8-bit PCM is unsigned.

    References
    ----------
    .. [1] IBM Corporation and Microsoft Corporation, "Multimedia Programming
       Interface and Data Specifications 1.0", section "Data Format of the
       Samples", August 1991
       http://www.tactilemedia.com/info/MCI_Control_Info.html

    Examples
    --------
    Create a 100Hz sine wave, sampled at 44100Hz.
    Write to 16-bit PCM, Mono.

    >>> from scipy.io.wavfile import write
    >>> samplerate = 44100; fs = 100
    >>> t = np.linspace(0., 1., samplerate)
    >>> amplitude = np.iinfo(np.int16).max
    >>> data = amplitude * np.sin(2. * np.pi * fs * t)
    >>> write("example.wav", samplerate, data.astype(np.int16))

    """
    fs = rate
    out = b''

    try:
        dkind = data.dtype.kind
        if not (dkind == 'i' or dkind == 'f' or (dkind == 'u' and
                                                    data.dtype.itemsize == 1)):
            raise ValueError("Unsupported data type '%s'" % data.dtype)

        header_data = b''

        header_data += b'RIFF'
        # header_data += b'\x00\x00\x00\x00'
        header_data += struct.pack('<I', data.shape[0]+36)

        header_data += b'WAVE'

        # fmt chunk
        header_data += b'fmt '
        if dkind == 'f':
            format_tag = WAVE_FORMAT.IEEE_FLOAT
        else:
            format_tag = WAVE_FORMAT.PCM
        if data.ndim == 1:
            channels = 1
        else:
            channels = data.shape[1]
        bit_depth = data.dtype.itemsize * 8
        bytes_per_second = fs*(bit_depth // 8)*channels
        block_align = channels * (bit_depth // 8)

        fmt_chunk_data = struct.pack('<HHIIHH', format_tag, channels, fs,
                                        bytes_per_second, block_align, bit_depth)
        if not (dkind == 'i' or dkind == 'u'):
            # add cbSize field for non-PCM files
            fmt_chunk_data += b'\x00\x00'

        header_data += struct.pack('<I', len(fmt_chunk_data))
        header_data += fmt_chunk_data

        # fact chunk (non-PCM files)
        if not (dkind == 'i' or dkind == 'u'):
            header_data += b'fact'
            header_data += struct.pack('<II', 4, data.shape[0])

        # check data size (needs to be immediately before the data chunk)
        if ((len(header_data)-4-4) + (4+4+data.nbytes)) > 0xFFFFFFFF:
            raise ValueError("Data exceeds wave file size limit")
        out += header_data
        # data chunk
        out +=(b'data')
        out += struct.pack('<I', data.nbytes)
        if data.dtype.byteorder == '>' or (data.dtype.byteorder == '=' and
                                            sys.byteorder == 'big'):
            data = data.byteswap()

        out += data.ravel().view('b').data
        return out

    except Exception as e:
        print("PCM2WAV could not serialize into WAV")
        print(e)
        return None


class MyExtension(omni.ext.IExt):
    def on_startup(self, ext_id):
        # print("[convai] Convai")
        self.IsCapturingAudio = False
        self._window = ui.Window("Convai", width=300, height=300)

        self.ResponseQueue = queue.Queue()
        self.EventsToLaunch = []
        self.sessionID = -1
        self.TryToPlay = 0
        # self.EventsToLaunch.append({'class': "talk", 'TimeToFire': 1})
        # self.EventsToLaunch.append({'class': "dance", 'TimeToFire': 3})


        self.VoiceCap_Btn = ui.Button("Start Voice Capture", clicked_fn=lambda: on_VoiceCap())

        self.on_new_frame_sub = (
            omni.usd.get_context()
            .get_rendering_event_stream()
            .create_subscription_to_pop(self._on_frame_event, name="convai new frame")
        )

        self.on_new_TimelineTick_sub = (
            omni.timeline.get_timeline_interface()
            .get_timeline_event_stream()
            .create_subscription_to_pop(self._on_TimelineTick_event, name="convai new frame")
        )

        with self._window.frame:
            with ui.VStack() :
                with ui.HStack(height = ui.Length(30)):
                    l = ui.Label("Enter Convai API key")
                    self.APIKey_input_UI = ui.StringField()
                    # self.APIKey_input_UI.height = ui.Length(30)
                    # l.height = ui.Length(30)
                ui.Spacer(height=5)
                with ui.HStack(height = ui.Length(30)):
                    l = ui.Label("Enter Char ID")
                    self.CharID_input_UI = ui.StringField()

                # button_width = Constant.ADD_BUTTON_SIZE + 25
                # add_button = ui.Button(f"{_get_plus_glyph()} Add", width=button_width, height=LABEL_HEIGHT, name="add", clicked_fn=partial(on_add_target, weak_self=weakref.ref(self)))
                


                self.response_UI_Label = ui.Label("<Response will apear here>", height = ui.Length(60), word_wrap = True)
                self.class_UI_Label = ui.Label("<Class will apear here>", height = ui.Length(30), word_wrap = False)

                ui.Label("Enter comma seperated events here:")
                self.text_input_UI = ui.StringField(height = ui.Length(30))
                # self.text_input_UI.model.set_value("dance,magic")
               
                # For Testing
                ##

                self.VoiceCap_Btn = ui.Button("Start Voice Capture", clicked_fn=lambda: on_VoiceCap(), height = ui.Length(30))
                def on_VoiceCap():
                    if (self.IsCapturingAudio):
                        self.VoiceCap_Btn.text = "Processing..."
                        self.VoiceCap_Btn.enabled = False
                        
                        def on_response(Response):
                            self.EventsToLaunch = [] # Clear the current events
                            self.ResponseQueue.put(Response)

                        args = (PCM2WAV(24000, self.recording), 
                        self.text_input_UI.model.get_value_as_string(),
                        self.APIKey_input_UI.model.get_value_as_string(), 
                        self.CharID_input_UI.model.get_value_as_string(), 
                        on_response)

                        threading.Thread(target=self.ChatbotQueryWithClassification, args=args).start()
                       
                    else:
                        self.recording = sd.rec(int(10 * 24000), samplerate=24000, channels=1, dtype=np.dtype("int16"))
                        self.IsCapturingAudio = True
                        self.VoiceCap_Btn.text = "Stop Voice Capture"

    def _on_frame_event(self, event):

        if self.TryToPlay > 0:
            omni.timeline.get_timeline_interface().play()
            self.TryToPlay -= 1

        try:
            Response = self.ResponseQueue.get_nowait()            
            try:
                data = Response.json()

                character_response = data["text"]
                classification = "idle"
                if character_response.find("<") >= 0:
                    begin_class = character_response.find("<")
                    end_class = character_response.find(">")
                    classification = character_response[begin_class+1:end_class]
                    character_response = character_response[:begin_class] + character_response[end_class+1:]

                decode_string = base64.b64decode(data["audio"])

                extension_path = omni.kit.app.get_app().get_extension_manager().get_extension_path_by_module(__name__)
                FilePath = f"{extension_path}/audioResponse.wav"

                with open(FilePath,'wb') as f:
                    f.write(decode_string)


                self.response_UI_Label.text = character_response
                self.class_UI_Label.text = classification

                # Get duration of the response audio
                wav = wv._wave.open(FilePath)
                rate = wav.getframerate()
                nframes = wav.getnframes()
                Duration = math.ceil(nframes / rate)

                self.SpawnAudio(FilePath, Duration)

                def AppendDelayedEvent(DelayedEvent, TimeToFire):
                    time.sleep(TimeToFire)
                    self.EventsToLaunch.append(DelayedEvent)

                if classification == "hello":
                    threading.Thread(target=AppendDelayedEvent, args=('hello', 0)).start()
                    threading.Thread(target=AppendDelayedEvent, args=('talk', 1)).start()
                else:
                    threading.Thread(target=AppendDelayedEvent, args=('talk', 0)).start()

                classes = self.text_input_UI.model.get_value_as_string().replace(" ", "").split(',')
                if classification in classes and classification != "hello":
                    threading.Thread(target=AppendDelayedEvent, args=(classification, Duration)).start()
                    # threading.Thread(target=AppendDelayedEvent, args=('idle' ,Duration+12)).start()
                else:
                    threading.Thread(target=AppendDelayedEvent, args=('idle' ,Duration)).start()

            except Exception as e:
                print("error: " + str(e))
                print("response: " + Response.text)
                
                self.response_UI_Label.text = "Error: Check the logs"
                self.class_UI_Label.text = "Error: " + str(e)
                return

            finally:
                self.VoiceCap_Btn.text = "Start Voice Capture"
                self.IsCapturingAudio = False
                self.VoiceCap_Btn.enabled = True
        except:
            pass



    def _on_TimelineTick_event(self, TickEvent):
        # print(TickEvent.payload.get_dict())
        # stage = UsdStageHelper()._get_stage()
        # stage.SetEndTimeCode(500)
        # stage.set
        # print(dir(omni.timeline.get_timeline_interface()))

        # stage = UsdStageHelper()._get_stage()
        # print('-------------------------------------------------------------------')
        # print(stage.GetEndTimeCode())

        for eventToLaunch in self.EventsToLaunch:
            if "currentTime" not in TickEvent.payload.get_dict():
                continue

            CurrentTIme = TickEvent.payload.get_dict()["currentTime"]
            # TargetTime = eventToLaunch["TimeToFire"]

            # CurrentTIme = math.ceil(CurrentTIme)
            # TargetTime  = math.ceil(TargetTime)
            
            # if CurrentTIme == TargetTime:
            #     classification = eventToLaunch["class"]
            #     FireEvent(classification) 
            #     print("Fired event: " + classification + ", at time: " + str(CurrentTIme))
            if (eventToLaunch not in ["talk", "hello"]):
                omni.kit.commands.execute('DeletePrims',
                paths=['/World/Convai_Audio'])
            FireEvent(eventToLaunch) 
            print("Fired event: " + eventToLaunch + ", at time: " + str(CurrentTIme))

        if len(self.EventsToLaunch) > 0:
            self.EventsToLaunch = []

    def SpawnAudio(self, AudioFilePath, duration=0):
        stage = UsdStageHelper()._get_stage()
        
        startTimeActual = omni.timeline.get_timeline_interface().get_current_time()
        startTimeFrame = startTimeActual * stage.GetTimeCodesPerSecond()
        endTimeFrame = (startTimeActual + duration) * stage.GetTimeCodesPerSecond()
        endTimeFrameActual = endTimeFrame / stage.GetTimeCodesPerSecond()
        print("Duration: " + str(duration) + "seconds, Start Frame: " + str(startTimeFrame) + "End frame: " + str(endTimeFrame))
        if endTimeFrame > stage.GetEndTimeCode():
            omni.timeline.get_timeline_interface().set_start_time(0)
            omni.timeline.get_timeline_interface().set_end_time(0)
            omni.timeline.get_timeline_interface().set_end_time(math.ceil(duration) + 1) #  + 1 margin
            startTimeFrame = Sdf.TimeCode(0)
            # omni.timeline.get_timeline_interface().play()
            self.TryToPlay = 10
            print ("set end time to: " + str(duration) + " seconds which is " + str(endTimeFrame-startTimeFrame) + " frames")

        omni.kit.commands.execute('DeletePrims',
            paths=['/World/Convai_Audio'])

        omni.kit.commands.execute('CreatePrimWithDefaultXform',
            prim_type='Sound',
            prim_path="/World/Convai_Audio",
                attributes={'auralMode': 'nonSpatial',
                            'filePath' : AudioFilePath,
                            'startTime': startTimeFrame})

    def on_shutdown(self):
        print("[convai] MyExtension shutdown")
        self.EventsToLaunch = []

    def ChatbotQueryWithClassification(self, AudioWav, Classes, APIKey, CharacterID, callback):
        url = "https://api.convai.com/character/getResponse"

        payload={
            'charID': CharacterID,
            'sessionID': self.sessionID,
            'responseLevel': '5',
            'voiceResponse': 'True',    
            'classification': 'True',
            'classLabels': Classes}


        # print(payload)
        files=[
        ('file',('audio.wav', AudioWav,'audio/wav'))
        ]

        headers = {
        'CONVAI-API-KEY': APIKey
        }

        try:
            response = requests.request("POST", url, headers=headers, data=payload, files=files)
            callback(response)

        except Exception as e:
            callback(None)
            print(e)
            return None





def FireEvent(event_name):
    def registered_event_name(event_name):
        """Returns the internal name used for the given custom event name"""
        n = "omni.graph.action." + event_name
        return carb.events.type_from_string(n)

    reg_event_name = registered_event_name(event_name)
    message_bus = omni.kit.app.get_app().get_message_bus_event_stream()

    message_bus.push(reg_event_name, payload={})


