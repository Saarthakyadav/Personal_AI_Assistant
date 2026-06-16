"""
Speech-to-Text using SpeechRecognition + PocketSphinx (no C++ compilation)
Or use Google's free API (needs internet)
"""

import speech_recognition as sr
import numpy as np
from typing import Optional

class SimpleSTT:
    """STT using SpeechRecognition - works without compilation"""
    
    def __init__(self, use_google=False):
        self.recognizer = sr.Recognizer()
        self.use_google = use_google
        
        print(f"✅ STT initialized (Google API: {use_google})")
    
    def transcribe(self, audio: np.ndarray, sample_rate=16000) -> Optional[str]:
        """Convert numpy audio to text"""
        if audio is None or len(audio) < 1000:
            return None
        
        # Convert numpy to AudioData
        audio_bytes = audio.astype(np.int16).tobytes()
        audio_data = sr.AudioData(audio_bytes, sample_rate, 2)  # 2 bytes per sample
        
        try:
            if self.use_google:
                # Google's free API (needs internet)
                text = self.recognizer.recognize_google(audio_data)
            else:
                # Offline: PocketSphinx (less accurate but works offline)
                text = self.recognizer.recognize_sphinx(audio_data)
            
            print(f"📝 STT: {text[:80]}")
            return text
            
        except sr.UnknownValueError:
            print("Could not understand audio")
            return None
        except sr.RequestError as e:
            print(f"STT service error: {e}")
            return None