"""
Simple Voice Activity Detection without C++ dependencies
Uses energy threshold and zero-crossing rate
"""

import numpy as np

class SimpleVAD:
    """Pure Python VAD - no compilation needed"""
    
    def __init__(self, energy_threshold=0.01, silence_frames=20):
        self.energy_threshold = energy_threshold
        self.silence_frames = silence_frames
        self.speech_frames = 0
        self.silence_count = 0
    
    def is_speech(self, audio_chunk: np.ndarray) -> bool:
        """Detect if audio chunk contains speech"""
        if len(audio_chunk) == 0:
            return False
        
        # Convert to float if int16
        if audio_chunk.dtype == np.int16:
            audio_float = audio_chunk.astype(np.float32) / 32768.0
        else:
            audio_float = audio_chunk
        
        # Calculate RMS energy
        energy = np.sqrt(np.mean(audio_float**2))
        
        # Simple energy threshold
        return energy > self.energy_threshold