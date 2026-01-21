"""Configuration loading and validation for the Lighting Control Hub."""

import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

import yaml

from app.device_modes import get_mode_or_default, DEFAULT_MODE

logger = logging.getLogger(__name__)


@dataclass
class DeviceTopics:
    """MQTT topics for a device."""
    set_plan: str
    set_static: str
    heartbeat: str


@dataclass
class DeviceConfig:
    """Configuration for a single ESP device."""
    device_id: str
    ip: str
    udp_port: int
    hw_mode: str  # Hardware mode ID (e.g., "4ch_v1", "rgb_v1")
    channels: int  # Derived from hw_mode
    channel_labels: tuple[str, ...]  # Derived from hw_mode
    topics: DeviceTopics
    firmware_version: str = "unknown"
    room: str = ""  # Set after parsing


@dataclass
class RoomConfig:
    """Configuration for a room containing devices."""
    name: str
    devices: list[DeviceConfig] = field(default_factory=list)


@dataclass
class MqttConfig:
    """MQTT broker configuration."""
    broker_host: str = "localhost"
    broker_port: int = 1883
    client_id: str = "lighting_hub"
    reconnect_delay_min: int = 1
    reconnect_delay_max: int = 60
    heartbeat_timeout_sec: int = 10


@dataclass
class UdpConfig:
    """UDP streaming configuration."""
    default_port: int = 5000
    send_rate_hz: int = 60


@dataclass
class UdpRepeaterConfig:
    """UDP repeater configuration for receiving external frames."""
    enabled: bool = True
    listen_host: str = "0.0.0.0"
    listen_port: int = 5001  # Separate from device ports


@dataclass
class PlannerConfig:
    """Planner configuration."""
    interval_sec: int = 1
    steps_per_interval: int = 10
    interval_ms: int = 100
    plan_payload_version: int = 2  # 1 = legacy (timestamp+interval_ms+sequence), 2 = per-step timestamps


@dataclass
class AppConfig:
    """Complete application configuration."""
    mqtt: MqttConfig
    udp: UdpConfig
    planner: PlannerConfig
    udp_repeater: UdpRepeaterConfig = field(default_factory=UdpRepeaterConfig)
    rooms: list[RoomConfig] = field(default_factory=list)

    def get_all_devices(self) -> list[DeviceConfig]:
        """Get a flat list of all devices across all rooms."""
        devices = []
        for room in self.rooms:
            devices.extend(room.devices)
        return devices

    def get_device_by_id(self, device_id: str) -> Optional[DeviceConfig]:
        """Find a device by its ID."""
        for room in self.rooms:
            for device in room.devices:
                if device.device_id == device_id:
                    return device
        return None


def load_config(config_path: str = "config/config.yaml") -> AppConfig:
    """Load configuration from YAML file."""
    path = Path(config_path)
    if not path.exists():
        raise FileNotFoundError(f"Configuration file not found: {config_path}")

    with open(path, "r", encoding="utf-8") as f:
        raw = yaml.safe_load(f)

    # Parse MQTT config
    mqtt_raw = raw.get("mqtt", {})
    mqtt_config = MqttConfig(
        broker_host=mqtt_raw.get("broker_host", "localhost"),
        broker_port=mqtt_raw.get("broker_port", 1883),
        client_id=mqtt_raw.get("client_id", "lighting_hub"),
        reconnect_delay_min=mqtt_raw.get("reconnect_delay_min", 1),
        reconnect_delay_max=mqtt_raw.get("reconnect_delay_max", 60),
        heartbeat_timeout_sec=mqtt_raw.get("heartbeat_timeout_sec", 10),
    )

    # Parse UDP config
    udp_raw = raw.get("udp", {})
    udp_config = UdpConfig(
        default_port=udp_raw.get("default_port", 5000),
        send_rate_hz=udp_raw.get("send_rate_hz", 60),
    )

    # Parse Planner config
    planner_raw = raw.get("planner", {})
    planner_config = PlannerConfig(
        interval_sec=planner_raw.get("interval_sec", 1),
        steps_per_interval=planner_raw.get("steps_per_interval", 10),
        interval_ms=planner_raw.get("interval_ms", 100),
        plan_payload_version=planner_raw.get("plan_payload_version", 2),
    )

    # Parse UDP Repeater config
    udp_repeater_raw = raw.get("udp_repeater", {})
    udp_repeater_config = UdpRepeaterConfig(
        enabled=udp_repeater_raw.get("enabled", True),
        listen_host=udp_repeater_raw.get("listen_host", "0.0.0.0"),
        listen_port=udp_repeater_raw.get("listen_port", 5001),
    )

    # Parse rooms and devices
    rooms = []
    for room_raw in raw.get("rooms", []):
        room_name = room_raw.get("name", "Unknown Room")
        devices = []
        for dev_raw in room_raw.get("devices", []):
            topics_raw = dev_raw.get("topics", {})
            topics = DeviceTopics(
                set_plan=topics_raw.get("set_plan", ""),
                set_static=topics_raw.get("set_static", ""),
                heartbeat=topics_raw.get("heartbeat", ""),
            )
            # Get hw_mode; fall back to legacy 'channels' if hw_mode not specified
            hw_mode_raw = dev_raw.get("hw_mode")
            if hw_mode_raw:
                mode = get_mode_or_default(hw_mode_raw)
                hw_mode = mode.mode_id
                channels = mode.channels
                channel_labels = mode.labels
            else:
                # Legacy fallback: use 'channels' field directly
                legacy_channels = dev_raw.get("channels", 4)
                hw_mode = DEFAULT_MODE
                mode = get_mode_or_default(hw_mode)
                channels = legacy_channels
                # Generate generic labels if channel count doesn't match mode
                if legacy_channels == mode.channels:
                    channel_labels = mode.labels
                else:
                    channel_labels = tuple(f"CH{i+1}" for i in range(legacy_channels))
                logger.warning(
                    f"Device {dev_raw.get('device_id', '?')} uses legacy 'channels' field. "
                    f"Consider migrating to 'hw_mode'."
                )

            device = DeviceConfig(
                device_id=dev_raw.get("device_id", ""),
                ip=dev_raw.get("ip", ""),
                udp_port=dev_raw.get("udp_port", udp_config.default_port),
                hw_mode=hw_mode,
                channels=channels,
                channel_labels=channel_labels,
                topics=topics,
                firmware_version=dev_raw.get("firmware_version", "unknown"),
                room=room_name,
            )
            devices.append(device)
        rooms.append(RoomConfig(name=room_name, devices=devices))

    return AppConfig(
        mqtt=mqtt_config,
        udp=udp_config,
        planner=planner_config,
        udp_repeater=udp_repeater_config,
        rooms=rooms,
    )


# Global config instance (loaded on import)
_config: Optional[AppConfig] = None


def get_config() -> AppConfig:
    """Get the global configuration instance."""
    global _config
    if _config is None:
        _config = load_config()
    return _config


def reload_config() -> AppConfig:
    """Reload configuration from disk."""
    global _config
    _config = load_config()
    return _config

