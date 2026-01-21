"""Thread-safe shared state for the Lighting Control Hub."""

import json
import threading
import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Optional

from app.config import AppConfig, DeviceConfig


class DeviceMode(Enum):
    """Operating mode for a device."""
    STATIC = "static"
    PLANNED = "planned"
    FAST = "fast"


class RoomControlMode(Enum):
    """Control mode for a room (AUTO broadcasts to all devices, MANUAL allows per-device control)."""
    AUTO = "auto"
    MANUAL = "manual"


class FastModeType(Enum):
    """Type of fast mode operation."""
    INTERNAL = "internal"  # Server-controlled values
    UDP_REPEATER = "udp_repeater"  # Server relays external UDP frames


@dataclass
class RoomControlState:
    """Runtime control state for a room (used in AUTO mode)."""
    room_name: str
    control_mode: RoomControlMode = RoomControlMode.MANUAL
    
    # Shared room settings (applied to all devices when in AUTO mode)
    mode: DeviceMode = DeviceMode.STATIC
    static_values: list[int] = field(default_factory=lambda: [0, 0, 0, 0])
    planned_plan_id: Optional[str] = None
    fast_mode_type: FastModeType = FastModeType.INTERNAL
    
    def to_dict(self) -> dict:
        """Convert to dictionary for JSON serialization."""
        return {
            "room_name": self.room_name,
            "control_mode": self.control_mode.value,
            "mode": self.mode.value,
            "static_values": self.static_values.copy(),
            "planned_plan_id": self.planned_plan_id,
            "fast_mode_type": self.fast_mode_type.value,
        }


@dataclass
class DeviceState:
    """Runtime state for a single device."""
    device_id: str
    room: str
    ip: str
    udp_port: int
    hw_mode: str  # Hardware mode ID (e.g., "4ch_v1", "rgb_v1")
    channels: int
    channel_labels: tuple[str, ...]  # Channel labels (e.g., ("Green", "Yellow", "Blue", "Red"))
    firmware_version: str

    # Mode and values (per-device settings, used in MANUAL mode or as overrides)
    mode: DeviceMode = DeviceMode.STATIC
    static_values: list[int] = field(default_factory=list)
    fast_values: list[int] = field(default_factory=list)

    # Planned mode: selected plan ID (memory-only)
    planned_plan_id: Optional[str] = None
    
    # Fast mode type (internal or udp_repeater)
    fast_mode_type: FastModeType = FastModeType.INTERNAL

    # Connectivity
    last_heartbeat: float = 0.0
    online: bool = False

    # Error tracking
    error_count: int = 0
    reconnect_count: int = 0

    def __post_init__(self):
        """Initialize channel arrays if empty."""
        if not self.static_values:
            self.static_values = [0] * self.channels
        if not self.fast_values:
            self.fast_values = [0] * self.channels

    def to_dict(self) -> dict:
        """Convert to dictionary for JSON serialization."""
        return {
            "device_id": self.device_id,
            "room": self.room,
            "ip": self.ip,
            "udp_port": self.udp_port,
            "hw_mode": self.hw_mode,
            "channels": self.channels,
            "channel_labels": list(self.channel_labels),
            "firmware_version": self.firmware_version,
            "mode": self.mode.value,
            "static_values": self.static_values.copy(),
            "fast_values": self.fast_values.copy(),
            "planned_plan_id": self.planned_plan_id,
            "fast_mode_type": self.fast_mode_type.value,
            "online": self.online,
            "last_heartbeat": self.last_heartbeat,
            "error_count": self.error_count,
            "reconnect_count": self.reconnect_count,
        }


