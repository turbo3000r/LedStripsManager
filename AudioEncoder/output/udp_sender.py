"""UDP sender with frame pacing for LED packets."""

import socket
import time
import threading
from typing import Optional, Callable
from dataclasses import dataclass
from collections import deque

from protocol.led_packets import (
    build_led_v1_packet, 
    build_led_v2_packet, 
    build_multi_stream_packet,
    StreamID
)


@dataclass
class SenderStats:
    """Statistics for the UDP sender."""
    packets_sent: int = 0
    bytes_sent: int = 0
    errors: int = 0
    actual_fps: float = 0.0
    last_send_time: float = 0.0


class UdpSender:
    """UDP sender with frame pacing for LED packets."""
    
    def __init__(self, host: str = "127.0.0.1", port: int = 5001):
        """
        Initialize UDP sender.
        
        Args:
            host: Server host address
            port: Server UDP repeater listen port
        """
        self._host = host
        self._port = port
        self._socket: Optional[socket.socket] = None
        
        self._running = False
        self._thread: Optional[threading.Thread] = None
        
        self._target_fps = 60
        self._frame_interval = 1.0 / 60
        
        # Frame callback
        self._frame_callback: Optional[Callable[[], Optional[bytes]]] = None
        
        # Stats
        self._stats = SenderStats()
        self._frame_times: deque = deque(maxlen=60)
        
        # Error handling
        self._last_error: Optional[str] = None
    
    @property
    def host(self) -> str:
        return self._host
    
    @host.setter
    def host(self, value: str) -> None:
        self._host = value
    
    @property
    def port(self) -> int:
        return self._port
    
    @port.setter
    def port(self, value: int) -> None:
        self._port = value
    
    @property
    def target_fps(self) -> int:
        return self._target_fps
    
    @target_fps.setter
    def target_fps(self, value: int) -> None:
        self._target_fps = max(1, min(120, value))
        self._frame_interval = 1.0 / self._target_fps
    
    @property
    def is_running(self) -> bool:
        return self._running
    
    @property
    def stats(self) -> SenderStats:
        return self._stats
    
    @property
    def last_error(self) -> Optional[str]:
        return self._last_error
    
    def set_frame_callback(self, callback: Callable[[], Optional[bytes]]) -> None:
        """
        Set callback that generates frame data.
        
        The callback should return bytes to send, or None to skip the frame.
        """
        self._frame_callback = callback
    
    def start(self) -> bool:
        """Start the sender loop. Returns True on success."""
        if self._running:
            return True
        
        try:
            self._socket = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            self._running = True
            self._stats = SenderStats()
            self._last_error = None
            
            self._thread = threading.Thread(target=self._send_loop, daemon=True)
            self._thread.start()
            return True
            
        except Exception as e:
            self._last_error = str(e)
            return False
    
    def stop(self) -> None:
        """Stop the sender loop."""
        self._running = False
        
        if self._thread:
            self._thread.join(timeout=2)
            self._thread = None
        
        if self._socket:
            try:
                self._socket.close()
            except Exception:
                pass
            self._socket = None
    
    def send_once(self, data: bytes) -> bool:
        """Send a single packet immediately (for testing)."""
        if self._socket is None:
            try:
                self._socket = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            except Exception as e:
                self._last_error = str(e)
                return False
        
        try:
            self._socket.sendto(data, (self._host, self._port))
            self._stats.packets_sent += 1
            self._stats.bytes_sent += len(data)
            return True
        except Exception as e:
            self._last_error = str(e)
            self._stats.errors += 1
            return False
    
    def _send_loop(self) -> None:
        """Main send loop with frame pacing."""
        next_frame_time = time.perf_counter()
        
        while self._running:
            now = time.perf_counter()
            
            # Wait for next frame time
            if now < next_frame_time:
                sleep_time = next_frame_time - now
                if sleep_time > 0.001:  # Only sleep if > 1ms
                    time.sleep(sleep_time * 0.9)  # Sleep slightly less to avoid overshooting
                continue
            
            # Schedule next frame
            next_frame_time += self._frame_interval
            
            # If we're behind, catch up
            if next_frame_time < now:
                next_frame_time = now + self._frame_interval
            
            # Get frame data from callback
            if self._frame_callback:
                try:
                    data = self._frame_callback()
                    if data:
                        self._send_packet(data)
                except Exception as e:
                    self._last_error = str(e)
                    self._stats.errors += 1
            
            # Update FPS stats
            self._frame_times.append(now)
            if len(self._frame_times) >= 2:
                duration = self._frame_times[-1] - self._frame_times[0]
                if duration > 0:
                    self._stats.actual_fps = (len(self._frame_times) - 1) / duration
    
    def _send_packet(self, data: bytes) -> None:
        """Send a packet to the server."""
        if self._socket is None:
            return
        
        try:
            self._socket.sendto(data, (self._host, self._port))
            self._stats.packets_sent += 1
            self._stats.bytes_sent += len(data)
            self._stats.last_send_time = time.time()
        except Exception as e:
            self._last_error = str(e)
            self._stats.errors += 1


class FrameBuilder:
    """Builds LED packets from mode output."""
    
    def __init__(self):
        self._send_4ch = True
        self._send_2ch = True
        self._send_rgb = False
        self._use_v2 = True
        
        # Current values (set by engine)
        self._values_4ch: list[int] = [0, 0, 0, 0]
        self._values_2ch: list[int] = [0, 0]
        self._values_rgb: list[int] = [0, 0, 0]
    
    @property
    def send_4ch(self) -> bool:
        return self._send_4ch
    
    @send_4ch.setter
    def send_4ch(self, value: bool) -> None:
        self._send_4ch = value
    
    @property
    def send_2ch(self) -> bool:
        return self._send_2ch
    
    @send_2ch.setter
    def send_2ch(self, value: bool) -> None:
        self._send_2ch = value
    
    @property
    def send_rgb(self) -> bool:
        return self._send_rgb
    
    @send_rgb.setter
    def send_rgb(self, value: bool) -> None:
        self._send_rgb = value
    
    @property
    def use_v2(self) -> bool:
        return self._use_v2
    
    @use_v2.setter
    def use_v2(self, value: bool) -> None:
        self._use_v2 = value
    
    def set_values(self, 
                   values_4ch: list[int],
                   values_2ch: list[int],
                   values_rgb: list[int]) -> None:
        """Update current values."""
        self._values_4ch = values_4ch
        self._values_2ch = values_2ch
        self._values_rgb = values_rgb
    
    def build_packet(self) -> Optional[bytes]:
        """Build a packet from current values based on settings."""
        # Count enabled streams
        enabled_streams = sum([self._send_4ch, self._send_2ch, self._send_rgb])
        
        if enabled_streams == 0:
            return None
        
        # Single stream: use v1 for compatibility
        if enabled_streams == 1 or not self._use_v2:
            if self._send_4ch:
                return build_led_v1_packet(self._values_4ch)
            elif self._send_2ch:
                return build_led_v1_packet(self._values_2ch)
            elif self._send_rgb:
                return build_led_v1_packet(self._values_rgb)
        
        # Multiple streams: use v2
        streams = {}
        if self._send_4ch:
            streams[StreamID.CH4_V1] = self._values_4ch
        if self._send_2ch:
            streams[StreamID.CH2_V1] = self._values_2ch
        if self._send_rgb:
            streams[StreamID.RGB_V1] = self._values_rgb
        
        return build_led_v2_packet(streams)
