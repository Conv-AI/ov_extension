import math, os
import asyncio
import numpy as np
import omni.ext
import carb.events
import omni.ui as ui
import configparser
import pyaudio
import grpc
from .rpc import service_pb2 as convai_service_msg
from .rpc import service_pb2_grpc as convai_service
from .convai_audio_player import ConvaiAudioPlayer
from typing import Generator
import io
from pydub import AudioSegment
import threading
import traceback
import time
from collections import deque
import random
from functools import partial


__location__ = os.path.realpath(os.path.join(os.getcwd(), os.path.dirname(__file__)))

CHUNK = 1024
FORMAT = pyaudio.paInt16
CHANNELS = 1
RATE = 12000

def log(text: str, warning: bool =False):
    print(f"[convai] {'[Warning]' if warning else ''} {text}")

class ConvaiExtension(omni.ext.IExt):
    WINDOW_NAME = "Convai"
    MENU_PATH = f"Window/{WINDOW_NAME}"

    def on_startup(self, ext_id: str):
        self.IsCapturingAudio = False
        self.on_new_frame_sub = None
        self.channel_address = None
        self.channel = None
        self.SessionID = None
        self.channelState = grpc.ChannelConnectivity.IDLE
        self.client = None
        self.ConvaiGRPCGetResponseProxy = None
        self.PyAudio = pyaudio.PyAudio()
        self.stream = None
        self.Tick = False
        self.TickThread = None
        self.ConvaiAudioPlayer = ConvaiAudioPlayer(self._on_start_talk_callback, self._on_stop_talk_callback)
        self.LastReadyTranscription = ""
        self.ResponseTextBuffer = ""
        self.OldCharacterID = ""

        self.response_UI_Label_text = ""
        self.action_UI_Label_text = "<Action>"
        self.transcription_UI_Label_text = ""
        # self.response_UI_Label_text = "<Response will apear here>"
        self.response_UI_Label_text = "" # Turn off response text due to unknown crash
        self.StartTalking_Btn_text = "Start Talking"
        self.StartTalking_Btn_state = True
        self.UI_Lock = threading.Lock()
        self.Mic_Lock = threading.Lock()
        self.UI_update_counter = 0
        self.on_new_update_sub = None


        ui.Workspace.set_show_window_fn(ConvaiExtension.WINDOW_NAME, partial(self.show_window, None))
        ui.Workspace.show_window(ConvaiExtension.WINDOW_NAME)
        
        # # Put the new menu
        editor_menu = omni.kit.ui.get_editor_menu()
        
        if editor_menu:
            self._menu = editor_menu.add_item(
                ConvaiExtension.MENU_PATH, self.show_window, toggle=True, value=True
            )

        # self.show_window(None, True)
        self.read_channel_address_from_config()
        self.create_channel()

        log("ConvaiExtension started")

    def setup_UI(self):
        self._window = ui.Window(ConvaiExtension.WINDOW_NAME, width=300, height=300)
        self._window.set_visibility_changed_fn(self._visiblity_changed_fn)

        with self._window.frame:
            with ui.VStack():
                with ui.HStack(height = ui.Length(30)):
                    l = ui.Label("Convai API key")
                    self.APIKey_input_UI = ui.StringField()

                ui.Spacer(height=5)

                with ui.HStack(height = ui.Length(30)):
                    l = ui.Label("Character ID")
                    self.CharID_input_UI = ui.StringField()

                ui.Spacer(height=5)

                # with ui.HStack(height = ui.Length(30)):
                #     l = ui.Label("Session(Leave empty for 1st time)")
                #     self.session_input_UI = ui.StringField()

                # ui.Spacer(height=5)

                with ui.HStack(height = ui.Length(30)):
                    l = ui.Label("Comma seperated actions")
                    self.actions_input_UI = ui.StringField()
                    self.actions_input_UI.set_tooltip("e.g. Dances, Jumps")
                
                ui.Spacer(height=5)

                # self.response_UI_Label = ui.Label("", height = ui.Length(60), word_wrap = True)
                # self.response_UI_Label.alignment = ui.Alignment.CENTER
                
                self.action_UI_Label = ui.Label("<Action>", height = ui.Length(30), word_wrap = False)
                self.action_UI_Label.alignment = ui.Alignment.CENTER

                ui.Spacer(height=5)
    
                self.StartTalking_Btn = ui.Button("Start Talking", clicked_fn=lambda: self.on_start_talking_btn_click(), height = ui.Length(30))
                
                self.transcription_UI_Label = ui.Label("", height = ui.Length(60), word_wrap = True)
                self.transcription_UI_Label.alignment = ui.Alignment.CENTER

        if self.on_new_update_sub is None:
            self.on_new_update_sub = (
                omni.kit.app.get_app()
                .get_update_event_stream()
                .create_subscription_to_pop(self._on_UI_update_event, name="convai new UI update")
            )
        
        self.read_UI_from_config()

        return self._window

    def _on_UI_update_event(self, e):
        if self.UI_update_counter>1000:
            self.UI_update_counter = 0
        self.UI_update_counter += 1
        if self._window is None:
            return
        if self.UI_Lock.locked():
            log("UI_Lock is locked", 1)
            return
        
        with self.UI_Lock:
            # self.response_UI_Label.text = str(self.response_UI_Label_text)
            self.action_UI_Label.text = str(self.action_UI_Label_text)
            self.transcription_UI_Label.text = str(self.transcription_UI_Label_text)
            self.StartTalking_Btn.text = self.StartTalking_Btn_text
            self.StartTalking_Btn.enabled = self.StartTalking_Btn_state

    def start_tick(self):
        if self.Tick:
            log("Tick already started", 1)
            return
        self.Tick = True
        self.TickThread = threading.Thread(target=self._on_tick)
        self.TickThread.start()

    def stop_tick(self):
        if self.TickThread and self.Tick:
            self.Tick = False
            self.TickThread.join()

    def read_channel_address_from_config(self):
        config = configparser.ConfigParser()
        config.read(os.path.join(__location__, 'convai.env'))
        self.channel_address = config.get("CONVAI", "CHANNEL")

    def read_UI_from_config(self):
        config = configparser.ConfigParser()
        config.read(os.path.join(__location__, 'convai.env'))
        api_key = config.get("CONVAI", "API_KEY")
        self.APIKey_input_UI.model.set_value(api_key)

        character_id = config.get("CONVAI", "CHARACTER_ID")
        self.CharID_input_UI.model.set_value(character_id)

        actions_text = config.get("CONVAI", "ACTIONS")
        self.actions_input_UI.model.set_value(actions_text)

    def save_config(self):
        config = configparser.ConfigParser()
        config.read(os.path.join(__location__, 'convai.env'))
        config.set("CONVAI", "API_KEY", self.APIKey_input_UI.model.get_value_as_string())
        config.set("CONVAI", "CHARACTER_ID", self.CharID_input_UI.model.get_value_as_string())
        config.set("CONVAI", "ACTIONS", self.actions_input_UI.model.get_value_as_string())
        # config.set("CONVAI", "CHANNEL", self.channel_address)
        with open(os.path.join(__location__, 'convai.env'), 'w') as file:
            config.write(file)

    def create_channel(self):
        if (self.channel):
            log("gRPC channel already created")
            return
        
        self.channel = grpc.secure_channel(self.channel_address, grpc.ssl_channel_credentials())
        # self.channel.subscribe(self.on_channel_state_change, True)
        log("Created gRPC channel")

    def close_channel(self):
        if (self.channel):
            self.channel.close()
            self.channel = None
            log("close_channel - Closed gRPC channel")
        else:
            log("close_channel - gRPC channel already closed")

    def on_start_talking_btn_click(self):
        if (self.IsCapturingAudio):
            # Change UI
            with self.UI_Lock:
                self.StartTalking_Btn_text = "Processing..."
                # self.StartTalking_Btn_text = "Start Talking"
                self.StartTalking_Btn_state = False

                # Reset response UI text
                self.response_UI_Label_text = ""

            # Do one last mic read
            self.read_mic_and_send_to_grpc(True) 
            # time.sleep(0.01)
            # Stop Mic
            self.stop_mic()

        else:
            # Reset Session ID if Character ID changes
            if self.OldCharacterID != self.CharID_input_UI.model.get_value_as_string():
                self.OldCharacterID = self.CharID_input_UI.model.get_value_as_string()
                self.SessionID = ""

            with self.UI_Lock:
                # Reset transcription UI text
                self.transcription_UI_Label_text = ""
                self.LastReadyTranscription = ""

                # Change Btn text
                self.StartTalking_Btn_text = "Stop"

            # Open Mic stream
            self.start_mic()

            # Stop any on-going audio
            self.ConvaiAudioPlayer.stop()

            # Save API key, character ID and session ID
            self.save_config()

            # Create gRPC stream
            self.ConvaiGRPCGetResponseProxy = ConvaiGRPCGetResponseProxy(self)

    def on_shutdown(self):
        self.clean_grpc_stream()
        self.close_channel()
        self.stop_tick()

        if self._menu:
            self._menu = None

        if self._window:
            self._window.destroy()

        self._window = None
        # Deregister the function that shows the window from omni.ui
        ui.Workspace.set_show_window_fn(ConvaiExtension.WINDOW_NAME, None)

        log("ConvaiExtension shutdown")

    def start_mic(self):
        if self.IsCapturingAudio == True:
            log("start_mic - mic is already capturing audio", 1)
            return
        self.stream = self.PyAudio.open(format=FORMAT,
                        channels=CHANNELS,
                        rate=RATE,
                        input=True,
                        frames_per_buffer=CHUNK)
        self.IsCapturingAudio = True
        self.start_tick()
        log("start_mic - Started Recording")

    def stop_mic(self):
        if self.IsCapturingAudio == False:
            log("stop_mic - mic has not started yet", 1)
            return
        
        self.stop_tick()

        if self.stream:
            self.stream.stop_stream()
            self.stream.close()
        else:
            log("stop_mic - could not close mic stream since it is None", 1)
        
        self.IsCapturingAudio = False
        log("stop_mic - Stopped Recording")

    def clean_grpc_stream(self):
        if self.ConvaiGRPCGetResponseProxy:
            self.ConvaiGRPCGetResponseProxy.Parent = None
            del self.ConvaiGRPCGetResponseProxy
        self.ConvaiGRPCGetResponseProxy = None
        # self.close_channel()

    def on_transcription_received(self, Transcription: str, IsTranscriptionReady: bool, IsFinal: bool):
        '''
        Called when user transcription is received
        '''
        self.UI_Lock.acquire()
        self.transcription_UI_Label_text = self.LastReadyTranscription + " " + Transcription
        self.UI_Lock.release()
        if IsTranscriptionReady:
            self.LastReadyTranscription = self.LastReadyTranscription + " " + Transcription

    def on_data_received(self, ReceivedText: str, ReceivedAudio: bytes, SampleRate: int, IsFinal: bool):
        '''
	    Called when new text and/or Audio data is received
        '''
        self.ResponseTextBuffer += str(ReceivedText)
        if IsFinal:
            with self.UI_Lock:
                self.response_UI_Label_text = self.ResponseTextBuffer
                self.transcription_UI_Label_text = self.ResponseTextBuffer
                self.ResponseTextBuffer = ""
        self.ConvaiAudioPlayer.append_to_stream(ReceivedAudio)
        return

    def on_actions_received(self, Action: str):
        '''
	    Called when actions are received
        '''
        # Action.replace(".", "")
        self.UI_Lock.acquire()
        for InputAction in self.parse_actions():
            # log (f"on_actions_received: {Action} - {InputAction} - {InputAction.find(Action)}")
            if Action.find(InputAction) >= 0:
                self.action_UI_Label_text = InputAction
                self.fire_event(InputAction)
                self.UI_Lock.release()
                return
        self.action_UI_Label_text = "None"
        self.UI_Lock.release()
        
    def on_session_ID_received(self, SessionID: str):
        '''
	    Called when new SessionID is received
        '''
        self.SessionID = SessionID

    def on_finish(self):
        '''
	    Called when the response stream is done
        '''

        self.ConvaiGRPCGetResponseProxy = None
        with self.UI_Lock:
            self.StartTalking_Btn_text = "Start Talking"
            self.StartTalking_Btn_state = True
        self.clean_grpc_stream()
        log("Received on_finish")

    def on_failure(self, ErrorMessage: str):
        '''
        Called when there is an unsuccessful response
        '''
        log(f"on_failure called with message: {ErrorMessage}", 1)
        with self.UI_Lock:
            self.transcription_UI_Label_text = "ERROR: Please double check API key and the character ID - Send logs to support@convai.com for further assistance."
        self.stop_mic()
        self.on_finish()

    def _on_tick(self):
        while self.Tick:
            time.sleep(0.1)
            if self.IsCapturingAudio == False or self.ConvaiGRPCGetResponseProxy is None:
                continue
            self.read_mic_and_send_to_grpc(False)

    def _on_start_talk_callback(self):
        self.fire_event("start")
        log("Character Started Talking")

    def _on_stop_talk_callback(self):
        self.fire_event("stop")
        log("Character Stopped Talking")
    
    def read_mic_and_send_to_grpc(self, LastWrite):
        with self.Mic_Lock:
            if self.stream:
                data = self.stream.read(CHUNK)
            else:
                log("read_mic_and_send_to_grpc - could not read mic stream since it is none", 1)
                data = bytes()

            if self.ConvaiGRPCGetResponseProxy:
                self.ConvaiGRPCGetResponseProxy.write_audio_data_to_send(data, LastWrite)
            else:
                log("read_mic_and_send_to_grpc - ConvaiGRPCGetResponseProxy is not valid", 1)

    def fire_event(self, event_name):
        def registered_event_name(event_name):
            """Returns the internal name used for the given custom event name"""
            n = "omni.graph.action." + event_name
            return carb.events.type_from_string(n)

        reg_event_name = registered_event_name(event_name)
        message_bus = omni.kit.app.get_app().get_message_bus_event_stream()

        message_bus.push(reg_event_name, payload={})

    def parse_actions(self):
        actions = ["None"] + self.actions_input_UI.model.get_value_as_string().split(',')
        actions = [a.lstrip(" ").rstrip(" ") for a in actions]
        return actions

    def show_window(self, menu, value):
        # with self.UI_Lock:
        if value:
            self.setup_UI()
            self._window.set_visibility_changed_fn(self._visiblity_changed_fn)
        else:
            if self._window:
                self._window.visible = False

    def _visiblity_changed_fn(self, visible):
        # with self.UI_Lock:
        # Called when the user pressed "X"
        self._set_menu(visible)
        if not visible:
            # Destroy the window, since we are creating new window
            # in show_window
            asyncio.ensure_future(self._destroy_window_async())

    def _set_menu(self, value):
        """Set the menu to create this window on and off"""
        editor_menu = omni.kit.ui.get_editor_menu()
        if editor_menu:
            editor_menu.set_value(ConvaiExtension.MENU_PATH, value)

    async def _destroy_window_async(self):
        # with self.UI_Lock:
        # wait one frame, this is due to the one frame defer
        # in Window::_moveToMainOSWindow()
        await omni.kit.app.get_app().next_update_async()
        if self._window:
            self._window.destroy()
            self._window = None

