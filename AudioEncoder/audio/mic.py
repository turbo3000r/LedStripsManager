"""Microphone audio capture provider using sounddevice."""

import time
from typing import Optional
import numpy as np

try:
    import sounddevice as sd
except ImportError:
    sd = None

from .base import AudioProvider


class MicrophoneProvider(AudioProvider):
    """Audio capture from microphone using sounddevice."""
    
    def __init__(self):
        super().__init__()
        self._stream: Optional[sd.InputStream] = None
        self._sample_rate = 44100
    
    def list_devices(self) -> list[tuple[int, str]]:
        """List all available input devices (no filtering)."""
        if sd is None:
            return []
        
        devices = []
        
        try:
            for i, dev in enumerate(sd.query_devices()):
                # Only inputs with at least 1 channel
                if dev["max_input_channels"] <= 0:
                    continue
                
                try:
                    sd.query_devices(i)  # verify accessible
                    devices.append((i, dev["name"]))
                except Exception:
                    continue
        except Exception:
            pass
        
        # Sort by name for easier selection
        devices.sort(key=lambda x: x[1].lower())
        
        # If nothing found, fallback to default input if available
        if not devices:
            try:
                default_in = sd.default.device[0]
                if default_in is not None:
                    info = sd.query_devices(default_in)
                    if info["max_input_channels"] > 0:
                        devices.append((default_in, info["name"]))
            except Exception:
                pass
        
        return devices
    
    def start(self, device_index: Optional[int] = None,
              sample_rate: int = 44100, chunk_size: int = 1024) -> bool:
        """Start capturing from microphone."""
        if sd is None:
            self._error = "sounddevice not installed"
            return False
        
        if self._running:
            return True
        
        self._sample_rate = sample_rate
        self._start_time = time.time()
        self._error = None
        
        try:
            def callback(indata, frames, time_info, status):
                if status:
                    self._error = str(status)
                # Convert to mono float32
                audio = indata[:, 0].astype(np.float32)
                timestamp = time.time() - self._start_time
                self._emit_frame(audio, self._sample_rate, timestamp)
            
            # Use numeric latency (0.1 seconds = 100ms) to prevent system audio interference
            # This allows the OS to buffer more audio, reducing conflicts with playback streams
            self._stream = sd.InputStream(
                device=device_index,
                channels=1,
                samplerate=sample_rate,
                blocksize=chunk_size,
                dtype=np.float32,
                latency=0.1,  # 100ms latency to minimize system audio interference
                callback=callback,
                extra_settings=None  # Use default (shared mode, not exclusive)
            )
            self._stream.start()
            self._running = True
            
            # Debug stream info
            try:
                print(f"[DEBUG] Mic: Stream started. Latency: {self._stream.latency}, Sample rate: {self._stream.samplerate}")
            except Exception:
                pass
                
            return True
            
        except Exception as e:
            self._error = str(e)
            return False
    
    def stop(self) -> None:
        """Stop capturing."""
        self._running = False
        if self._stream:
            try:
                self._stream.stop()
                self._stream.close()
            except Exception:
                pass
            self._stream = None
