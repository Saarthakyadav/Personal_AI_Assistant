#!/usr/bin/env python3
"""
Test wake word detection (free version)
"""

import time
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

def test_wakeword():
    """Test free wake word detection"""
    
    print("=" * 50)
    print("Testing Free Wake Word Detection")
    print("=" * 50)
    print("\nSay one of these wake words:")
    print("  • computer")
    print("  • alexa")
    print("  • hey jarvis")
    print("\nPress Ctrl+C to stop\n")
    
    from src.audio.wakeword import FreeWakeWordDetector
    
    # Initialize detector
    detector = FreeWakeWordDetector(
        wake_words=["computer", "alexa", "hey jarvis"],
        threshold=0.4
    )
    
    # Test with microphone
    import sounddevice as sd
    import numpy as np
    
    sample_rate = 16000
    frame_size = 1280
    
    def callback(indata, frames, time, status):
        audio = indata.flatten()
        detected = detector.process_frame(audio)
        if detected:
            print(f"\n🔊 DETECTED: '{detected}'")
    
    stream = sd.InputStream(
        samplerate=sample_rate,
        channels=1,
        dtype=np.int16,
        blocksize=frame_size,
        callback=callback
    )
    
    stream.start()
    print("🎤 Listening...")
    
    try:
        while True:
            time.sleep(0.1)
    except KeyboardInterrupt:
        print("\n\nTest complete")
        stream.stop()
        stream.close()

def test_text_fallback():
    """Test text-based fallback detection"""
    from src.audio.wakeword import TextWakeWordDetector
    
    detector = TextWakeWordDetector(["computer", "alexa", "hey jarvis"])
    
    test_phrases = [
        "computer what time is it",
        "hey jarvis set a reminder",
        "alexa play music",
        "just a normal question"
    ]
    
    print("\nTesting text-based detection:")
    for phrase in test_phrases:
        detected = detector.detect_in_text(phrase)
        cleaned = detector.remove_wake_word(phrase) if detected else phrase
        print(f"  '{phrase}' -> detected: {detected}, cleaned: '{cleaned}'")

if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--text", action="store_true", help="Test text-based detection only")
    args = parser.parse_args()
    
    if args.text:
        test_text_fallback()
    else:
        test_wakeword()