class SharedState:
    """Thread-safe shared state manager."""

    def __init__(self):
        self._lock = threading.RLock()
        self._devices: dict[str, DeviceState] = {}
        self._rooms: dict[str, RoomControlState] = {}  # room_name -> RoomControlState
        self._heartbeat_timeout: float = 10.0
        self._mqtt_connected: bool = False
        self._mqtt_error_count: int = 0
        # State versioning for change detection
        self._state_version: int = 0
        self._last_broadcast_hash: str = ""
        self._last_broadcast_version: int = 0

    def _increment_version(self) -> None:
        """Increment the state version (call within lock)."""
        self._state_version += 1

    def _compute_state_hash(self, state_data: list[dict]) -> str:
        """Compute a hash of the state data for change detection."""
        return json.dumps(state_data, sort_keys=True)

    def has_state_changed(self) -> bool:
        """Check if state has changed since last broadcast."""
        with self._lock:
            current_state = self.get_all_device_status()
            current_hash = self._compute_state_hash(current_state)
            return current_hash != self._last_broadcast_hash

    def mark_broadcast_complete(self, state_data: list[dict]) -> None:
        """Mark the current state as broadcast (for change detection)."""
        with self._lock:
            self._last_broadcast_hash = self._compute_state_hash(state_data)
            self._last_broadcast_version = self._state_version

    def get_state_version(self) -> int:
        """Get the current state version number."""
        with self._lock:
            return self._state_version

    def initialize_from_config(self, config: AppConfig) -> None:
        """Initialize device states from configuration."""
        with self._lock:
            self._heartbeat_timeout = float(config.mqtt.heartbeat_timeout_sec)
            self._devices.clear()
            self._rooms.clear()

            for room in config.rooms:
                # Initialize room control state
                # Find max channels in room for default static_values size
                max_channels = max((d.channels for d in room.devices), default=4)
                self._rooms[room.name] = RoomControlState(
                    room_name=room.name,
                    static_values=[0] * max_channels,
                )
                
                for device in room.devices:
                    self._devices[device.device_id] = DeviceState(
                        device_id=device.device_id,
                        room=room.name,
                        ip=device.ip,
                        udp_port=device.udp_port,
                        hw_mode=device.hw_mode,
                        channels=device.channels,
                        channel_labels=device.channel_labels,
                        firmware_version=device.firmware_version,
                        static_values=[0] * device.channels,
                        fast_values=[0] * device.channels,
                    )
            self._increment_version()

    def get_device_ids(self) -> list[str]:
        """Get list of all device IDs."""
        with self._lock:
            return list(self._devices.keys())

    def get_device_state(self, device_id: str) -> Optional[DeviceState]:
        """Get a copy of a device's state (not thread-safe for modifications)."""
        with self._lock:
            device = self._devices.get(device_id)
            if device:
                # Return a shallow copy for reading
                return device
            return None

    def get_device_status(self, device_id: str) -> Optional[dict]:
        """Get device status as a dictionary."""
        with self._lock:
            device = self._devices.get(device_id)
            if device:
                self._update_online_status(device)
                return device.to_dict()
            return None

    def get_all_device_status(self) -> list[dict]:
        """Get status of all devices."""
        with self._lock:
            result = []
            for device in self._devices.values():
                self._update_online_status(device)
                result.append(device.to_dict())
            return result

    def _update_online_status(self, device: DeviceState) -> None:
        """Update the online status based on heartbeat timeout."""
        if device.last_heartbeat > 0:
            elapsed = time.time() - device.last_heartbeat
            device.online = elapsed < self._heartbeat_timeout
        else:
            device.online = False

    def set_device_mode(self, device_id: str, mode: DeviceMode) -> bool:
        """Set the operating mode for a device."""
        with self._lock:
            device = self._devices.get(device_id)
            if device:
                device.mode = mode
                self._increment_version()
                return True
            return False

    def get_device_mode(self, device_id: str) -> Optional[DeviceMode]:
        """Get the operating mode for a device."""
        with self._lock:
            device = self._devices.get(device_id)
            if device:
                return device.mode
            return None

    def set_static_values(self, device_id: str, values: list[int]) -> bool:
        """Set static brightness values for a device."""
        with self._lock:
            device = self._devices.get(device_id)
            if device:
                # Clamp values to 0-255 and pad/truncate to match channel count
                clamped = [max(0, min(255, v)) for v in values]
                if len(clamped) < device.channels:
                    clamped.extend([0] * (device.channels - len(clamped)))
                elif len(clamped) > device.channels:
                    clamped = clamped[:device.channels]
                device.static_values = clamped
                self._increment_version()
                return True
            return False

    def get_static_values(self, device_id: str) -> Optional[list[int]]:
        """Get static brightness values for a device."""
        with self._lock:
            device = self._devices.get(device_id)
            if device:
                return device.static_values.copy()
            return None

    def set_fast_values(self, device_id: str, values: list[int]) -> bool:
        """Set fast mode values for a device."""
        with self._lock:
            device = self._devices.get(device_id)
            if device:
                # Clamp values to 0-255 and pad/truncate to match channel count
                clamped = [max(0, min(255, v)) for v in values]
                if len(clamped) < device.channels:
                    clamped.extend([0] * (device.channels - len(clamped)))
                elif len(clamped) > device.channels:
                    clamped = clamped[:device.channels]
                device.fast_values = clamped
                self._increment_version()
                return True
            return False

    def get_fast_values(self, device_id: str) -> Optional[list[int]]:
        """Get fast mode values for a device."""
        with self._lock:
            device = self._devices.get(device_id)
            if device:
                return device.fast_values.copy()
            return None

    def update_heartbeat(self, device_id: str) -> bool:
        """Update the last heartbeat timestamp for a device."""
        with self._lock:
            device = self._devices.get(device_id)
            if device:
                was_online = device.online
                device.last_heartbeat = time.time()
                device.online = True
                # Only increment version if online status actually changed
                if not was_online:
                    self._increment_version()
                return True
            return False

    def increment_device_error(self, device_id: str) -> None:
        """Increment the error count for a device."""
        with self._lock:
            device = self._devices.get(device_id)
            if device:
                device.error_count += 1
                self._increment_version()

    def increment_device_reconnect(self, device_id: str) -> None:
        """Increment the reconnect count for a device."""
        with self._lock:
            device = self._devices.get(device_id)
            if device:
                device.reconnect_count += 1
                self._increment_version()

    def get_devices_by_mode(self, mode: DeviceMode) -> list[str]:
        """Get list of device IDs in a specific mode."""
        with self._lock:
            return [
                device_id
                for device_id, device in self._devices.items()
                if device.mode == mode
            ]

    def set_device_plan(self, device_id: str, plan_id: Optional[str]) -> bool:
        """Set the planned mode plan ID for a device."""
        with self._lock:
            device = self._devices.get(device_id)
            if device:
                device.planned_plan_id = plan_id
                self._increment_version()
                return True
            return False

    def get_device_plan(self, device_id: str) -> Optional[str]:
        """Get the planned mode plan ID for a device."""
        with self._lock:
            device = self._devices.get(device_id)
            if device:
                return device.planned_plan_id
            return None

    def set_mqtt_connected(self, connected: bool) -> None:
        """Set MQTT connection status."""
        with self._lock:
            if self._mqtt_connected != connected:
                self._mqtt_connected = connected
                self._increment_version()

    def is_mqtt_connected(self) -> bool:
        """Check if MQTT is connected."""
        with self._lock:
            return self._mqtt_connected

    def increment_mqtt_error(self) -> None:
        """Increment MQTT error count."""
        with self._lock:
            self._mqtt_error_count += 1

    def get_mqtt_error_count(self) -> int:
        """Get MQTT error count."""
        with self._lock:
            return self._mqtt_error_count

    # --- Room Control Methods ---

    def get_room_names(self) -> list[str]:
        """Get list of all room names."""
        with self._lock:
            return list(self._rooms.keys())

    def get_room_control_state(self, room_name: str) -> Optional[RoomControlState]:
        """Get the control state for a room."""
        with self._lock:
            return self._rooms.get(room_name)

    def get_all_room_control_states(self) -> dict[str, dict]:
        """Get all room control states as dictionaries."""
        with self._lock:
            return {name: room.to_dict() for name, room in self._rooms.items()}

    def set_room_control_mode(self, room_name: str, control_mode: RoomControlMode) -> bool:
        """Set the control mode (AUTO/MANUAL) for a room."""
        with self._lock:
            room = self._rooms.get(room_name)
            if room:
                room.control_mode = control_mode
                # When switching to AUTO, apply room settings to all devices
                if control_mode == RoomControlMode.AUTO:
                    self._apply_room_settings_to_devices(room_name)
                self._increment_version()
                return True
            return False

    def get_room_control_mode(self, room_name: str) -> Optional[RoomControlMode]:
        """Get the control mode for a room."""
        with self._lock:
            room = self._rooms.get(room_name)
            if room:
                return room.control_mode
            return None

    def set_room_mode(self, room_name: str, mode: DeviceMode) -> bool:
        """Set the operating mode for a room (applies to all devices in AUTO mode)."""
        with self._lock:
            room = self._rooms.get(room_name)
            if room:
                room.mode = mode
                if room.control_mode == RoomControlMode.AUTO:
                    self._apply_room_settings_to_devices(room_name)
                self._increment_version()
                return True
            return False

    def set_room_static_values(self, room_name: str, values: list[int]) -> bool:
        """Set static brightness values for a room (applies to all devices in AUTO mode)."""
        with self._lock:
            room = self._rooms.get(room_name)
            if room:
                # Clamp values to 0-255
                clamped = [max(0, min(255, v)) for v in values]
                room.static_values = clamped
                if room.control_mode == RoomControlMode.AUTO:
                    self._apply_room_settings_to_devices(room_name)
                self._increment_version()
                return True
            return False

    def set_room_planned_plan(self, room_name: str, plan_id: Optional[str]) -> bool:
        """Set the planned mode plan ID for a room (applies to all devices in AUTO mode)."""
        with self._lock:
            room = self._rooms.get(room_name)
            if room:
                room.planned_plan_id = plan_id
                if room.control_mode == RoomControlMode.AUTO:
                    self._apply_room_settings_to_devices(room_name)
                self._increment_version()
                return True
            return False

    def set_room_fast_mode_type(self, room_name: str, fast_mode_type: FastModeType) -> bool:
        """Set the fast mode type for a room (applies to all devices in AUTO mode)."""
        with self._lock:
            room = self._rooms.get(room_name)
            if room:
                room.fast_mode_type = fast_mode_type
                if room.control_mode == RoomControlMode.AUTO:
                    self._apply_room_settings_to_devices(room_name)
                self._increment_version()
                return True
            return False

    def _apply_room_settings_to_devices(self, room_name: str) -> None:
        """Apply room settings to all devices in the room (call within lock)."""
        room = self._rooms.get(room_name)
        if not room:
            return
        
        for device in self._devices.values():
            if device.room == room_name:
                device.mode = room.mode
                device.planned_plan_id = room.planned_plan_id
                device.fast_mode_type = room.fast_mode_type
                # Apply static values, adapting to device channel count
                device_values = room.static_values[:device.channels]
                if len(device_values) < device.channels:
                    device_values.extend([0] * (device.channels - len(device_values)))
                device.static_values = device_values

    def get_devices_in_room(self, room_name: str) -> list[str]:
        """Get list of device IDs in a specific room."""
        with self._lock:
            return [
                device_id
                for device_id, device in self._devices.items()
                if device.room == room_name
            ]

    def is_room_auto_mode(self, room_name: str) -> bool:
        """Check if a room is in AUTO control mode."""
        with self._lock:
            room = self._rooms.get(room_name)
            return room is not None and room.control_mode == RoomControlMode.AUTO

    def get_effective_mode(self, device_id: str) -> Optional[DeviceMode]:
        """Get the effective operating mode for a device (considers room AUTO mode)."""
        with self._lock:
            device = self._devices.get(device_id)
            if not device:
                return None
            room = self._rooms.get(device.room)
            if room and room.control_mode == RoomControlMode.AUTO:
                return room.mode
            return device.mode

    def get_effective_static_values(self, device_id: str) -> Optional[list[int]]:
        """Get the effective static values for a device (considers room AUTO mode)."""
        with self._lock:
            device = self._devices.get(device_id)
            if not device:
                return None
            room = self._rooms.get(device.room)
            if room and room.control_mode == RoomControlMode.AUTO:
                # Adapt room values to device channel count
                values = room.static_values[:device.channels]
                if len(values) < device.channels:
                    values = values + [0] * (device.channels - len(values))
                return values
            return device.static_values.copy()

    def get_effective_planned_plan(self, device_id: str) -> Optional[str]:
        """Get the effective planned plan ID for a device (considers room AUTO mode)."""
        with self._lock:
            device = self._devices.get(device_id)
            if not device:
                return None
            room = self._rooms.get(device.room)
            if room and room.control_mode == RoomControlMode.AUTO:
                return room.planned_plan_id
            return device.planned_plan_id

    def get_effective_fast_mode_type(self, device_id: str) -> Optional[FastModeType]:
        """Get the effective fast mode type for a device (considers room AUTO mode)."""
        with self._lock:
            device = self._devices.get(device_id)
            if not device:
                return None
            room = self._rooms.get(device.room)
            if room and room.control_mode == RoomControlMode.AUTO:
                return room.fast_mode_type
            return device.fast_mode_type

    def set_device_fast_mode_type(self, device_id: str, fast_mode_type: FastModeType) -> bool:
        """Set the fast mode type for a device."""
        with self._lock:
            device = self._devices.get(device_id)
            if device:
                device.fast_mode_type = fast_mode_type
                self._increment_version()
                return True
            return False

    def get_devices_by_fast_mode_type(self, fast_mode_type: FastModeType) -> list[str]:
        """Get list of device IDs with a specific fast mode type that are in fast mode."""
        with self._lock:
            result = []
            for device_id, device in self._devices.items():
                if device.mode != DeviceMode.FAST:
                    continue
                # Check effective fast mode type (considers room AUTO)
                room = self._rooms.get(device.room)
                effective_type = (
                    room.fast_mode_type
                    if room and room.control_mode == RoomControlMode.AUTO
                    else device.fast_mode_type
                )
                if effective_type == fast_mode_type:
                    result.append(device_id)
            return result


# Global state instance
_state: Optional[SharedState] = None


def get_state() -> SharedState:
    """Get the global shared state instance."""
    global _state
    if _state is None:
        _state = SharedState()
    return _state

