"""
Speech-to-Text using faster-whisper - Works with Python 3.10.11
"""

import numpy as np
from typing import Optional
import time
import os

class WhisperSTT:
    """STT using faster-whisper"""
    
    def __init__(self, model="base", device="cpu", compute_type="int8"):
        self.model_name = model
        self.device = device
        self.compute_type = compute_type
        self.model = None
        self.available = False
        
        try:
            print(f"🔄 Loading Whisper model '{model}'...")
            from faster_whisper import WhisperModel
            
            self.model = WhisperModel(
                model, 
                device=device, 
                compute_type=compute_type,
                cpu_threads=4,
                num_workers=1
            )
            self.available = True
            print(f"✅ Faster-Whisper model loaded")
            print(f"   Model: {model}")
            print(f"   Device: {device}")
            
        except Exception as e:
            print(f"⚠️ Could not load faster-whisper: {e}")
            print("   Will use text input mode instead")
    
    def transcribe(self, audio: np.ndarray, sample_rate: int = 16000) -> Optional[str]:
        """Transcribe audio to text"""
        if not self.available or self.model is None:
            return None
        
        if audio is None or len(audio) < 1000:  # Too short
            return None
        
        try:
            start_time = time.time()
            
            # Convert to float32 if needed
            if audio.dtype == np.int16:
                audio_float = audio.astype(np.float32) / 32768.0
            else:
                audio_float = audio.astype(np.float32)
            
            # Transcribe
            segments, info = self.model.transcribe(
                audio_float, 
                beam_size=3, 
                language="en",
                vad_filter=True  # Filter out silence
            )
            
            text = " ".join([seg.text for seg in segments])
            
            elapsed = time.time() - start_time
            if text:
                print(f"📝 STT: {text[:80]}... ({elapsed:.2f}s)")
                return text.strip()
            else:
                return None
                
        except Exception as e:
            print(f"❌ STT error: {e}")
            return None