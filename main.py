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
from dotenv import load_dotenv
from groq import Groq

from src.audio.mic import EnhancedMicrophone
from src.audio.wakeword import TextWakeWordDetector
from src.memory import UserMemory
from src.agent import AgentCore
from src.tools import ToolRegistry
from src.tools.builtins import ALL_BUILTIN_TOOLS
from src.tools.reminders import ReminderService, create_reminder_tool

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
# Audio synthesis is managed by TTSEngine (supporting ElevenLabs + pyttsx3 fallback).
TTS_RATE = 160
TTS_VOICE_KEYWORD = 'david'
TTS_TIMEOUT = 30  # seconds — safety limit so we never hang forever
print("✅ TTS ready (TTSEngine)")

# ── Groq ─────────────────────────────────────────────────────
print("\n🧠 Initializing Groq...")
api_key = os.getenv("GROQ_API_KEY")
if not api_key:
    print("❌ No GROQ_API_KEY found in .env file")
    print("   Get one from: https://console.groq.com")
    sys.exit(1)
client = Groq(api_key=api_key)
print("✅ Groq ready (Whisper + Llama)")

# ── Persistent user memory ───────────────────────────────────
print("\n🧠 Loading user memory...")
memory = UserMemory(filepath=os.path.join(os.path.dirname(__file__), "user_memory.json"))
print(f"✅ User memory ready ({memory.fact_count} fact(s) loaded)")

# ── Tool registry ────────────────────────────────────────────
print("\n🔧 Registering tools...")
tool_registry = ToolRegistry()
for tool in ALL_BUILTIN_TOOLS:
    tool_registry.register(tool)
print(f"✅ {tool_registry.count} built-in tool(s) registered: {tool_registry.tool_names}")

# Register Browser tools
try:
    from src.tools.browser import BROWSER_TOOLS
    for tool in BROWSER_TOOLS:
        tool_registry.register(tool)
    print(f"✅ Browser tools registered")
except ImportError as e:
    print(f"⚠️ Browser tools not available: {e}")

# Register General tools
try:
    from src.tools.general_tools import GENERAL_TOOLS
    for tool in GENERAL_TOOLS:
        tool_registry.register(tool)
    print(f"✅ General tools registered")
except ImportError as e:
    print(f"⚠️ General tools not available: {e}")

# Register Email/Calendar via MCP
try:
    from src.tools.email_tool import EMAIL_TOOLS
    from src.tools.calendar_tool import CALENDAR_TOOLS
    from src.tools.mcp_adapter import MCPPluginAdapter
    
    mcp_adapter = MCPPluginAdapter()
    mcp_adapter.register_tools("email", EMAIL_TOOLS)
    mcp_adapter.register_tools("calendar", CALENDAR_TOOLS)
    installed_count = mcp_adapter.install_into_registry(tool_registry)
    print(f"✅ MCP tools registered: {installed_count} tools across 2 servers")
except ImportError as e:
    print(f"⚠️ MCP tools not available: {e}")

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

# ── Reminder service (needs speak(), which is defined below) ─
# Initialized later after speak() is defined.
reminder_service = None
agent = None

# ── TTS lock — prevents reminder and command speech from colliding ─
_tts_lock = threading.Lock()


# ── TTS Engine ───────────────────────────────────────────────
from src.audio.tts import TTSEngine
tts_engine = TTSEngine(rate=TTS_RATE, voice_keyword=TTS_VOICE_KEYWORD)


def speak(text: str):
    """Mute mic → TTS with barge-in support → unmute with cooldown."""
    with _tts_lock:
        print(f"\n🤖 {text}")

        try:
            # 1. Before starting TTS, set barge_in_mode = True and clear barge_in_event
            mic.barge_in_mode = True
            mic.barge_in_event.clear()

            with mic._mute_lock:
                mic.muted = True

            # Start TTS in a background thread to allow polling/interruption
            t = threading.Thread(
                target=tts_engine.speak,
                args=(text, TTS_TIMEOUT),
                daemon=True
            )
            t.start()

            # 2. While TTS is playing, poll mic.barge_in_event
            waited = 0.0
            interrupted = False
            while t.is_alive() and waited < TTS_TIMEOUT:
                if mic.barge_in_event.is_set():
                    print("\n   💥 Barge-in detected! Stopping TTS playback...")
                    tts_engine.stop()
                    interrupted = True
                    break
                t.join(timeout=0.1)
                waited += 0.1
                if _shutdown.is_set():
                    break

            if not interrupted and t.is_alive():
                print("   ⚠️ TTS timed out, continuing...")

            # Small pause for driver buffer to drain
            time.sleep(0.3)

        finally:
            # 4. Cleanup barge_in_mode
            mic.barge_in_mode = False

            # Reset model state and set cooldown
            mic.set_wakeword_cooldown(2)

            with mic._mute_lock:
                mic._just_unmuted = True
                mic.muted = False

            print("\n🎤 Listening for wake word...")


