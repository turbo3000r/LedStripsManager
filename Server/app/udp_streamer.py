"""UDP streamer for low-latency fast mode updates."""

import logging
import socket
import struct
import threading
import time
from typing import Optional

from app.config import AppConfig
from app.state import SharedState, DeviceMode

logger = logging.getLogger(__name__)


# Packet format constants
PACKET_HEADER = b"LED"  # 3 bytes header
PACKET_VERSION = 1  # Protocol version


class UdpStreamer:
    """
    UDP streamer for fast mode (music-reactive lighting).
    
    Sends low-latency UDP packets to ESP devices in fast mode.
    
    Packet Format (simple mode):
        Header:     3 bytes  "LED"
        Version:    1 byte   Protocol version (1)
        Channels:   1 byte   Number of channels
        Values:     N bytes  One byte per channel (0-255)
    
    Total: 5 + N bytes per packet
    """

    def __init__(self, config: AppConfig, state: SharedState):
        self._config = config
        self._state = state
        self._running = False
        self._thread: Optional[threading.Thread] = None
        self._socket: Optional[socket.socket] = None

    def start(self) -> None:
        """Start the UDP streamer in a background thread."""
        if self._running:
            return

        # Create UDP socket
        self._socket = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self._socket.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)

        self._running = True
        self._thread = threading.Thread(target=self._run_loop, daemon=True)
        self._thread.start()

    def stop(self) -> None:
        """Stop the UDP streamer."""
        self._running = False
        if self._socket:
            try:
                self._socket.close()
            except Exception:
                pass
        if self._thread:
            self._thread.join(timeout=5)

    def _run_loop(self) -> None:
        """Main streamer loop - runs at configured rate."""
        send_rate = self._config.udp.send_rate_hz
        interval = 1.0 / send_rate if send_rate > 0 else 0.016  # Default ~60Hz
        logger.info(f"UDP streamer started at {send_rate}Hz (interval: {interval*1000:.1f}ms)")

        while self._running:
            loop_start = time.time()

            try:
                self._send_fast_updates()
            except Exception as e:
                logger.error(f"UDP streamer error: {e}")

            # Sleep for the remainder of the interval
            elapsed = time.time() - loop_start
            sleep_time = max(0, interval - elapsed)
            if sleep_time > 0:
                time.sleep(sleep_time)

    def _send_fast_updates(self) -> None:
        """Send UDP packets to all devices in fast mode."""
        # Get devices in fast mode
        fast_device_ids = self._state.get_devices_by_mode(DeviceMode.FAST)

        if not fast_device_ids:
            return

        for device_id in fast_device_ids:
            try:
                self._send_to_device(device_id)
            except Exception as e:
                logger.debug(f"Failed to send UDP to {device_id}: {e}")
                self._state.increment_device_error(device_id)

    def _send_to_device(self, device_id: str) -> None:
        """Send a UDP packet to a single device."""
        device_config = self._config.get_device_by_id(device_id)
        if not device_config:
            return

        # Get current fast values
        values = self._state.get_fast_values(device_id)
        if not values:
            values = [0] * device_config.channels

        # Build packet
        packet = self._build_packet(values)

        # Send to device
        if self._socket:
            try:
                self._socket.sendto(packet, (device_config.ip, device_config.udp_port))
            except socket.error as e:
                logger.debug(f"Socket error sending to {device_config.ip}:{device_config.udp_port}: {e}")
                raise

    def _build_packet(self, values: list[int]) -> bytes:
        """
        Build a UDP packet with brightness values.
        
        Format:
            Header:     3 bytes  "LED"
            Version:    1 byte   Protocol version
            Channels:   1 byte   Number of channels
            Values:     N bytes  One byte per channel
        """
        num_channels = len(values)
        
        # Clamp values to 0-255
        clamped = [max(0, min(255, v)) for v in values]

        # Pack the data
        # Header (3 bytes) + Version (1 byte) + Channel count (1 byte) + Values (N bytes)
        packet = bytearray(PACKET_HEADER)
        packet.append(PACKET_VERSION)
        packet.append(num_channels)
        packet.extend(clamped)

        return bytes(packet)

    def build_ddp_packet(
        self,
        values: list[int],
        offset: int = 0,
        push: bool = True
    ) -> bytes:
        """
        Build a DDP (Distributed Display Protocol) packet.
        
        DDP is a common protocol for LED controllers.
        
        Format (simplified):
            Flags:      1 byte   (0x41 = push, 0x01 = no push)
            Sequence:   1 byte   Packet sequence number
            DataType:   1 byte   Data type (0x01 = RGB)
            DestID:     1 byte   Destination ID (0x01 default)
            Offset:     4 bytes  Data offset (big-endian)
            Length:     2 bytes  Data length (big-endian)
            Data:       N bytes  RGB values
        
        Args:
            values: List of brightness values (RGB interleaved)
            offset: Data offset in the buffer
            push: Whether this is the last packet (display now)
            
        Returns:
            DDP packet bytes
        """
        flags = 0x41 if push else 0x01  # Push flag + version 1
        sequence = 0  # Could implement sequence numbering
        data_type = 0x01  # RGB data
        dest_id = 0x01  # Default device

        data_bytes = bytes([max(0, min(255, v)) for v in values])
        data_len = len(data_bytes)

        # Build header
        packet = bytearray()
        packet.append(flags)
        packet.append(sequence)
        packet.append(data_type)
        packet.append(dest_id)
        packet.extend(struct.pack(">I", offset))  # 4 bytes, big-endian
        packet.extend(struct.pack(">H", data_len))  # 2 bytes, big-endian
        packet.extend(data_bytes)

        return bytes(packet)

    def send_immediate(self, device_id: str, values: list[int]) -> bool:
        """
        Send an immediate UDP update to a device.
        
        This bypasses the normal loop and sends immediately.
        Useful for responsive UI updates.
        
        Args:
            device_id: Target device ID
            values: Brightness values per channel
            
        Returns:
            True if sent successfully
        """
        device_config = self._config.get_device_by_id(device_id)
        if not device_config:
            return False

        packet = self._build_packet(values)

        if self._socket:
            try:
                self._socket.sendto(packet, (device_config.ip, device_config.udp_port))
                return True
            except socket.error as e:
                logger.debug(f"Immediate send failed to {device_id}: {e}")
                return False
        return False


class UdpBroadcaster:
    """
    Helper for broadcasting UDP packets to multiple devices.
    
    Can be used for synchronized effects across all devices.
    """

    def __init__(self, config: AppConfig):
        self._config = config
        self._socket: Optional[socket.socket] = None

    def __enter__(self):
        self._socket = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self._socket.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        if self._socket:
            self._socket.close()
        return False

    def broadcast_to_all(self, values: list[int]) -> int:
        """
        Broadcast the same values to all devices.
        
        Args:
            values: Brightness values per channel
            
        Returns:
            Number of devices successfully sent to
        """
        if not self._socket:
            return 0

        packet = self._build_simple_packet(values)
        success_count = 0

        for device in self._config.get_all_devices():
            try:
                self._socket.sendto(packet, (device.ip, device.udp_port))
                success_count += 1
            except socket.error:
                pass

        return success_count

    def _build_simple_packet(self, values: list[int]) -> bytes:
        """Build a simple UDP packet."""
        packet = bytearray(PACKET_HEADER)
        packet.append(PACKET_VERSION)
        packet.append(len(values))
        packet.extend([max(0, min(255, v)) for v in values])
        return bytes(packet)

