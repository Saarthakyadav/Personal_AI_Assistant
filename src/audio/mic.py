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
        self.vad_frame_size = int(self.sample_rate * self.frame_duration_ms / 1000)
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

        # FIX #6: track cooldown print so we don't spam the console
        self._cooldown_printed = False

        if use_ml_wakeword:
            try:
                self.ml_detector = FreeWakeWordDetector(
                    wake_words=wake_words or ["alexa", "hey_jarvis"],
                    threshold=0.60  # FIX #3: balanced threshold (was 0.98 vs 0.1 mismatch)
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
        self._vad_carryover = np.empty((0,), dtype=np.int16)
        self.silence_frames = 0         # FIX #5: reset properly in start_listening
        self.max_silence_frames = int(self.silence_timeout * 1000 / self.frame_duration_ms)
        self.is_capturing = False

    def start_listening(self):
        if self.is_listening:
            return

        self.is_listening = True
        self.wake_word_triggered = False
        self.is_capturing = False
        self.silence_frames = 0          # FIX #5: always reset on fresh start
        self._cooldown_printed = False

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
        self._cooldown_printed = False   # FIX #6: allow one print per new cooldown
        # Flush openWakeWord's internal buffer so stale audio from before
        # the cooldown can't fire the moment the cooldown expires
        if self.ml_detector is not None:
            self.ml_detector.reset_states()

    def _audio_callback(self, indata, frames, time_info, status):
        if status:
            print(f"Audio callback warning: {status}")

        # Drop audio while muted (during TTS playback)
        with self._mute_lock:
            if self.muted:
                return
            # First frame after unmute — discard this frame entirely so the
            # model doesn't score audio that was buffered during the muted period.
            # reset_states() was already called by set_wakeword_cooldown().
            if getattr(self, '_just_unmuted', False):
                self._just_unmuted = False
                return  # skip this one frame, model is already clean

        audio_chunk = indata.flatten()
        self.ring_buffer.extend(audio_chunk)

        # Wake word detection — runs only when not already capturing
        if self.use_ml_wakeword and not self.wake_word_triggered and not self.is_capturing:

            remaining = self.ignore_wake_until - time.time()

            # FIX #1: single cooldown check — removed the dead duplicate block
            if remaining > 0:
                # FIX #6: print only once per cooldown, not every 30ms
                if not self._cooldown_printed:
                    print(f"⏳ Cooldown active ({remaining:.1f}s remaining)...")
                    self._cooldown_printed = True
                return

            self._cooldown_printed = False  # reset for next cooldown

            detected_word = self.ml_detector.process_frame(audio_chunk)

            if detected_word:
                self.wake_word_triggered = True
                self.is_capturing = True
                self.silence_frames = 0  # FIX #5: reset silence counter on new capture
                self._vad_carryover = np.empty((0,), dtype=np.int16)

                    # FIX #7: larger pre-roll (0.5s = 8000 samples) to avoid clipping command start
                pre_roll = self.ring_buffer.get_last_n(8000)
                self.current_utterance = list(pre_roll) if len(pre_roll) > 0 else []

                print(f"\n🟢 Wake word detected: '{detected_word}'")
                print("🎙️ Listening for command...")
                return

        # Command capture with VAD
        if self.is_capturing:
            self.current_utterance.extend(audio_chunk)

            try:
                vad_audio = np.concatenate((self._vad_carryover, audio_chunk)) if self._vad_carryover.size else audio_chunk
                self._vad_carryover = np.empty((0,), dtype=np.int16)

                speech_frames = 0
                trailing_silence_frames = 0
                is_speech = False

                for i in range(0, len(vad_audio), self.vad_frame_size):
                    vad_chunk = vad_audio[i:i + self.vad_frame_size]
                    if len(vad_chunk) < self.vad_frame_size:
                        self._vad_carryover = vad_chunk
                        break

                    frame_speech = self.vad.is_speech(vad_chunk.tobytes(), self.sample_rate)
                    if frame_speech:
                        speech_frames += 1
                        trailing_silence_frames = 0
                    else:
                        trailing_silence_frames += 1

                is_speech = speech_frames > 0
                if is_speech:
                    self.silence_frames = trailing_silence_frames
                else:
                    self.silence_frames += trailing_silence_frames

            except Exception:
                is_speech = True

            if not is_speech:

                    # Prevent immediate retrigger during processing
                    self.ignore_wake_until = time.time() + 5
                    self._cooldown_printed = False

                    # Mute NOW to block re-triggering during transcription + LLM + TTS
                    with self._mute_lock:
                        self.muted = True

                    utterance = np.array(self.current_utterance, dtype=np.int16)
                    self.audio_queue.put(("utterance_ready", utterance))
                    self.current_utterance = []
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