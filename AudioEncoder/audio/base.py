"""Base classes for audio capture providers."""

from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Optional, Callable
import numpy as np
import threading


@dataclass
class AudioFrame:
    """A frame of audio data."""
    data: np.ndarray  # Audio samples (mono, float32, -1 to 1)
    sample_rate: int
    timestamp: float  # Time in seconds since start
    
    @property
    def duration(self) -> float:
        """Duration of this frame in seconds."""
        return len(self.data) / self.sample_rate


class AudioProvider(ABC):
    """Abstract base class for audio input providers."""
    
    def __init__(self):
        self._running = False
        self._callback: Optional[Callable[[AudioFrame], None]] = None
        self._thread: Optional[threading.Thread] = None
        self._start_time: float = 0
        self._error: Optional[str] = None
    
    @property
    def is_running(self) -> bool:
        return self._running
    
    @property
    def last_error(self) -> Optional[str]:
        return self._error
    
    def set_callback(self, callback: Callable[[AudioFrame], None]) -> None:
        """Set the callback to receive audio frames."""
        self._callback = callback
    
    @abstractmethod
    def list_devices(self) -> list[tuple[int, str]]:
        """List available audio devices as (index, name) tuples."""
        pass
    
    @abstractmethod
    def start(self, device_index: Optional[int] = None, 
              sample_rate: int = 44100, chunk_size: int = 1024) -> bool:
        """Start capturing audio. Returns True on success."""
        pass
    
    @abstractmethod
    def stop(self) -> None:
        """Stop capturing audio."""
        pass
    
    def _emit_frame(self, data: np.ndarray, sample_rate: int, timestamp: float) -> None:
        """Emit an audio frame to the callback."""
        if self._callback:
            frame = AudioFrame(data=data, sample_rate=sample_rate, timestamp=timestamp)
            self._callback(frame)
        else:
            # Debug: check if callback is set
            if not hasattr(self, '_callback_warned'):
                print(f"[DEBUG] AudioProvider: No callback set for frame emission (type: {type(self).__name__})")
                self._callback_warned = True


class RingBuffer:
    """Thread-safe ring buffer for audio samples."""
    
    def __init__(self, capacity: int = 44100):
        """Create a ring buffer with given capacity in samples."""
        self._buffer = np.zeros(capacity, dtype=np.float32)
        self._capacity = capacity
        self._write_pos = 0
        self._available = 0
        self._lock = threading.Lock()
    
    def write(self, data: np.ndarray) -> None:
        """Write samples to the buffer."""
        with self._lock:
            n = len(data)
            if n >= self._capacity:
                # Data larger than buffer, keep only the last part
                self._buffer[:] = data[-self._capacity:]
                self._write_pos = 0
                self._available = self._capacity
            else:
                # Write with wrap-around
                end_pos = self._write_pos + n
                if end_pos <= self._capacity:
                    self._buffer[self._write_pos:end_pos] = data
                else:
                    first_part = self._capacity - self._write_pos
                    self._buffer[self._write_pos:] = data[:first_part]
                    self._buffer[:n - first_part] = data[first_part:]
                self._write_pos = end_pos % self._capacity
                self._available = min(self._available + n, self._capacity)
    
    def read(self, n: int) -> np.ndarray:
        """Read up to n samples from the buffer (most recent)."""
        with self._lock:
            n = min(n, self._available)
            if n == 0:
                return np.array([], dtype=np.float32)
            
            read_start = (self._write_pos - n) % self._capacity
            if read_start + n <= self._capacity:
                return self._buffer[read_start:read_start + n].copy()
            else:
                first_part = self._capacity - read_start
                return np.concatenate([
                    self._buffer[read_start:],
                    self._buffer[:n - first_part]
                ])
    
    def clear(self) -> None:
        """Clear the buffer."""
        with self._lock:
            self._write_pos = 0
            self._available = 0
