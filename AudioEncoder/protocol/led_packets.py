"""LED protocol packet builders for UDP communication."""

from enum import IntEnum
from typing import Optional


# Protocol constants
PACKET_HEADER = b"LED"
VERSION_1 = 1
VERSION_2 = 2


class StreamID(IntEnum):
    """Stream identifiers for LED v2 protocol."""
    CH4_V1 = 1   # 4ch_v1: Green, Yellow, Blue, Red
    CH2_V1 = 2   # 2ch_v1: Red+Yellow, Green+Blue
    RGB_V1 = 3   # rgb_v1: Red, Green, Blue


def build_led_v1_packet(values: list[int]) -> bytes:
    """
    Build a LED v1 protocol packet.
    
    Format:
        Header:   3 bytes  "LED"
        Version:  1 byte   Protocol version (1)
        Channels: 1 byte   Number of channels (N)
        Values:   N bytes  Brightness values (0-255)
    
    Args:
        values: List of brightness values (0-255)
        
    Returns:
        Bytes of the complete packet
    """
    num_channels = len(values)
    clamped = [max(0, min(255, v)) for v in values]
    
    packet = bytearray()
    packet.extend(PACKET_HEADER)
    packet.append(VERSION_1)
    packet.append(num_channels)
    packet.extend(clamped)
    
    return bytes(packet)


def build_led_v2_packet(streams: dict[StreamID, list[int]]) -> bytes:
    """
    Build a LED v2 multi-stream protocol packet.
    
    Format:
        Header:      3 bytes   "LED"
        Version:     1 byte    Protocol version (2)
        StreamCount: 1 byte    Number of streams (S)
        Streams:     variable  S stream blocks
        
    Stream Block:
        StreamID:  1 byte   Hardware mode identifier
        Channels:  1 byte   Number of channels (N)
        Values:    N bytes  Brightness values (0-255)
    
    Args:
        streams: Dict mapping StreamID to list of brightness values (0-255)
        
    Returns:
        Bytes of the complete packet
    """
    packet = bytearray()
    packet.extend(PACKET_HEADER)
    packet.append(VERSION_2)
    packet.append(len(streams))
    
    for stream_id, values in streams.items():
        num_channels = len(values)
        clamped = [max(0, min(255, v)) for v in values]
        
        packet.append(int(stream_id))
        packet.append(num_channels)
        packet.extend(clamped)
    
    return bytes(packet)


def parse_led_packet(data: bytes) -> Optional[dict]:
    """
    Parse a LED protocol packet (v1 or v2).
    
    Returns:
        Dict with packet info, or None if invalid.
        
        For v1: {"version": 1, "values": [...]}
        For v2: {"version": 2, "streams": {StreamID: [...]}}
    """
    # Minimum size: header(3) + version(1) + channels/count(1) + at least 1 value
    if len(data) < 6:
        return None
    
    # Check header
    if data[:3] != PACKET_HEADER:
        return None
    
    version = data[3]
    
    if version == VERSION_1:
        num_channels = data[4]
        expected_len = 5 + num_channels
        if len(data) < expected_len:
            return None
        
        values = list(data[5:5 + num_channels])
        return {"version": 1, "values": values}
    
    elif version == VERSION_2:
        stream_count = data[4]
        streams = {}
        offset = 5
        
        for _ in range(stream_count):
            if offset + 2 > len(data):
                return None
            
            stream_id = data[offset]
            num_channels = data[offset + 1]
            offset += 2
            
            if offset + num_channels > len(data):
                return None
            
            values = list(data[offset:offset + num_channels])
            offset += num_channels
            
            try:
                streams[StreamID(stream_id)] = values
            except ValueError:
                # Unknown stream ID, skip
                pass
        
        return {"version": 2, "streams": streams}
    
    return None


# Convenience functions for common cases

def build_4ch_packet(green: int, yellow: int, blue: int, red: int) -> bytes:
    """Build a LED v1 packet for 4ch_v1 (G, Y, B, R order)."""
    return build_led_v1_packet([green, yellow, blue, red])


def build_2ch_packet(red_yellow: int, green_blue: int) -> bytes:
    """Build a LED v1 packet for 2ch_v1."""
    return build_led_v1_packet([red_yellow, green_blue])


def build_multi_stream_packet(
    values_4ch: Optional[list[int]] = None,
    values_2ch: Optional[list[int]] = None,
    values_rgb: Optional[list[int]] = None
) -> bytes:
    """
    Build a LED v2 multi-stream packet with the specified streams.
    
    Args:
        values_4ch: 4-channel values [G, Y, B, R] (optional)
        values_2ch: 2-channel values [R+Y, G+B] (optional)
        values_rgb: 3-channel values [R, G, B] (optional)
        
    Returns:
        LED v2 packet bytes
    """
    streams = {}
    
    if values_4ch is not None:
        streams[StreamID.CH4_V1] = values_4ch
    
    if values_2ch is not None:
        streams[StreamID.CH2_V1] = values_2ch
    
    if values_rgb is not None:
        streams[StreamID.RGB_V1] = values_rgb
    
    if not streams:
        # No streams, return empty v2 packet
        return build_led_v2_packet({})
    
    # If only one stream, use v1 for backward compatibility
    if len(streams) == 1:
        stream_id, values = next(iter(streams.items()))
        return build_led_v1_packet(values)
    
    return build_led_v2_packet(streams)
