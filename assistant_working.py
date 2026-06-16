"""
Debug script - tests openwakeword directly on mic.
Run this and say "Alexa" to see raw scores.
"""

import numpy as np
import sounddevice as sd
from openwakeword.model import Model

SAMPLE_RATE = 16000
FRAME_SIZE = 1280  # 80ms at 16kHz

print("Loading model...")
model = Model(wakeword_models=["alexa", "hey_jarvis"], inference_framework="onnx")
print("Model loaded. Say 'Alexa' or 'Hey Jarvis'...\n")

buffer = np.zeros(0, dtype=np.int16)

def callback(indata, frames, time_info, status):
    global buffer
    chunk = indata.flatten().astype(np.int16)
    buffer = np.concatenate([buffer, chunk])

    # Process in 1280-sample frames
    while len(buffer) >= FRAME_SIZE:
        frame = buffer[:FRAME_SIZE]
        buffer = buffer[FRAME_SIZE:]

        prediction = model.predict(frame)
        # Print any non-zero scores
        scores = {k: round(v, 4) for k, v in prediction.items() if v > 0.01}
        if scores:
            print(f"Scores: {scores}")

with sd.InputStream(
    samplerate=SAMPLE_RATE,
    channels=1,
    dtype=np.int16,
    blocksize=FRAME_SIZE,
    callback=callback
):
    print("Listening... (Ctrl+C to stop)")
    try:
        while True:
            import time
            time.sleep(0.1)
    except KeyboardInterrupt:
        print("\nDone.")