def audio_to_wav_file(audio: np.ndarray) -> str:
    """Save int16 numpy buffer to a temp WAV file."""
    tmp = tempfile.NamedTemporaryFile(delete=False, suffix='.wav')
    tmp_name = tmp.name
    tmp.close()  # Close handle to avoid ResourceWarning
    with wave.open(tmp_name, 'wb') as wf:
        wf.setnchannels(CHANNELS)
        wf.setsampwidth(SAMPLE_WIDTH)
        wf.setframerate(RATE)
        wf.writeframes(audio.astype(np.int16).tobytes())
    return tmp_name


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


def voice_confirm(tool_name: str, description: str) -> bool:
    """Speak a confirmation prompt, listen via mic, transcribe, check for yes/no."""
    speak(f"I'm about to {description}. Should I proceed?")

    print("🎤 Waiting for confirmation...")
    mic.wake_word_triggered = True     # Skip wake word detection
    mic.is_capturing = True
    mic._capture_start_time = time.time()
    mic.silence_frames = 0
    mic.current_utterance = []
    mic.max_capture_seconds = 5        # Short capture window

    with mic._mute_lock:
        mic._just_unmuted = True
        mic.muted = False

    try:
        utterance = mic.get_utterance(timeout=6)

        # Re-mute since we're still in process_wake_command
        with mic._mute_lock:
            mic.muted = True

        if utterance is None or len(utterance) == 0:
            speak("I didn't hear a response. Cancelling.")
            return False

        wav_path = audio_to_wav_file(utterance)
        transcript = transcribe_audio(wav_path).strip().lower()
        print(f"   📝 Confirmation response: '{transcript}'")

        yes_words = {"yes", "yeah", "yep", "sure", "go ahead", "do it", "okay", "ok", "confirm"}
        return any(word in transcript for word in yes_words)
    finally:
        mic.max_capture_seconds = 10   # Always restore, even on timeout/error


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

        print("\n🎯 Processing with agent...")
        try:
            response = agent.run(
                user_message=cleaned,
                conversation_history=conversation_history,
                confirm_callback=voice_confirm,
            )
        except Exception as e:
            print(f"\n❌ Agent error: {e}")
            speak("Something went wrong. Please try again.")
            return

        # Save this exchange to history, trim to window
        conversation_history.append({"role": "user", "content": cleaned})
        conversation_history.append({"role": "assistant", "content": response})
        if len(conversation_history) > MAX_HISTORY_TURNS * 2:
            del conversation_history[:2]  # drop oldest exchange

        # Extract user facts in background (non-blocking)
        threading.Thread(
            target=memory.extract_and_store,
            args=(cleaned, response, client),
            daemon=True,
        ).start()

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


def _init_services():
    """Initialize services that depend on speak() being defined."""
    global reminder_service, agent

    # Reminder service — uses speak() for TTS
    print("\n⏰ Starting reminder service...")
    reminder_service = ReminderService(
        filepath=os.path.join(os.path.dirname(__file__), "reminders.json"),
        speak_callback=speak,
    )
    reminder_tool = create_reminder_tool(reminder_service)
    tool_registry.register(reminder_tool)
    reminder_service.start()
    print(f"✅ Tools ready: {tool_registry.tool_names}")

    # Agent core — the reasoning loop
    print("\n🧠 Initializing agent core...")
    agent = AgentCore(
        groq_client=client,
        memory=memory,
        tool_registry=tool_registry,
        max_steps=5,
    )
    print("✅ Agent core ready")


def run_wake_word_mode():
    """Start the assistant in wake word mode and keep listening."""
    _init_services()

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
            if reminder_service:
                reminder_service.stop()
        except Exception:
            pass
        try:
            mic.stop_listening()
        except Exception:
            pass
        print("👋 Session ended")
        os._exit(0)


if __name__ == "__main__":
    run_wake_word_mode()