class ConvaiGRPCGetResponseProxy:
    def __init__(self, Parent: ConvaiExtension):
        self.Parent = Parent

        self.AudioBuffer = deque(maxlen=4096*2)
        self.InformOnDataReceived = False
        self.LastWriteReceived = False
        self.client = None
        self.NumberOfAudioBytesSent = 0
        self.call = None
        self._write_task = None
        self._read_task = None

        # self._main_task = asyncio.ensure_future(self.activate())
        self.activate()
        log("ConvaiGRPCGetResponseProxy constructor")

    def activate(self):
        # Validate API key
        if (len(self.Parent.APIKey_input_UI.model.get_value_as_string()) == 0):
            self.Parent.on_failure("API key is empty")
            return
        
        # Validate Character ID
        if (len(self.Parent.CharID_input_UI.model.get_value_as_string()) == 0):
            self.Parent.on_failure("Character ID is empty")
            return
        
        # Validate Channel
        if self.Parent.channel is None:
            log("grpc - self.Parent.channel is None", 1)
            self.Parent.on_failure("gRPC channel was not created")
            return

        # Create the stub
        self.client = convai_service.ConvaiServiceStub(self.Parent.channel)

        threading.Thread(target=self.init_stream).start()

    def init_stream(self):
        log("grpc - stream initialized")
        try:
            for response in self.client.GetResponse(self.create_getGetResponseRequests()):
                if response.HasField("audio_response"):
                    log("gRPC - audio_response: {} {} {}".format(response.audio_response.audio_config, response.audio_response.text_data, response.audio_response.end_of_response))
                    log("gRPC - session_id: {}".format(response.session_id))
                    self.Parent.on_session_ID_received(response.session_id)
                    self.Parent.on_data_received(
                        response.audio_response.text_data,
                        response.audio_response.audio_data,
                        response.audio_response.audio_config.sample_rate_hertz,
                        response.audio_response.end_of_response)

                elif response.HasField("action_response"):
                    log(f"gRPC - action_response: {response.action_response.action}")
                    self.Parent.on_actions_received(response.action_response.action)

                elif response.HasField("user_query"):
                    log(f"gRPC - user_query: {response.user_query}")
                    self.Parent.on_transcription_received(response.user_query.text_data, response.user_query.is_final, response.user_query.end_of_response)

                else:
                    log("Stream Message: {}".format(response))
            time.sleep(0.1)
                
        except Exception as e:
            if 'response' in locals() and response is not None and response.HasField("audio_response"):
                self.Parent.on_failure(f"gRPC - Exception caught in loop: {str(e)} - Stream Message: {response}")
            else:
                self.Parent.on_failure(f"gRPC - Exception caught in loop: {str(e)}")
            traceback.print_exc()
            return
        self.Parent.on_finish()

    def create_initial_GetResponseRequest(self)-> convai_service_msg.GetResponseRequest:
        action_config = convai_service_msg.ActionConfig(
            classification = 'singlestep',
            context_level = 1
        )
        action_config.actions[:] = self.Parent.parse_actions()
        action_config.objects.append(
            convai_service_msg.ActionConfig.Object(
                name = "dummy",
                description = "A dummy object."
            )
        )

        log(f"gRPC - actions parsed: {action_config.actions}")
        action_config.characters.append(
            convai_service_msg.ActionConfig.Character(
                name = "User",
                bio = "Person playing the game and asking questions."
            )
        )
        get_response_config = convai_service_msg.GetResponseRequest.GetResponseConfig(
                character_id = self.Parent.CharID_input_UI.model.get_value_as_string(),
                api_key = self.Parent.APIKey_input_UI.model.get_value_as_string(),
                audio_config = convai_service_msg.AudioConfig(
                    sample_rate_hertz = RATE
                ),
                action_config = action_config
            )
        if self.Parent.SessionID and self.Parent.SessionID != "":
            get_response_config.session_id = self.Parent.SessionID
        return convai_service_msg.GetResponseRequest(get_response_config = get_response_config)

    def create_getGetResponseRequests(self)-> Generator[convai_service_msg.GetResponseRequest, None, None]:
        req = self.create_initial_GetResponseRequest()
        yield req

        # for i in range(0, 10):
        while 1:
            IsThisTheFinalWrite = False
            GetResponseData = None

            if (0): # check if this is a text request
                pass
            else:
                data, IsThisTheFinalWrite = self.consume_from_audio_buffer()
                if len(data) == 0 and IsThisTheFinalWrite == False:
                    time.sleep(0.05)
                    continue
                # Load the audio data to the request
                self.NumberOfAudioBytesSent += len(data)
                # if len(data):
                #     log(f"len(data) = {len(data)}")
                GetResponseData = convai_service_msg.GetResponseRequest.GetResponseData(audio_data = data)

            # Prepare the request
            req = convai_service_msg.GetResponseRequest(get_response_data = GetResponseData)
            yield req

            if IsThisTheFinalWrite:
                log(f"gRPC - Done Writing - {self.NumberOfAudioBytesSent} audio bytes sent")
                break
            time.sleep(0.1)

    def write_audio_data_to_send(self, Data: bytes, LastWrite: bool):
        self.AudioBuffer.append(Data)
        if LastWrite:
            self.LastWriteReceived = True
            log(f"gRPC LastWriteReceived")

        # if self.InformOnDataReceived:
        #     # Inform of new data to send
        #     self._write_task = asyncio.ensure_future(self.write_stream())
        #     # Reset
        #     self.InformOnDataReceived = False

    def finish_writing(self):
        self.write_audio_data_to_send(bytes(), True)

    def consume_from_audio_buffer(self):
        Length = len(self.AudioBuffer)
        IsThisTheFinalWrite = False
        data = bytes()

        if Length:
            data = self.AudioBuffer.pop()
            # self.AudioBuffer = bytes()
        
        if self.LastWriteReceived and Length == 0:
            IsThisTheFinalWrite = True
        else:
            IsThisTheFinalWrite = False

        if IsThisTheFinalWrite:
            log(f"gRPC Consuming last mic write")

        return data, IsThisTheFinalWrite
    
    def __del__(self):
        self.Parent = None
        # if self._main_task:
        #     self._main_task.cancel()
        # if self._write_task:
        #     self._write_task.cancel()
        # if self._read_task:
        #     self._read_task.cancel()
        # if self.call:
        #     self.call.cancel()
        log("ConvaiGRPCGetResponseProxy Destructor")
