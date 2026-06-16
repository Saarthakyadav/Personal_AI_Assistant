"""
Text-to-Speech using pyttsx3 - Works with Python 3.10.11
No binary issues, uses Windows built-in voices
"""

import numpy as np
import threading
import time
from typing import Optional

class TextToSpeech:
    """TTS using pyttsx3 - compatible with Python 3.10"""
    
    def __init__(self, engine="pyttsx3", voice_name=None, rate=180):
        self.engine_type = engine
        self.voice_name = voice_name
        self.rate = rate
        self.available = False
        self.engine = None
        
        try:
            import pyttsx3
            self.engine = pyttsx3.init()
            self.available = True
            
            # Configure voice
            self.engine.setProperty('rate', rate)
            
            # Try to set a nice voice
            voices = self.engine.getProperty('voices')
            if voices:
                # Try to find a good English voice
                for voice in voices:
                    voice_name_lower = voice.name.lower()
                    if 'zira' in voice_name_lower:  # Windows 10/11 female voice
                        self.engine.setProperty('voice', voice.id)
                        print(f"✅ Using voice: {voice.name}")
                        break
                    elif 'david' in voice_name_lower:  # Windows male voice
                        self.engine.setProperty('voice', voice.id)
                        print(f"✅ Using voice: {voice.name}")
                        break
                else:
                    # Use first available voice
                    self.engine.setProperty('voice', voices[0].id)
                    print(f"✅ Using voice: {voices[0].name}")
            
            print(f"✅ TTS initialized (pyttsx3)")
            print(f"   Rate: {rate} words/min")
            
        except Exception as e:
            print(f"⚠️ TTS not available: {e}")
            print("   Will print responses instead of speaking")
    
    def synthesize(self, text: str, output_file: Optional[str] = None) -> Optional[np.ndarray]:
        """Convert text to speech"""
        if not text or not self.available or not self.engine:
            print(f"🔊 [Would speak]: {text[:100]}...")
            return None
        
        print(f"🗣️ Speaking: {text[:100]}...")
        
        try:
            if output_file:
                # Save to file (pyttsx3 doesn't directly support saving)
                # We'll just speak and return None
                self.engine.say(text)
                self.engine.runAndWait()
                return None
            
            # Speak directly
            self.engine.say(text)
            self.engine.runAndWait()
            
            # Return empty array (no audio processing needed)
            return np.array([], dtype=np.int16)
            
        except Exception as e:
            print(f"❌ TTS error: {e}")
            return None
    
    def speak(self, text: str):
        """Simple speak method"""
        self.synthesize(text)
    
    def speak_async(self, text: str):
        """Speak without blocking"""
        if self.available:
            thread = threading.Thread(target=self.speak, args=(text,))
            thread.daemon = True
            thread.start()
    
    def stop(self):
        """Stop speaking"""
        if self.engine:
            self.engine.stop()


# Simple fallback that just prints
class PrintOnlyTTS:
    """Fallback TTS that just prints text"""
    def synthesize(self, text: str, *args, **kwargs):
        print(f"\n🤖 Assistant: {text}\n")
        return None
    
    def speak(self, text: str):
        print(f"\n🤖 Assistant: {text}\n")