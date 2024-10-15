import threading
import queue
import nltk
from openai import OpenAI
import io
import soundfile as sf
import sounddevice as sd

# Download the NLTK tokenizer data for sentence splitting
nltk.download('punkt')
nltk.download('punkt_tab')

class TextToSpeechPlugin:
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.client = OpenAI()
        self.sentence_queue = queue.Queue()
        self.buffer_queue = queue.Queue()
        self.playback_queue = queue.Queue()
        self.stop_thread = threading.Event()

        # Variable to accumulate words until a full sentence is formed
        self.text_buffer = ""

        # Start the threads
        self.voice_thread = threading.Thread(target=self.process_queue)
        self.buffer_thread = threading.Thread(target=self.generate_buffers)
        self.playback_thread = threading.Thread(target=self.play_buffers)
        self.voice_thread.start()
        self.buffer_thread.start()
        self.playback_thread.start()

    def on_llm_token_response(self, text: str):
        # Accumulate incoming words into the buffer
        self.text_buffer += text

        # Check if the buffer contains any complete sentences
        sentences = nltk.sent_tokenize(self.text_buffer)

        # If there are any complete sentences, process them
        if sentences:
            # Keep the last incomplete sentence in the buffer
            self.text_buffer = sentences[-1]
            
            # Add complete sentences to the sentence queue
            for sentence in sentences[:-1]:
                self.sentence_queue.put(sentence)
                
        return False
    
    def on_user_input_done(self, user_input=None, verbose_mode=False):
        # Process the last incomplete sentence in the buffer
        if self.text_buffer:
            # Make sure all sentences are processed before the user input is done
            while not self.sentence_queue.empty() or not self.playback_queue.empty():
                # Wait for the queue to be processed
                pass

            self.text_buffer = ""
        return False
    
    def on_llm_response(self, response):
        # Ignore the response and call the on_llm_token_response method with a special <|endoftext|> token
        self.on_llm_token_response(" <|endoftext|>")

        # Wait for all buffers to be processed and audio to be played
        while not self.buffer_queue.empty() or not self.playback_queue.empty():
            # This will ensure the method waits until both queues are empty before returning
            threading.Event().wait(0.1)  # Add a small delay to avoid tight looping

        # Ensure all playback is finished
        sd.wait()  # Wait for any ongoing playback to complete

        return False

    def process_queue(self):
        while not self.stop_thread.is_set():
            try:
                # Get the next sentence to process from the queue
                sentence = self.sentence_queue.get(timeout=1)  # 1-second timeout
                if sentence:
                    self.buffer_queue.put(sentence)
            except queue.Empty:
                continue

    def generate_buffers(self):
        while not self.stop_thread.is_set():
            try:
                # Get the next sentence to process from the buffer queue
                sentence = self.buffer_queue.get(timeout=1)  # 1-second timeout
                if sentence:
                    # Generate spoken response for the sentence
                    spoken_response = self.client.audio.speech.create(
                        model="tts-1-hd",
                        voice="nova",
                        response_format="opus",
                        input=sentence
                    )

                    buffer = io.BytesIO()
                    for chunk in spoken_response.iter_bytes(chunk_size=4096):
                        buffer.write(chunk)
                    buffer.seek(0)
                    self.playback_queue.put(buffer)
            except queue.Empty:
                continue

    def play_buffers(self):
        while not self.stop_thread.is_set():
            try:
                # Get the next buffer to play
                buffer = self.playback_queue.get(timeout=1)  # 1-second timeout
                if buffer:
                    # Play the generated voice
                    with sf.SoundFile(buffer, 'r') as sound_file:
                        data = sound_file.read(dtype='int16')
                        sd.play(data, sound_file.samplerate)
                        sd.wait()
            except queue.Empty:
                continue

    def stop(self):
        # Stop the threads when done
        self.stop_thread.set()
        self.voice_thread.join()
        self.buffer_thread.join()
        self.playback_thread.join()

    def on_exit(self):
        # Gracefully stop the background threads
        self.stop()
