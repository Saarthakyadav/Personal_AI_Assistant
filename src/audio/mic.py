import sounddevice as sd
import numpy as np
import webrtcvad
import queue
import threading
import time
from typing import Optional
from .wakeword import FreeWakeWordDetector, TextWakeWordDetector


class RingBuffer:
    """Simple ring buffer for audio pre-roll."""

    def __init__(self, maxlen: int):
        self.buffer = np.zeros(maxlen, dtype=np.int16)
        self.maxlen = maxlen
        self.pos = 0
        self.full = False

    def extend(self, samples: np.ndarray):
        for sample in samples:
            self.buffer[self.pos] = sample
            self.pos = (self.pos + 1) % self.maxlen
            if self.pos == 0:
                self.full = True

    def get_last_n(self, n: int) -> np.ndarray:
        if n > self.maxlen:
            n = self.maxlen
        if self.full:
            indices = np.arange(self.pos - n, self.pos) % self.maxlen
            return self.buffer[indices]
        else:
            return self.buffer[max(0, self.pos - n):self.pos]


class EnhancedMicrophone:
    """
    Enhanced microphone with free wake word detection (openWakeWord).
    No API keys, no paid services required.
    """

    def __init__(self,
                 sample_rate: int = 16000,
                 frame_duration_ms: int = 30,
                 silence_timeout: float = 1.5,
                 wake_words: list = None,
                 use_ml_wakeword: bool = True):

        self.sample_rate = sample_rate
        self.frame_duration_ms = frame_duration_ms
        self.frame_size = 1280  # openwakeword requires exactly 1280 samples
        self.ignore_wake_until = 0
        self.silence_timeout = silence_timeout

        self.audio_queue = queue.Queue()
        self.vad = webrtcvad.Vad(3)  # most aggressive — filters background noise

        self.use_ml_wakeword = use_ml_wakeword
        self.ml_detector = None
        self.text_detector = None
        self.wake_word_triggered = False

        # Thread-safe mute flag
        self.muted = False
        self._mute_lock = threading.Lock()

        if use_ml_wakeword:
            try:
                self.ml_detector = FreeWakeWordDetector(
                    wake_words=wake_words or ["alexa", "hey_jarvis"],
                    threshold=0.98
                )
                print("✅ ML wake word detector active (free, open-source)")
            except Exception as e:
                print(f"⚠️ ML wake word failed: {e}")
                print("   Falling back to text-based detection")
                self.use_ml_wakeword = False

        self.text_detector = TextWakeWordDetector(wake_words or ["alexa", "hey jarvis"])

        pre_roll_samples = int(1.5 * sample_rate)
        self.ring_buffer = RingBuffer(maxlen=pre_roll_samples)

        self.is_listening = False
        self.stream = None
        self.current_utterance = []
        self.silence_frames = 0
        self.max_silence_frames = 20
        self.is_capturing = False

    def start_listening(self):
        if self.is_listening:
            return

        self.is_listening = True
        self.wake_word_triggered = False
        self.is_capturing = False

        self.stream = sd.InputStream(
            samplerate=self.sample_rate,
            channels=1,
            dtype=np.int16,
            blocksize=self.frame_size,
            callback=self._audio_callback
        )
        self.stream.start()
        print("🎤 Microphone listening for wake word...")
        print(f"   Wake words: alexa, hey jarvis")

    def stop_listening(self):
        self.is_listening = False
        if self.stream:
            self.stream.stop()
            self.stream.close()
            self.stream = None
    
    def set_wakeword_cooldown(self, seconds=3):
        self.ignore_wake_until = time.time() + seconds

    def _audio_callback(self, indata, frames, time_info, status):
        if status:
            print(f"Audio callback warning: {status}")

        # Drop audio while muted (during TTS playback)
        with self._mute_lock:
            if self.muted:
                return

        audio_chunk = indata.flatten()
        self.ring_buffer.extend(audio_chunk)

        # Wake word detection — runs only when not already capturing
        if self.use_ml_wakeword and not self.wake_word_triggered and not self.is_capturing:

            remaining = self.ignore_wake_until - time.time()

            if remaining > 0:
                print(f"⏳ Cooldown active: {remaining:.1f}s")
                return
        # Ignore wake words for a few seconds after TTS
            if time.time() < self.ignore_wake_until:
                return

            detected_word = self.ml_detector.process_frame(audio_chunk)

            if detected_word:
                self.wake_word_triggered = True
                self.is_capturing = True

                # smaller pre-roll buffer
                pre_roll = self.ring_buffer.get_last_n(3200)

                self.current_utterance = list(pre_roll) if len(pre_roll) > 0 else []

                print(f"\n🟢 Wake word detected: '{detected_word}'")
                print("🎙️ Listening for command...")
                return

        # Command capture with VAD
        if self.is_capturing:
            self.current_utterance.extend(audio_chunk)

            try:
                # webrtcvad needs exact 30ms frames = 480 samples at 16kHz
                vad_frame_size = 480
                is_speech = False
                for i in range(0, len(audio_chunk), vad_frame_size):
                    vad_chunk = audio_chunk[i:i + vad_frame_size]
                    if len(vad_chunk) == vad_frame_size:
                        if self.vad.is_speech(vad_chunk.tobytes(), self.sample_rate):
                            is_speech = True
                            break
            except Exception:
                is_speech = True

            if not is_speech:
                self.silence_frames += 1
                if self.silence_frames >= self.max_silence_frames:
                    self.is_capturing = False

                    # prevent immediate retrigger
                    self.ignore_wake_until = time.time() + 5

                    self.wake_word_triggered = False
                    # Mute NOW to block re-triggering during transcription + LLM + TTS
                    with self._mute_lock:
                        self.muted = True
                    utterance = np.array(self.current_utterance, dtype=np.int16)
                    self.audio_queue.put(("utterance_ready", utterance))
                    self.current_utterance = []
                    self.silence_frames = 0
            else:
                self.silence_frames = 0

    def get_utterance(self, timeout: float = 5.0) -> Optional[np.ndarray]:
        try:
            msg, data = self.audio_queue.get(timeout=timeout)
            if msg == "utterance_ready":
                return data
        except queue.Empty:
            pass
        return None

    def capture_with_text_fallback(self, transcribed_text: str) -> Optional[str]:
        if self.text_detector.detect_in_text(transcribed_text):
            return self.text_detector.remove_wake_word(transcribed_text)
        return None

    def __del__(self):
        self.stop_listening()