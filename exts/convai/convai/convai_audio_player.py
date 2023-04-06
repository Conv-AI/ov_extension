# from .extension import ConvaiExtension, log
# from test import ConvaiExtension, log
import pyaudio
from pydub import AudioSegment
import io


class ConvaiAudioPlayer:
    def __init__(self, start_taking_callback, stop_talking_callback):
        self.start_talking_callback = start_taking_callback
        self.stop_talking_callback = stop_talking_callback
        self.AudioSegment = None
        self.pa = pyaudio.PyAudio()
        self.pa_stream = None
        self.IsPlaying = False
    
    def append_to_stream(self, data: bytes):
        segment = AudioSegment.from_wav(io.BytesIO(data)).fade_in(100).fade_out(100)
        if self.AudioSegment is None:
            self.AudioSegment = segment
        else:
            self.AudioSegment._data += segment._data
        self.play()

    def play(self):    
        if self.IsPlaying:
            return
        print("ConvaiAudioPlayer - Started playing")
        self.start_talking_callback()
        self.pa_stream = self.pa.open(
            format=pyaudio.get_format_from_width(self.AudioSegment.sample_width),
            channels=self.AudioSegment.channels,
            rate=self.AudioSegment.frame_rate,
            output=True, 
            stream_callback=self.stream_callback
        )
        self.IsPlaying = True

    def pause(self):
        '''
        Pause playing
        '''
        self.IsPlaying = False
    
    def stop(self):
        '''
        Pause playing and clear audio
        '''
        self.pause()
        self.AudioSegment = None

    def stream_callback(self, in_data, frame_count, time_info, status_flags):
        if not self.IsPlaying:
            frames = bytes()
        else:
            frames = self.consume_frames(frame_count)
        
        if self.AudioSegment and len(frames) < frame_count*self.AudioSegment.frame_width:
            print("ConvaiAudioPlayer - Stopped playing")
            self.stop_talking_callback()
            self.IsPlaying = False
            return frames, pyaudio.paComplete
        else:
            return frames, pyaudio.paContinue
        
    def consume_frames(self, count: int):
        if self.AudioSegment is None:
            return bytes()
        
        FrameEnd = self.AudioSegment.frame_width*count
        if FrameEnd > len(self.AudioSegment._data):
            return bytes()

            
        FramesToReturn = self.AudioSegment._data[0:FrameEnd]
        if FrameEnd == len(self.AudioSegment._data):
            self.AudioSegment._data = bytes()
        else:
            self.AudioSegment._data = self.AudioSegment._data[FrameEnd:]
            # print("self.AudioSegment._data = self.AudioSegment._data[FrameEnd:]")

        return FramesToReturn

if __name__ == '__main__':
    import time
    import pyaudio
    import grpc
    from rpc import service_pb2 as convai_service_msg
    from rpc import service_pb2_grpc as convai_service
    from typing import Generator
    import io
    from pydub import AudioSegment
    import configparser

    CHUNK = 1024
    FORMAT = pyaudio.paInt16
    CHANNELS = 1
    RATE = 16000
    RECORD_SECONDS = 3

    p = pyaudio.PyAudio()

    stream = p.open(format=FORMAT,
                    channels=CHANNELS,
                    rate=RATE,
                    input=True,
                    frames_per_buffer=CHUNK)
    audio_player = ConvaiAudioPlayer(None)

    def start_mic():
        global stream
        stream = PyAudio.open(format=FORMAT,
                        channels=CHANNELS,
                        rate=RATE,
                        input=True,
                        frames_per_buffer=CHUNK)
        print("start_mic - Started Recording")

    def stop_mic():
        global stream
        if stream:
            stream.stop_stream()
            stream.close()
        else:
            print("stop_mic - could not close mic stream since it is None")
            return
        print("stop_mic - Stopped Recording")

    def getGetResponseRequests(api_key: str, character_id: str, session_id: str = "") -> Generator[convai_service_msg.GetResponseRequest, None, None]:
        action_config = convai_service_msg.ActionConfig(
            classification = 'multistep',
            context_level = 1
        )
        action_config.actions[:] = ["fetch", "jump", "dance", "swim"]
        action_config.objects.append(
            convai_service_msg.ActionConfig.Object(
                name = "ball",
                description = "A round object that can bounce around."
            )
        )
        action_config.objects.append(
            convai_service_msg.ActionConfig.Object(
                name = "water",
                description = "Liquid found in oceans, seas and rivers that you can swim in. You can also drink it."
            )
        )
        action_config.characters.append(
            convai_service_msg.ActionConfig.Character(
                name = "User",
                bio = "Person playing the game and asking questions."
            )
        )
        action_config.characters.append(
            convai_service_msg.ActionConfig.Character(
                name = "Learno",
                bio = "A medieval farmer from a small village."
            )
        )
        get_response_config = convai_service_msg.GetResponseRequest.GetResponseConfig(
                character_id = character_id,
                api_key = api_key,
                audio_config = convai_service_msg.AudioConfig(
                    sample_rate_hertz = 16000
                ),
                action_config = action_config
            )
        # session_id = "f50b7bf00ad50f5c2c22065965948c16"
        if session_id != "":
            get_response_config.session_id = session_id
        yield convai_service_msg.GetResponseRequest(
            get_response_config = get_response_config    
        )
        for i in range(0, int(RATE / CHUNK * RECORD_SECONDS)):
            data = stream.read(CHUNK)
            yield convai_service_msg.GetResponseRequest(
                get_response_data = convai_service_msg.GetResponseRequest.GetResponseData(
                    audio_data = data
                )
            )
        stream.stop_stream()
        stream.close()
        print("* recording stopped")

    config = configparser.ConfigParser()
    config.read("exts\convai\convai\convai.env")
    api_key = config.get("CONVAI", "API_KEY")
    character_id = config.get("CONVAI", "CHARACTER_ID")
    channel_address = config.get("CONVAI", "CHANNEL")

    channel = grpc.secure_channel(channel_address, grpc.ssl_channel_credentials())
    client = convai_service.ConvaiServiceStub(channel)
    for response in client.GetResponse(getGetResponseRequests(api_key, character_id)):
        if response.HasField("audio_response"):
            print("Stream Message: {} {} {}".format(response.session_id, response.audio_response.audio_config, response.audio_response.text_data))
            audio_player.append_to_stream(response.audio_response.audio_data)

        else:
            print("Stream Message: {}".format(response))
    p.terminate()

    # start_mic()
    time.sleep(10)




    # while 1:


    #     audio_player = ConvaiAudioPlayer(None)
    #     # data = stream.read(CHUNK)
    #     # _, data = scipy.io.wavfile.read("F:/Work/Convai/Tests/Welcome.wav")
    #     f = open("F:/Work/Convai/Tests/Welcome.wav", "rb")
    #     data = f.read()
    #     print(type(data))
    #     audio_player.append_to_stream(data)
    #     time.sleep(0.2)
    #     break

    # # stop_mic()
    # time.sleep(2)

    # with keyboard.Listener(on_press=on_press,on_release=on_release):
    #     while(1):
    #         time.sleep(0.1)
    #         continue
    #         print("running")