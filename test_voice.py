import speech_recognition as sr
import time

print("Testing microphone...")
r = sr.Recognizer()

try:
    with sr.Microphone() as source:
        print("1. Microphone opened")
        print("2. Adjusting for ambient noise (2 seconds)...")
        r.adjust_for_ambient_noise(source, duration=2)
        print("3. Calibration done!")
        print("4. Say something now...")
        
        audio = r.listen(source, timeout=5, phrase_time_limit=5)
        print("5. Audio captured!")
        
        text = r.recognize_google(audio)
        print(f"You said: {text}")
        
except sr.WaitTimeoutError:
    print("Timeout - No speech detected")
except Exception as e:
    print(f"Error: {e}")