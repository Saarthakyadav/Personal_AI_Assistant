import sounddevice as sd
import numpy as np
from typing import Optional

class SpeakerOutput:
    """Play audio through speakers"""
    
    def __init__(self, sample_rate=16000):
        self.sample_rate = sample_rate
    
    def play(self, audio: np.ndarray, sample_rate: Optional[int] = None):
        """Play audio array"""
        if audio is None or len(audio) == 0:
            return
        
        sr = sample_rate or self.sample_rate
        
        # Normalize to float32 if needed
        if audio.dtype == np.int16:
            audio_float = audio.astype(np.float32) / 32768.0
        else:
            audio_float = audio
        
        sd.play(audio_float, sr)
        sd.wait()  # Wait for playback to finish