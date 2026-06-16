"""
DEPRECATED — use main.py instead.
This file is an older standalone version kept for reference only.
It will be removed in a future cleanup.
"""
raise SystemExit(
    'This file is deprecated. Run: python main.py'
)

"""
Agentic Voice Assistant with Groq Whisper API
Uses Groq's ultra-fast Whisper implementation for speech recognition
"""

import os
import time
import tempfile
import wave
import numpy as np
import pyttsx3
from dotenv import load_dotenv
from groq import Groq
import pyaudio

load_dotenv()

# Audio configuration
FORMAT = pyaudio.paInt16
CHANNELS = 1
RATE = 16000
CHUNK = 1024
SILENCE_THRESHOLD = 500  # Energy threshold for silence detection
SILENCE_DURATION = 1.5   # Seconds of silence to stop recording
MAX_RECORD_SECONDS = 10  # Max recording length

class VoiceAssistant:
    def __init__(self):
        print("=" * 50)
        print("🎙️ Agentic Voice Assistant - Groq Whisper")
        print("=" * 50)
        
        # Initialize TTS
        print("\n🔊 Loading voice...")
        self.tts = pyttsx3.init()
        self.tts.setProperty('rate', 160)
        voices = self.tts.getProperty('voices')
        for voice in voices:
            if 'david' in voice.name.lower():
                self.tts.setProperty('voice', voice.id)
                break
        print("✅ Voice ready")
        
        # Initialize Groq client (for both Whisper and LLM)
        print("\n🧠 Loading Groq...")
        api_key = os.getenv("GROQ_API_KEY")
        if not api_key:
            print("❌ No GROQ_API_KEY in .env file")
            exit(1)
        
        self.client = Groq(api_key=api_key)
        print("✅ Groq ready (Whisper + Llama)")
        
        # Initialize PyAudio
        print("\n🎤 Initializing microphone...")
        self.audio = pyaudio.PyAudio()
        
        # List available devices
        for i in range(self.audio.get_device_count()):
            dev = self.audio.get_device_info_by_index(i)
            if dev['maxInputChannels'] > 0:
                print(f"   Device {i}: {dev['name']}")
        
        self.mic_index = self.find_headset_mic()
        print(f"✅ Using microphone index: {self.mic_index}")
        
        self.sample_rate = RATE
        self.chunk = CHUNK
        
        print("\n" + "=" * 50)
        print("✅ Assistant Ready!")
        print("Commands: 'v' (voice), 't' (text), 'q' (quit)")
        print("=" * 50)
    
    def find_headset_mic(self):
        """Find the headset microphone device"""
        for i in range(self.audio.get_device_count()):
            dev = self.audio.get_device_info_by_index(i)
            if dev['maxInputChannels'] > 0:
                name = dev['name'].lower()
                if 'headset' in name or 'boult' in name:
                    return i
        # Fallback to default
        return self.audio.get_default_input_device_info()['index']
    
    def record_audio(self):
        """Record audio until silence or max duration"""
        print("\n🎤 Recording... Speak now (max 10 seconds)")
        
        stream = self.audio.open(
            format=FORMAT,
            channels=CHANNELS,
            rate=RATE,
            input=True,
            input_device_index=self.mic_index,
            frames_per_buffer=CHUNK
        )
        
        frames = []
        silent_chunks = 0
        max_silent_chunks = int(SILENCE_DURATION * RATE / CHUNK)
        speaking = False
        
        for _ in range(int(MAX_RECORD_SECONDS * RATE / CHUNK)):
            data = stream.read(CHUNK, exception_on_overflow=False)
            frames.append(data)
            
            # Convert to numpy for energy calculation
            audio_data = np.frombuffer(data, dtype=np.int16)
            energy = np.abs(audio_data).mean()
            
            if energy > SILENCE_THRESHOLD:
                speaking = True
                silent_chunks = 0
                # Visual feedback
                print(".", end="", flush=True)
            elif speaking:
                silent_chunks += 1
                if silent_chunks > max_silent_chunks:
                    print("\n✅ Silence detected, stopping...")
                    break
        
        stream.stop_stream()
        stream.close()
        
        if not speaking:
            print("\n❌ No speech detected")
            return None
        
        print(f"\n🎙️ Recorded {len(frames)} chunks")
        
        # Save to temporary WAV file
        temp_file = tempfile.NamedTemporaryFile(delete=False, suffix=".wav")
        with wave.open(temp_file.name, 'wb') as wf:
            wf.setnchannels(CHANNELS)
            wf.setsampwidth(self.audio.get_sample_size(FORMAT))
            wf.setframerate(RATE)
            wf.writeframes(b''.join(frames))
        
        return temp_file.name
    
    def transcribe_audio(self, audio_file):
        """Send audio to Groq Whisper API for transcription"""
        print("📝 Transcribing with Groq Whisper...")
        
        with open(audio_file, 'rb') as file:
            transcription = self.client.audio.transcriptions.create(
                file=(audio_file, file.read()),
                model="whisper-large-v3",
                language="en",
                response_format="text"
            )
        
        # Clean up temp file
        os.unlink(audio_file)
        
        return transcription
    
    def ask_llm(self, question):
        """Ask Groq Llama for response"""
        print("🧠 Thinking...")
        response = self.client.chat.completions.create(
            model="llama3-70b-8192",
            messages=[
                {"role": "system", "content": "You are a helpful voice assistant. Be very concise. Answer in 1-2 short sentences."},
                {"role": "user", "content": question}
            ],
            max_tokens=200,
            temperature=0.7
        )
        return response.choices[0].message.content
    
    def speak(self, text):
        """Text to speech output"""
        print(f"\n🤖 {text}")
        self.tts.say(text)
        self.tts.runAndWait()
    
    def process_voice(self):
        """Full voice pipeline: record -> transcribe -> LLM -> speak"""
        audio_file = self.record_audio()
        if not audio_file:
            return
        
        try:
            text = self.transcribe_audio(audio_file)
            print(f"📝 You said: {text}")
            
            if text and text.strip():
                response = self.ask_llm(text)
                self.speak(response)
        except Exception as e:
            print(f"❌ Error: {e}")
            self.speak("Sorry, I couldn't understand that. Please try again.")
    
    def process_text(self, text):
        """Process text input"""
        response = self.ask_llm(text)
        self.speak(response)
    
    def run(self):
        """Main loop"""
        while True:
            cmd = input("\n> ").strip().lower()
            
            if cmd == 'q':
                self.speak("Goodbye!")
                break
            elif cmd == 'v':
                self.process_voice()
            elif cmd == 't':
                text = input("You: ").strip()
                if text:
                    self.process_text(text)
            elif cmd:
                print("Commands: v (voice), t (text), q (quit)")

if __name__ == "__main__":
    assistant = VoiceAssistant()
    assistant.run()