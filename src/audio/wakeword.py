"""
Free, open-source wake word detection using openWakeWord.
No API keys, no paid services, 100% local.
"""

import numpy as np
import os
import sys
from pathlib import Path
from typing import Optional, List, Callable

try:
    import openwakeword
    from openwakeword.model import Model
    OPENWAKEWORD_AVAILABLE = True
except ImportError:
    OPENWAKEWORD_AVAILABLE = False
    print("⚠️ openwakeword not installed. Run: pip install openwakeword")


class FreeWakeWordDetector:
    """
    Free wake word detection using openWakeWord.
    Pre-trained models: alexa, hey_jarvis, hey_mycroft, hey_rhasspy
    """

    def __init__(self,
                 wake_words: List[str] = None,
                 model_path: str = None,
                 threshold: float = 0.1):   # lowered from 0.5

        if not OPENWAKEWORD_AVAILABLE:
            raise ImportError("openwakeword not installed. Run: pip install openwakeword")

        if wake_words is None:
            wake_words = ["alexa", "hey_jarvis"]

        self.wake_words = wake_words
        self.threshold = threshold
        self.model = None
        self.sample_rate = 16000

        # Build model name list (underscore format for openwakeword)
        self.model_names = [ww.lower().replace(" ", "_") for ww in wake_words]

        self._ensure_models_downloaded()

        try:
            self.model = Model(
                wakeword_models=self.model_names,
                inference_framework="onnx"
            )
            print(f"✅ Free wake word detector initialized")
            print(f"   Wake words: {wake_words}")
            print(f"   Threshold: {threshold}")
        except Exception as e:
            print(f"❌ Failed to initialize wake word model: {e}")
            raise

    def _ensure_models_downloaded(self):
        model_dir = Path.home() / ".cache" / "openwakeword"
        if not model_dir.exists():
            print("📥 Downloading openWakeWord models (first time only)...")
            try:
                openwakeword.utils.download_models()
                print("✅ Models downloaded successfully")
            except Exception as e:
                print(f"⚠️ Auto-download failed: {e}")

    def process_frame(self, audio_frame: np.ndarray) -> Optional[str]:
        """
        Process a single audio frame.
        Returns wake word string if detected, None otherwise.
        """
        if self.model is None:
            return None

        # openwakeword expects int16
        if audio_frame.dtype != np.int16:
            audio_frame = (audio_frame * 32768).astype(np.int16)

        frame_size = 1280  # 80ms at 16kHz
        for i in range(0, len(audio_frame), frame_size):
            chunk = audio_frame[i:i + frame_size]
            if len(chunk) < frame_size:
                continue  # skip incomplete final chunk

            prediction = self.model.predict(chunk)

            # FIX: iterate over actual prediction keys (e.g. "hey_jarvis_v0.1")
            # instead of trying to match our model name list exactly
            for key, score in prediction.items():
                if score > self.threshold:
                    print(f"   🔑 '{key}' score: {score:.3f}")
                    return key  # return whatever fired

        return None

    def process_audio_chunk(self, audio_chunk: np.ndarray) -> Optional[str]:
        return self.process_frame(audio_chunk)


class SimpleFrequencyDetector:
    """Ultra-simple energy-based detector. No ML, no wake word specificity."""

    def __init__(self, wake_word: str = "assistant"):
        self.wake_word = wake_word
        self.energy_threshold = 0.01

    def process_frame(self, audio_frame: np.ndarray, sample_rate: int = 16000) -> bool:
        if len(audio_frame) == 0:
            return False
        audio_float = audio_frame.astype(np.float32) / 32768.0
        energy = np.sqrt(np.mean(audio_float ** 2))
        return energy > self.energy_threshold


class TextWakeWordDetector:
    """Text-based wake word detection as fallback."""

    def __init__(self, wake_words: List[str]):
        self.wake_words = [ww.lower() for ww in wake_words]

    def detect_in_text(self, text: str) -> bool:
        text_lower = text.lower()
        return any(ww in text_lower for ww in self.wake_words)

    def remove_wake_word(self, text: str) -> str:
        text_lower = text.lower()
        for ww in self.wake_words:
            if ww in text_lower:
                text = text_lower.replace(ww, "").strip()
                if text:
                    text = text[0].upper() + text[1:]
                return text
        return text