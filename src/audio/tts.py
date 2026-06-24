# src/audio/tts.py
"""
TTS Engine for Nova — ElevenLabs (premium) + pyttsx3 (offline fallback).

Matches the Architecture v3 flowchart box: "TTS — Piper / ElevenLabs"

Priority order:
  1. ElevenLabs (if ELEVENLABS_API_KEY is set and the package is installed)
  2. pyttsx3 (always available, local, no API key)

The engine is thread-safe and supports stop() for barge-in interruption.
"""

import os
import threading
import tempfile
import time
from typing import Optional, Callable


class TTSEngine:
    """
    Unified TTS engine with ElevenLabs premium and pyttsx3 fallback.
    Thread-safe, supports stop() for barge-in.
    """

    def __init__(self, rate: int = 160, voice_keyword: str = "david"):
        self._rate = rate
        self._voice_keyword = voice_keyword
        self._speaking = False
        self._stop_event = threading.Event()
        self._lock = threading.Lock()
        self._backend = "pyttsx3"  # default

        # Try to initialize ElevenLabs
        self._eleven_api_key = os.getenv("ELEVENLABS_API_KEY", "")
        self._eleven_available = False

        if self._eleven_api_key:
            try:
                import elevenlabs
                self._eleven_available = True
                self._backend = "elevenlabs"
                print("✅ TTS: ElevenLabs available (premium)")
            except ImportError:
                print("⚠️  TTS: elevenlabs package not installed, using pyttsx3 fallback")
        else:
            print("ℹ️  TTS: No ELEVENLABS_API_KEY, using pyttsx3 (offline)")

        print(f"✅ TTS engine ready (backend: {self._backend})")

    @property
    def backend(self) -> str:
        return self._backend

    @property
    def is_speaking(self) -> bool:
        return self._speaking

    def speak(self, text: str, timeout: float = 30.0) -> bool:
        """
        Speak the given text. Returns True if completed, False if interrupted.

        Thread-safe: blocks until speech finishes or stop() is called.
        """
        with self._lock:
            self._speaking = True
            self._stop_event.clear()

        try:
            if self._backend == "elevenlabs":
                success = self._speak_elevenlabs(text, timeout)
                if not success:
                    # Fallback to pyttsx3 if ElevenLabs fails
                    print("   ⚠️ ElevenLabs failed, falling back to pyttsx3")
                    return self._speak_pyttsx3(text, timeout)
                return success
            else:
                return self._speak_pyttsx3(text, timeout)
        finally:
            self._speaking = False

    def stop(self):
        """Interrupt current speech (for barge-in)."""
        self._stop_event.set()

    def _speak_elevenlabs(self, text: str, timeout: float) -> bool:
        """Speak using ElevenLabs API."""
        try:
            from elevenlabs.client import ElevenLabs
            from elevenlabs import play

            if self._stop_event.is_set():
                return False

            client = ElevenLabs(api_key=self._eleven_api_key)

            # Generate audio
            audio = client.text_to_speech.convert(
                text=text,
                voice_id="pNInz6obpgDQGcFmaJgB",  # "Adam" voice — clear, natural
                model_id="eleven_multilingual_v2",
                output_format="pcm_16000",
            )

            if self._stop_event.is_set():
                return False

            # Save to temp file as WAV and play
            tmp = tempfile.NamedTemporaryFile(delete=False, suffix=".wav")
            try:
                import wave
                with wave.open(tmp.name, 'wb') as wav_file:
                    wav_file.setnchannels(1)
                    wav_file.setsampwidth(2)  # 16-bit PCM is 2 bytes
                    wav_file.setframerate(16000)
                    for chunk in audio:
                        if self._stop_event.is_set():
                            tmp.close()
                            return False
                        wav_file.writeframes(chunk)
                tmp.close()

                if self._stop_event.is_set():
                    return False

                # Play audio using a subprocess to allow interruption
                self._play_audio_file(tmp.name, timeout)

                return not self._stop_event.is_set()
            finally:
                try:
                    os.unlink(tmp.name)
                except Exception:
                    pass

        except Exception as e:
            print(f"   ⚠️ ElevenLabs TTS error: {e}")
            return False

    def _play_audio_file(self, filepath: str, timeout: float):
        """Play an audio file, interruptible via stop_event."""
        import subprocess

        try:
            # Use ffplay (comes with ffmpeg) or platform-specific player
            if os.name == "nt":
                # Windows: use the built-in media player via PowerShell
                proc = subprocess.Popen(
                    [
                        "powershell", "-WindowStyle", "Hidden", "-Command",
                        f"(New-Object Media.SoundPlayer '{filepath}').PlaySync()"
                    ],
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                )
            else:
                # Linux/Mac: try ffplay, then aplay
                proc = subprocess.Popen(
                    ["ffplay", "-nodisp", "-autoexit", "-loglevel", "quiet", filepath],
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                )

            # Wait for completion or stop signal
            waited = 0.0
            while proc.poll() is None and waited < timeout:
                if self._stop_event.is_set():
                    proc.terminate()
                    try:
                        proc.wait(timeout=1)
                    except subprocess.TimeoutExpired:
                        proc.kill()
                    return
                time.sleep(0.1)
                waited += 0.1

            if proc.poll() is None:
                proc.terminate()

        except FileNotFoundError:
            # ffplay/powershell not available — try pygame as last resort
            try:
                import pygame
                pygame.mixer.init()
                pygame.mixer.music.load(filepath)
                pygame.mixer.music.play()
                while pygame.mixer.music.get_busy():
                    if self._stop_event.is_set():
                        pygame.mixer.music.stop()
                        return
                    time.sleep(0.1)
            except ImportError:
                print("   ⚠️ No audio player available for ElevenLabs output")
        except Exception as e:
            print(f"   ⚠️ Audio playback error: {e}")

    def _speak_pyttsx3(self, text: str, timeout: float) -> bool:
        """Speak using pyttsx3 (offline, local)."""
        try:
            import pyttsx3

            if self._stop_event.is_set():
                return False

            # Create engine fresh per call to avoid COM deadlocks on Windows
            engine = pyttsx3.init()
            engine.setProperty('rate', self._rate)

            for voice in engine.getProperty('voices'):
                if self._voice_keyword in voice.name.lower():
                    engine.setProperty('voice', voice.id)
                    break

            # Run in a thread so we can check stop_event
            done_event = threading.Event()

            def _run():
                try:
                    engine.say(text)
                    engine.runAndWait()
                    engine.stop()
                except Exception as e:
                    print(f"   ⚠️ pyttsx3 error: {e}")
                finally:
                    done_event.set()

            t = threading.Thread(target=_run, daemon=True)
            t.start()

            # Wait with stop checking
            waited = 0.0
            while not done_event.is_set() and waited < timeout:
                if self._stop_event.is_set():
                    # pyttsx3 doesn't support clean stop from another thread,
                    # but we can at least signal and move on
                    try:
                        engine.stop()
                    except Exception:
                        pass
                    return False
                done_event.wait(timeout=0.1)
                waited += 0.1

            return not self._stop_event.is_set()

        except Exception as e:
            print(f"   ⚠️ TTS error: {e}")
            return False
