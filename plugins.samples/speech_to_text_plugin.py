import whisper
import sounddevice as sd
import numpy as np
import queue
import threading
from time import time

class SpeechToTextPlugin:
    def __init__(self):
        self.model = whisper.load_model("base")  # Load the Whisper model
        self.audio_queue = queue.Queue()
        self.audio_capture_thread = None
        self.samplerate = 16000
        self.block_size = 16000
        self.silence_threshold = 0.002
        self.min_audio_seconds = 4
        self.silence_duration = 1
        self.device_index = self.select_device_index()  # Prompt user to select device
        self.listening = False  # Flag to control the listening state

    def list_input_devices(self):
        """Lists available input devices."""
        devices = sd.query_devices()
        print("\nAvailable Input Devices:\n")
        input_devices = []
        for i, device in enumerate(devices):
            if device['max_input_channels'] > 0:
                print(f"{i}: {device['name']}")
                input_devices.append(device['name'])
        print("\n")
        return input_devices

    def select_device_index(self):
        """Prompt the user to select an input device index."""
        input_devices = self.list_input_devices()

        # Prompt user for device selection
        device_index = None
        while device_index is None:
            try:
                user_input = input("Select input device index: ")
                device_index = int(user_input)
                if device_index < 0 or device_index >= len(input_devices):
                    print(f"Invalid selection. Please choose a number between 0 and {len(input_devices) - 1}.")
                    device_index = None
            except ValueError:
                print("Please enter a valid number.")

        return device_index

    def on_user_input(self, input_prompt):
        """
        Capture audio input and transcribe it to text.

        :param input_prompt: The user input prompt (unused here).
        :return: The transcribed sentence.
        """
        if self.device_index is None:
            return "No input device selected. Please set the device index."

        # Start listening for audio input
        if not self.listening:
            self.listening = True
            self.audio_capture_thread = threading.Thread(
                target=self.capture_audio_in_background,
                args=(self.device_index, self.samplerate, self.block_size,
                      self.silence_threshold, self.silence_duration),
                daemon=True
            )
            self.audio_capture_thread.start()

        # Wait for transcription and return the result
        transcribed_text = self.wait_for_transcription()
        print(transcribed_text)
        return transcribed_text

    def wait_for_transcription(self):
        """Wait for audio to be transcribed and return the text."""
        audio_buffer = []

        # Continuously wait for audio data until a valid transcription is available
        while True:
            try:
                # Check for audio data in the queue
                while not self.audio_queue.empty():
                    audio_buffer.append(self.audio_queue.get())

                if audio_buffer:
                    # Concatenate buffered audio into a single numpy array
                    audio_segment = np.concatenate(audio_buffer, axis=0)
                    result = self.model.transcribe(audio_segment, fp16=False)
                    return result['text'].strip()  # Return the transcribed text

                # If no audio data yet, sleep briefly before checking again
                sd.sleep(100)  # 100 ms sleep

            except Exception as e:
                print(f"Error during transcription: {e}")
                return "Transcription error."

    def capture_audio_in_background(self, device_index, samplerate, block_size, silence_threshold, silence_duration):
        """Capture audio data in the background."""
        audio_capture_buffer = []  # Buffer to accumulate audio chunks
        silence_start_time = None  # Track when silence started

        def audio_callback(indata, frames, stream_time, status):
            """Callback function to process audio input."""
            nonlocal silence_start_time, audio_capture_buffer

            if status:
                print(f"Status: {status}")

            # Convert the incoming audio data to a numpy array
            audio_data = np.array(indata[:, 0], dtype=np.float32)
            audio_rms = self.rms_level(audio_data)

            if audio_rms >= silence_threshold:
                # Significant audio detected, append it to the buffer
                audio_capture_buffer.append(audio_data)
                silence_start_time = None  # Reset the silence timer
            else:
                # Silence detected
                if silence_start_time is None:
                    silence_start_time = time()  # Start silence timer
                elif (time() - silence_start_time) >= silence_duration:
                    # If silence duration is exceeded, finalize the audio segment
                    if audio_capture_buffer:
                        audio_segment = np.concatenate(audio_capture_buffer, axis=0)
                        self.audio_queue.put(audio_segment)  # Add the segment to the queue
                        audio_capture_buffer = []  # Clear the buffer after queueing
                    silence_start_time = None  # Reset silence timer

        # Start the audio stream and process audio in real-time
        with sd.InputStream(callback=audio_callback, device=device_index, channels=1, samplerate=samplerate, blocksize=block_size):
            while self.listening:
                sd.sleep(100)  # Keep the thread alive and listening


    @staticmethod
    def rms_level(audio_data):
        """Calculate the root mean square (RMS) level of the audio data."""
        return np.sqrt(np.mean(np.square(audio_data)))

    def on_exit(self):
        """Method to stop audio capture."""
        self.listening = False
        if self.audio_capture_thread is not None:
            self.audio_capture_thread.join()
