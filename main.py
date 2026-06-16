# main.py
"""
Agentic Voice AI - Nova Assistant
Starts automatically in wake word mode using src/audio/mic.py and src/audio/wakeword.py.
"""

import os
import sys
import tempfile
import wave
import time

import numpy as np
import pyttsx3
from dotenv import load_dotenv
from groq import Groq

from src.audio.mic import EnhancedMicrophone
from src.audio.wakeword import TextWakeWordDetector

load_dotenv()

RATE        = 16000
CHANNELS    = 1
SAMPLE_WIDTH = 2
WAKE_WORDS  = ["alexa", "hey jarvis"]

print("=" * 60)
print("🎙️ Agentic Voice AI - Nova Assistant")
print("=" * 60)

# ── TTS ──────────────────────────────────────────────────────
print("\n🔊 Initializing TTS...")
tts = pyttsx3.init()
tts.setProperty('rate', 160)
for voice in tts.getProperty('voices'):
    if 'david' in voice.name.lower():
        tts.setProperty('voice', voice.id)
        print(f"   ✅ Voice: {voice.name}")
        break
print("✅ TTS ready")

# ── Groq ─────────────────────────────────────────────────────
print("\n🧠 Initializing Groq...")
api_key = os.getenv("GROQ_API_KEY")
if not api_key:
    print("❌ No GROQ_API_KEY found in .env file")
    print("   Get one from: https://console.groq.com")
    sys.exit(1)
client = Groq(api_key=api_key)
print("✅ Groq ready (Whisper + Llama)")

# ── Microphone ───────────────────────────────────────────────
print("\n🎤 Initializing wake word microphone...")
try:
    mic = EnhancedMicrophone(
        sample_rate=RATE,
        frame_duration_ms=30,
        silence_timeout=1.5,
        wake_words=WAKE_WORDS,
        use_ml_wakeword=True,
    )
    mic.start_listening()
    print("✅ Wake word microphone ready")
except Exception as e:
    print(f"❌ Failed to initialize wake word microphone: {e}")
    sys.exit(1)

wakeword_cleanup = TextWakeWordDetector(wake_words=WAKE_WORDS)


# ─────────────────────────────────────────────────────────────
def speak(text: str):
    print(f"\n🤖 {text}")

    with mic._mute_lock:
        mic.muted = True

    tts.say(text)
    tts.runAndWait()

    # allow speaker echo to die down
    time.sleep(1.0)

    with mic._mute_lock:
        mic.muted = False

    # ignore wake words for 3 seconds
    mic.set_wakeword_cooldown(3)



def audio_to_wav_file(audio: np.ndarray) -> str:
    """Save int16 numpy buffer to a temp WAV file."""
    tmp = tempfile.NamedTemporaryFile(delete=False, suffix='.wav')
    with wave.open(tmp.name, 'wb') as wf:
        wf.setnchannels(CHANNELS)
        wf.setsampwidth(SAMPLE_WIDTH)
        wf.setframerate(RATE)
        wf.writeframes(audio.astype(np.int16).tobytes())
    return tmp.name


def transcribe_audio(audio_file: str) -> str:
    """Transcribe audio using Groq Whisper."""
    print("   📝 Transcribing with Whisper...")
    with open(audio_file, 'rb') as f:
        result = client.audio.transcriptions.create(
            file=(audio_file, f.read()),
            model="whisper-large-v3",
            language="en",
            response_format="text",
        )
    try:
        os.unlink(audio_file)
    except Exception:
        pass
    return result


def ask_llm(question: str) -> str:
    """Query Groq Llama."""
    print("   🧠 Thinking...")
    resp = client.chat.completions.create(
        model="llama-3.3-70b-versatile",
        messages=[
            {"role": "system", "content": "You are a helpful voice assistant named Nova. Be concise and direct."},
            {"role": "user",   "content": question},
        ],
        max_tokens=200,
        temperature=0.7,
    )
    return resp.choices[0].message.content


def process_wake_command(audio: np.ndarray):
    if audio is None or len(audio) == 0:
        with mic._mute_lock:
            mic.muted = False
        speak("I didn't capture any command. Please try again.")
        return

    wav_path = audio_to_wav_file(audio)
    try:
        transcript = transcribe_audio(wav_path)
        if not transcript or len(transcript.strip().split()) < 2:
            print("   ⚠️ Too short, ignoring (likely noise)")
            with mic._mute_lock:
                mic.muted = False  # ← must unmute here too
            return
    except Exception as e:
        print(f"\n❌ Transcription error: {e}")
        with mic._mute_lock:
            mic.muted = False
        speak("I couldn't transcribe that. Please try again.")
        return

    cleaned = transcript
    if wakeword_cleanup.detect_in_text(transcript):
        cleaned = wakeword_cleanup.remove_wake_word(transcript)

    print(f"\n📝 Heard: {transcript}")
    if cleaned != transcript:
        print(f"📝 Command: {cleaned}")

    if not cleaned.strip():
        with mic._mute_lock:
            mic.muted = False
        speak("I heard the wake word but not a command. Please try again.")
        return

    print("\n🎯 Processing...")
    try:
        response = ask_llm(cleaned)
        speak(response)
    except Exception as e:
        print(f"\n❌ LLM error: {e}")
        with mic._mute_lock:
            mic.muted = False
        speak("Something went wrong. Please try again.")


def run_wake_word_mode():
    """Start the assistant in wake word mode and keep listening."""
    print("\n✅ Nova Assistant Ready!")
    print(f"   Say 'Alexa' or 'Hey Jarvis' to activate")
    print("   Press Ctrl+C to quit")
    print("─" * 60)

    try:
        while True:
            utterance = mic.get_utterance(timeout=0.5)
            if utterance is None:
                continue
            print("\n🟢 Wake word detected. Processing command...")
            process_wake_command(utterance)
            print("\n👂 Listening for wake word again...")

    except KeyboardInterrupt:
        print("\n\n🛑 Stopping assistant.")

    finally:
        mic.stop_listening()
        print("\n👋 Session ended")


if __name__ == "__main__":
    run_wake_word_mode()