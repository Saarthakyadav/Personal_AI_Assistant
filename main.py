# main.py
"""
Agentic Voice AI - Nova Assistant
Starts automatically in wake word mode using src/audio/mic.py and src/audio/wakeword.py.
"""

import sys
import io

# Force UTF-8 output on Windows (CP1252 can't handle emoji)
if sys.stdout.encoding != 'utf-8':
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')
if sys.stderr.encoding != 'utf-8':
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding='utf-8', errors='replace')

import os
import signal
import tempfile
import wave
import time
import threading

# ── Graceful shutdown flag ───────────────────────────────────
_shutdown = threading.Event()

def _sigint_handler(sig, frame):
    """Set the shutdown flag so every loop can check it cleanly."""
    print("\n\n🛑 Ctrl+C received — shutting down...")
    _shutdown.set()

signal.signal(signal.SIGINT, _sigint_handler)

import numpy as np
import pyttsx3
from dotenv import load_dotenv
from groq import Groq

from src.audio.mic import EnhancedMicrophone
from src.audio.wakeword import TextWakeWordDetector

load_dotenv()

RATE         = 16000
CHANNELS     = 1
SAMPLE_WIDTH = 2
WAKE_WORDS   = ["alexa", "hey jarvis"]

# FIX #10: conversation memory — keep last N exchanges for context
MAX_HISTORY_TURNS = 10
conversation_history = []

print("=" * 60)
print("🎙️ Agentic Voice AI - Nova Assistant")
print("=" * 60)

# ── TTS config ───────────────────────────────────────────────
# pyttsx3 engine is created fresh per call inside the TTS thread.
# Reusing a global engine from a non-main thread causes COM deadlocks on Windows.
TTS_RATE = 160
TTS_VOICE_KEYWORD = 'david'
TTS_TIMEOUT = 30  # seconds — safety limit so we never hang forever
print("✅ TTS ready (per-call engine)")

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
def _tts_speak(text: str):
    """Create a fresh pyttsx3 engine per call to avoid Windows COM deadlock."""
    try:
        engine = pyttsx3.init()
        engine.setProperty('rate', TTS_RATE)
        for voice in engine.getProperty('voices'):
            if TTS_VOICE_KEYWORD in voice.name.lower():
                engine.setProperty('voice', voice.id)
                break
        engine.say(text)
        engine.runAndWait()
        engine.stop()
    except Exception as e:
        print(f"   ⚠️ TTS error: {e}")


def speak(text: str):
    """Mute mic → TTS in a fresh-engine thread → unmute with cooldown."""
    print(f"\n🤖 {text}")

    try:
        with mic._mute_lock:
            mic.muted = True

        t = threading.Thread(
            target=_tts_speak,
            args=(text,),
            daemon=True
        )
        t.start()

        # Join with short timeouts so main thread stays interruptible.
        # Safety cap: if TTS hangs longer than TTS_TIMEOUT, move on.
        waited = 0.0
        while t.is_alive() and waited < TTS_TIMEOUT:
            t.join(timeout=0.1)
            waited += 0.1
            if _shutdown.is_set():
                break

        if t.is_alive():
            print("   ⚠️ TTS timed out, continuing...")

        # Small pause for driver buffer to drain
        time.sleep(0.3)

    finally:
        # Reset model state and set cooldown
        mic.set_wakeword_cooldown(2)

        with mic._mute_lock:
            mic._just_unmuted = True
            mic.muted = False

        print("\n🎤 Listening for wake word...")


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
    # FIX #9: always clean up temp file even if transcription fails
    try:
        with open(audio_file, 'rb') as f:
            result = client.audio.transcriptions.create(
                file=(audio_file, f.read()),
                model="whisper-large-v3",
                language="en",
                response_format="text",
            )
        return result
    finally:
        try:
            os.unlink(audio_file)
        except Exception:
            pass


def ask_llm(question: str) -> str:
    """Query Groq Llama with rolling conversation history."""
    print("   🧠 Thinking...")

    # FIX #10: build messages with full history for context
    system_msg = {
        "role": "system",
        "content": (
            "You are a helpful voice assistant named Nova. "
            "Be concise and direct. Keep replies to 1-3 sentences."
        )
    }
    messages = [system_msg] + conversation_history + [{"role": "user", "content": question}]

    resp = client.chat.completions.create(
        model="llama-3.3-70b-versatile",
        messages=messages,
        max_tokens=200,
        temperature=0.7,
    )
    return resp.choices[0].message.content


def process_wake_command(audio: np.ndarray):
    # Mute mic immediately so the model can't false-trigger during
    # transcription + LLM (which can take 2-5 seconds).
    with mic._mute_lock:
        mic.muted = True

    try:
        if audio is None or len(audio) == 0:
            speak("I didn't capture any command. Please try again.")
            return

        wav_path = audio_to_wav_file(audio)
        try:
            transcript = transcribe_audio(wav_path)
        except Exception as e:
            print(f"\n❌ Transcription error: {e}")
            speak("I couldn't transcribe that. Please try again.")
            return

        if not transcript or len(transcript.strip().split()) < 2:
            print("   ⚠️ Too short, ignoring (likely noise)")
            return

        cleaned = transcript
        if wakeword_cleanup.detect_in_text(transcript):
            cleaned = wakeword_cleanup.remove_wake_word(transcript)

        print(f"\n📝 Heard: {transcript}")
        if cleaned != transcript:
            print(f"📝 Command: {cleaned}")

        if not cleaned.strip():
            speak("I heard the wake word but not a command. Please try again.")
            return

        print("\n🎯 Processing...")
        try:
            response = ask_llm(cleaned)
        except Exception as e:
            print(f"\n❌ LLM error: {e}")
            speak("Something went wrong. Please try again.")
            return

        # FIX #10: save this exchange to history, trim to window
        conversation_history.append({"role": "user", "content": cleaned})
        conversation_history.append({"role": "assistant", "content": response})
        if len(conversation_history) > MAX_HISTORY_TURNS * 2:
            del conversation_history[:2]  # drop oldest exchange

        speak(response)

    finally:
        # Safety unmute: always guarantee mic is unmuted when we exit.
        # speak() already unmutes + sets cooldown on the normal path,
        # but early-return paths (e.g. "too short") skip speak().
        with mic._mute_lock:
            if mic.muted:
                mic.set_wakeword_cooldown(2)
                mic._just_unmuted = True
                mic.muted = False
                print("\n🎤 Listening for wake word...")


def run_wake_word_mode():
    """Start the assistant in wake word mode and keep listening."""
    print("\n✅ Nova Assistant Ready!")
    print(f"   Say 'Alexa' or 'Hey Jarvis' to activate")
    print("   Press Ctrl+C to quit")
    print("─" * 60)

    try:
        while not _shutdown.is_set():
            utterance = mic.get_utterance(timeout=0.5)
            if utterance is None:
                continue
            print("\n🟢 Wake word detected. Processing command...")
            process_wake_command(utterance)

    finally:
        print("\n🛑 Stopping assistant...")
        try:
            mic.stop_listening()
        except Exception:
            pass
        print("👋 Session ended")
        os._exit(0)


if __name__ == "__main__":
    run_wake_word_mode()