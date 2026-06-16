# quick_test.py
import speech_recognition as sr

MIC_INDEX = 14

print("Speak into your headset NOW (you have 4 seconds)...")

r = sr.Recognizer()
with sr.Microphone(device_index=MIC_INDEX) as source:
    try:
        audio = r.listen(source, timeout=4, phrase_time_limit=4)
        text = r.recognize_google(audio)
        print(f"\n✅ You said: {text}")
    except sr.WaitTimeoutError:
        print("No speech detected")
    except Exception as e:
        print(f"Error: {e}")