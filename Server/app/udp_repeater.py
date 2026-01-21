"""UDP repeater for forwarding external frames to ESP devices.

Receives UDP packets from external sources (e.g., audio analyzers, light shows)
and forwards them to devices/rooms configured for udp_repeater fast mode.

Supports both LED v1 (single stream) and LED v2 (multi-stream) protocols.
"""

import logging
import socket
import struct
import threading
from enum import IntEnum
from typing import Optional

from app.config import AppConfig
from app.state import SharedState, DeviceMode, FastModeType

logger = logging.getLogger(__name__)

# LED packet format constants
PACKET_HEADER = b"LED"
PACKET_VERSION_1 = 1
PACKET_VERSION_2 = 2

# For backward compatibility
PACKET_VERSION = PACKET_VERSION_1


class StreamID(IntEnum):
    """Stream identifiers for LED v2 protocol."""
    CH4_V1 = 1   # 4ch_v1: Green, Yellow, Blue, Red
    CH2_V1 = 2   # 2ch_v1: Red+Yellow, Green+Blue
    RGB_V1 = 3   # rgb_v1: Red, Green, Blue


# Mapping from hw_mode string to StreamID
HW_MODE_TO_STREAM_ID = {
    "4ch_v1": StreamID.CH4_V1,
    "2ch_v1": StreamID.CH2_V1,
    "rgb_v1": StreamID.RGB_V1,
}


