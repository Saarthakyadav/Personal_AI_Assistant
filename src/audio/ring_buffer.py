import numpy as np
from collections import deque
from typing import Optional

class RingBuffer:
    """
    Circular buffer to store recent audio.
    Preserves audio before wake word detection.
    """
    
    def __init__(self, capacity: int):
        """
        Args:
            capacity: Maximum number of samples to store
        """
        self.capacity = capacity
        self.buffer = deque(maxlen=capacity)
        self.total_samples = 0
    
    def extend(self, samples: np.ndarray):
        """Add samples to the buffer"""
        for sample in samples:
            self.buffer.append(sample)
        self.total_samples += len(samples)
    
    def get_last_n(self, n_samples: int) -> Optional[np.ndarray]:
        """
        Get the last N samples (most recent)
        Returns None if not enough samples
        """
        if len(self.buffer) < n_samples:
            return None
        
        # Get last N samples from deque
        samples = list(self.buffer)[-n_samples:]
        return np.array(samples, dtype=np.int16)
    
    def get_all(self) -> np.ndarray:
        """Get all samples in buffer"""
        return np.array(list(self.buffer), dtype=np.int16)
    
    def clear(self):
        """Clear the buffer"""
        self.buffer.clear()
    
    def __len__(self):
        return len(self.buffer)


class AudioCaptureBuffer:
    """
    Manages audio capture with pre and post wake word buffering
    """
    
    def __init__(self, sample_rate: int = 16000, pre_roll_seconds: float = 1.0):
        self.sample_rate = sample_rate
        self.pre_roll_samples = int(pre_roll_seconds * sample_rate)
        
        # Ring buffer for continuous audio
        self.ring_buffer = RingBuffer(capacity=self.pre_roll_samples * 2)
        
        # Current utterance buffer
        self.utterance_buffer = []
        
        # State tracking
        self.is_capturing = False
        self.post_silence_frames = 0
        self.max_silence_frames = int(1.5 * sample_rate / 512)  # ~1.5 seconds at 512 frame size
        
    def add_audio_chunk(self, chunk: np.ndarray, is_speech: bool = None):
        """
        Add audio chunk to buffer.
        
        Args:
            chunk: Audio samples (int16)
            is_speech: Voice activity detection flag (optional)
        """
        # Always add to ring buffer
        self.ring_buffer.extend(chunk)
        
        if self.is_capturing:
            # Currently capturing an utterance
            self.utterance_buffer.extend(chunk)
            
            # Check for silence to stop capture
            if is_speech is False:  # Silence detected
                self.post_silence_frames += 1
                if self.post_silence_frames >= self.max_silence_frames:
                    # End of utterance
                    self.is_capturing = False
            else:
                self.post_silence_frames = 0
    
    def start_capture(self):
        """Start capturing a new utterance"""
        self.is_capturing = True
        self.post_silence_frames = 0
        
        # Get pre-roll audio from ring buffer
        pre_roll = self.ring_buffer.get_last_n(self.pre_roll_samples)
        
        # Initialize utterance buffer with pre-roll audio
        if pre_roll is not None:
            self.utterance_buffer = list(pre_roll)
        else:
            self.utterance_buffer = []
    
    def stop_capture(self) -> np.ndarray:
        """Stop capture and return full utterance"""
        self.is_capturing = False
        audio = np.array(self.utterance_buffer, dtype=np.int16)
        self.utterance_buffer = []
        return audio
    
    def is_silence_timeout(self) -> bool:
        """Check if silence timeout has been reached"""
        return not self.is_capturing and self.post_silence_frames >= self.max_silence_frames