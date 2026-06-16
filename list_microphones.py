# list_microphones.py
import pyaudio

p = pyaudio.PyAudio()

print("\n🎤 Available Audio Input Devices:\n")
for i in range(p.get_device_count()):
    dev = p.get_device_info_by_index(i)
    if dev['maxInputChannels'] > 0:
        print(f"Device {i}: {dev['name']}")
        print(f"   Input channels: {dev['maxInputChannels']}")
        print(f"   Default sample rate: {dev['defaultSampleRate']}")
        print()

p.terminate()