class UdpRepeater:
    """
    UDP repeater that receives external LED control packets and forwards
    them to ESP devices configured for udp_repeater fast mode.
    
    Supports two protocol versions:
    
    LED v1 (Single Stream):
        Header:     3 bytes  "LED"
        Version:    1 byte   Protocol version (1)
        Channels:   1 byte   Number of channels (N)
        Values:     N bytes  One byte per channel (0-255)
    
    LED v2 (Multi-Stream):
        Header:      3 bytes   "LED"
        Version:     1 byte    Protocol version (2)
        StreamCount: 1 byte    Number of streams (S)
        Streams:     variable  S stream blocks
        
        Stream Block:
            StreamID:  1 byte   Hardware mode identifier (1=4ch_v1, 2=2ch_v1, 3=rgb_v1)
            Channels:  1 byte   Number of channels (N)
            Values:    N bytes  Brightness values (0-255)
    
    The repeater:
    1. Listens on a configurable UDP port for incoming packets
    2. Validates the packet format (v1 or v2)
    3. Forwards to all devices in FAST mode with fast_mode_type=udp_repeater
    4. For v2: selects best matching stream per device hw_mode
    5. Adapts channel count for each target device (e.g., 4ch->2ch mapping)
    """

    def __init__(self, config: AppConfig, state: SharedState):
        self._config = config
        self._state = state
        self._running = False
        self._thread: Optional[threading.Thread] = None
        self._socket: Optional[socket.socket] = None
        self._send_socket: Optional[socket.socket] = None
        
        # Cache for last received v2 streams (for devices to pick from)
        self._last_streams: dict[StreamID, list[int]] = {}

    def start(self) -> None:
        """Start the UDP repeater in a background thread."""
        if not self._config.udp_repeater.enabled:
            logger.info("UDP repeater is disabled in config")
            return
            
        if self._running:
            return

        # Create receive socket
        try:
            self._socket = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            self._socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            self._socket.bind((
                self._config.udp_repeater.listen_host,
                self._config.udp_repeater.listen_port
            ))
            self._socket.settimeout(1.0)  # Allow periodic check for shutdown
        except Exception as e:
            logger.error(f"Failed to bind UDP repeater socket: {e}")
            return

        # Create send socket
        self._send_socket = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self._send_socket.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)

        self._running = True
        self._thread = threading.Thread(target=self._run_loop, daemon=True)
        self._thread.start()
        
        logger.info(
            f"UDP repeater started on {self._config.udp_repeater.listen_host}:"
            f"{self._config.udp_repeater.listen_port}"
        )

    def stop(self) -> None:
        """Stop the UDP repeater."""
        self._running = False
        
        if self._socket:
            try:
                self._socket.close()
            except Exception:
                pass
            self._socket = None
            
        if self._send_socket:
            try:
                self._send_socket.close()
            except Exception:
                pass
            self._send_socket = None
            
        if self._thread:
            self._thread.join(timeout=5)
            self._thread = None
            
        logger.info("UDP repeater stopped")

    def _run_loop(self) -> None:
        """Main receive loop."""
        while self._running:
            try:
                data, addr = self._socket.recvfrom(1024)
                self._handle_packet(data, addr)
            except socket.timeout:
                continue
            except Exception as e:
                if self._running:
                    logger.error(f"UDP repeater receive error: {e}")

    def _handle_packet(self, data: bytes, addr: tuple) -> None:
        """Handle an incoming UDP packet (v1 or v2)."""
        # Validate minimum packet size (header + version + count/channels + at least 1 value)
        if len(data) < 6:
            logger.debug(f"Packet too short from {addr}: {len(data)} bytes")
            return

        # Validate header
        if data[:3] != PACKET_HEADER:
            logger.debug(f"Invalid header from {addr}: {data[:3]}")
            return

        version = data[3]
        
        if version == PACKET_VERSION_1:
            self._handle_v1_packet(data, addr)
        elif version == PACKET_VERSION_2:
            self._handle_v2_packet(data, addr)
        else:
            logger.debug(f"Unsupported version from {addr}: {version}")
    
    def _handle_v1_packet(self, data: bytes, addr: tuple) -> None:
        """Handle a LED v1 single-stream packet."""
        # Parse channels and values
        num_channels = data[4]
        expected_len = 5 + num_channels
        
        if len(data) < expected_len:
            logger.debug(f"Packet truncated from {addr}: expected {expected_len}, got {len(data)}")
            return

        values = list(data[5:5 + num_channels])
        
        # Forward to target devices using legacy single-stream logic
        self._forward_to_devices_v1(values)
    
    def _handle_v2_packet(self, data: bytes, addr: tuple) -> None:
        """Handle a LED v2 multi-stream packet."""
        stream_count = data[4]
        offset = 5
        
        streams: dict[StreamID, list[int]] = {}
        
        for _ in range(stream_count):
            if offset + 2 > len(data):
                logger.debug(f"V2 packet truncated at stream header from {addr}")
                return
            
            stream_id_raw = data[offset]
            num_channels = data[offset + 1]
            offset += 2
            
            if offset + num_channels > len(data):
                logger.debug(f"V2 packet truncated at stream values from {addr}")
                return
            
            values = list(data[offset:offset + num_channels])
            offset += num_channels
            
            try:
                stream_id = StreamID(stream_id_raw)
                streams[stream_id] = values
            except ValueError:
                # Unknown stream ID, skip but continue parsing
                logger.debug(f"Unknown stream ID {stream_id_raw} from {addr}")
        
        if not streams:
            return
        
        # Cache streams for device forwarding
        self._last_streams = streams
        
        # Forward to target devices with stream selection
        self._forward_to_devices_v2(streams)

    def _forward_to_devices_v1(self, values: list[int]) -> None:
        """Forward v1 single-stream values to all devices (legacy behavior)."""
        # Get devices in FAST mode with udp_repeater type
        target_device_ids = self._state.get_devices_by_fast_mode_type(FastModeType.UDP_REPEATER)
        
        if not target_device_ids:
            return

        for device_id in target_device_ids:
            try:
                self._send_to_device_v1(device_id, values)
            except Exception as e:
                logger.debug(f"Failed to forward to {device_id}: {e}")
    
    def _forward_to_devices_v2(self, streams: dict[StreamID, list[int]]) -> None:
        """Forward v2 multi-stream values, selecting best stream per device."""
        target_device_ids = self._state.get_devices_by_fast_mode_type(FastModeType.UDP_REPEATER)
        
        if not target_device_ids:
            return

        for device_id in target_device_ids:
            try:
                self._send_to_device_v2(device_id, streams)
            except Exception as e:
                logger.debug(f"Failed to forward to {device_id}: {e}")

    def _send_to_device_v1(self, device_id: str, input_values: list[int]) -> None:
        """Send v1 values to a specific device, adapting channel count."""
        device_config = self._config.get_device_by_id(device_id)
        if not device_config:
            return

        device_state = self._state.get_device_state(device_id)
        if not device_state:
            return

        # Adapt values to device channel count
        device_channels = device_config.channels
        adapted_values = self._adapt_channels(input_values, device_channels, device_config.hw_mode)
        
        # Update state (for UI display)
        self._state.set_fast_values(device_id, adapted_values)

        # Build and send packet
        packet = self._build_packet(adapted_values)
        
        if self._send_socket:
            self._send_socket.sendto(packet, (device_config.ip, device_config.udp_port))
    
    def _send_to_device_v2(self, device_id: str, streams: dict[StreamID, list[int]]) -> None:
        """Send v2 values to a device, selecting best matching stream."""
        device_config = self._config.get_device_by_id(device_id)
        if not device_config:
            return

        device_state = self._state.get_device_state(device_id)
        if not device_state:
            return

        hw_mode = device_config.hw_mode
        device_channels = device_config.channels
        
        # Select best stream for this device
        values = self._select_stream_for_device(streams, hw_mode, device_channels)
        
        # Update state (for UI display)
        self._state.set_fast_values(device_id, values)

        # Build and send packet
        packet = self._build_packet(values)
        
        if self._send_socket:
            self._send_socket.sendto(packet, (device_config.ip, device_config.udp_port))
    
    def _select_stream_for_device(
        self, 
        streams: dict[StreamID, list[int]], 
        hw_mode: str,
        device_channels: int
    ) -> list[int]:
        """
        Select the best stream for a device based on its hw_mode.
        
        Priority:
        1. Exact match: stream with matching hw_mode
        2. Fallback to 4ch_v1 and adapt (existing behavior)
        3. Use first available stream and truncate/pad
        """
        # Try exact match
        target_stream_id = HW_MODE_TO_STREAM_ID.get(hw_mode)
        if target_stream_id and target_stream_id in streams:
            values = streams[target_stream_id]
            # Still need to adapt if channel count differs
            if len(values) != device_channels:
                return self._adapt_channels(values, device_channels, hw_mode)
            return values
        
        # Fallback to 4ch_v1 with adaptation
        if StreamID.CH4_V1 in streams:
            values = streams[StreamID.CH4_V1]
            return self._adapt_channels(values, device_channels, hw_mode)
        
        # Use first available stream
        if streams:
            first_values = next(iter(streams.values()))
            return self._adapt_channels(first_values, device_channels, hw_mode)
        
        # No streams available
        return [0] * device_channels

    def _adapt_channels(self, input_values: list[int], target_channels: int, hw_mode: str) -> list[int]:
        """
        Adapt input values to the target device's channel count.
        
        For 2ch_v1 receiving 4ch input (R,Y,G,B order from 4ch_v1 which is G,Y,B,R):
            - output0 (Red+Yellow) = max of input channels corresponding to R and Y
            - output1 (Green+Blue) = max of input channels corresponding to G and B
        
        For other cases: truncate or pad with zeros.
        """
        input_len = len(input_values)
        
        # Special handling for 2ch_v1 when receiving 4ch input
        if hw_mode == "2ch_v1" and input_len >= 4:
            # 4ch_v1 order is: Green(0), Yellow(1), Blue(2), Red(3)
            # 2ch_v1: output0 = Red+Yellow, output1 = Green+Blue
            green = input_values[0]
            yellow = input_values[1]
            blue = input_values[2]
            red = input_values[3]
            return [max(red, yellow), max(green, blue)]
        
        # Generic adaptation: truncate or pad
        if input_len >= target_channels:
            return input_values[:target_channels]
        else:
            return input_values + [0] * (target_channels - input_len)

    def _build_packet(self, values: list[int]) -> bytes:
        """Build a LED v1 packet for sending to a device."""
        num_channels = len(values)
        clamped_values = [max(0, min(255, v)) for v in values]
        
        packet = bytearray()
        packet.extend(PACKET_HEADER)
        packet.append(PACKET_VERSION)
        packet.append(num_channels)
        packet.extend(clamped_values)
        
        return bytes(packet)
