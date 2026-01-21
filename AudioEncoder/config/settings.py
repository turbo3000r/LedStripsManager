"""Settings management and preset storage for AudioEncoder."""

import json
import os
from dataclasses import dataclass, field, asdict
from typing import Optional
from pathlib import Path


@dataclass
class ConnectionSettings:
    """Server connection settings."""
    host: str = "127.0.0.1"
    port: int = 5001  # Server's udp_repeater.listen_port
    fps: int = 60
    enabled: bool = False


@dataclass
class AudioSettings:
    """Audio source settings."""
    source_type: str = "mic"  # "mic" or "loopback"
    device_index: Optional[int] = None
    sample_rate: int = 22050  # Lower sample rate reduces system load and interference
    chunk_size: int = 4096  # Large buffer (4096 samples = ~186ms at 22050Hz) to minimize system interference


@dataclass
class ModeSettings:
    """Visualization mode settings."""
    active_mode: str = "vu"  # "vu", "fft", "beat", "combined"
    
    # VU/RMS settings
    vu_gain: float = 1.0
    vu_smoothing: float = 0.3  # 0-1, higher = smoother
    
    # FFT settings
    fft_bands: int = 4  # Number of frequency bands
    fft_gain: float = 1.0
    fft_smoothing: float = 0.2
    
    # Beat detection settings
    beat_sensitivity: float = 1.5
    beat_decay: float = 0.95
    
    # Post-processing
    agc_enabled: bool = True
    agc_target: float = 0.7  # Target output level (0-1)
    agc_attack: float = 0.1
    agc_release: float = 0.01
    
    peak_hold_enabled: bool = True
    peak_decay: float = 0.98


@dataclass
class StreamSettings:
    """Output stream configuration."""
    send_4ch_v1: bool = True
    send_2ch_v1: bool = True
    send_rgb_v1: bool = False
    use_v2_protocol: bool = True  # Use LED v2 multi-stream when multiple streams enabled


@dataclass 
class AppSettings:
    """Complete application settings."""
    connection: ConnectionSettings = field(default_factory=ConnectionSettings)
    audio: AudioSettings = field(default_factory=AudioSettings)
    mode: ModeSettings = field(default_factory=ModeSettings)
    streams: StreamSettings = field(default_factory=StreamSettings)


class SettingsManager:
    """Manages settings persistence and presets."""
    
    def __init__(self, config_dir: Optional[Path] = None):
        if config_dir is None:
            config_dir = Path(__file__).parent
        self.config_dir = config_dir
        self.settings_file = config_dir / "user_settings.json"
        self.presets_dir = config_dir / "presets"
        self._settings: AppSettings = AppSettings()
        
    @property
    def settings(self) -> AppSettings:
        return self._settings
    
    def load(self) -> AppSettings:
        """Load settings from file."""
        if self.settings_file.exists():
            try:
                with open(self.settings_file, "r") as f:
                    data = json.load(f)
                self._settings = self._from_dict(data)
            except (json.JSONDecodeError, KeyError) as e:
                print(f"Failed to load settings: {e}, using defaults")
                self._settings = AppSettings()
        return self._settings
    
    def save(self) -> None:
        """Save current settings to file."""
        self.config_dir.mkdir(parents=True, exist_ok=True)
        with open(self.settings_file, "w") as f:
            json.dump(self._to_dict(self._settings), f, indent=2)
    
    def load_preset(self, name: str) -> bool:
        """Load a named preset."""
        preset_file = self.presets_dir / f"{name}.json"
        if preset_file.exists():
            try:
                with open(preset_file, "r") as f:
                    data = json.load(f)
                self._settings = self._from_dict(data)
                return True
            except (json.JSONDecodeError, KeyError):
                return False
        return False
    
    def save_preset(self, name: str) -> None:
        """Save current settings as a named preset."""
        self.presets_dir.mkdir(parents=True, exist_ok=True)
        preset_file = self.presets_dir / f"{name}.json"
        with open(preset_file, "w") as f:
            json.dump(self._to_dict(self._settings), f, indent=2)
    
    def list_presets(self) -> list[str]:
        """List available preset names."""
        if not self.presets_dir.exists():
            return []
        return [p.stem for p in self.presets_dir.glob("*.json")]
    
    def delete_preset(self, name: str) -> bool:
        """Delete a preset by name."""
        preset_file = self.presets_dir / f"{name}.json"
        if preset_file.exists():
            preset_file.unlink()
            return True
        return False
    
    def _to_dict(self, settings: AppSettings) -> dict:
        """Convert settings to dictionary."""
        return {
            "connection": asdict(settings.connection),
            "audio": asdict(settings.audio),
            "mode": asdict(settings.mode),
            "streams": asdict(settings.streams),
        }
    
    def _from_dict(self, data: dict) -> AppSettings:
        """Create settings from dictionary."""
        return AppSettings(
            connection=ConnectionSettings(**data.get("connection", {})),
            audio=AudioSettings(**data.get("audio", {})),
            mode=ModeSettings(**data.get("mode", {})),
            streams=StreamSettings(**data.get("streams", {})),
        )


# Global settings manager instance
_settings_manager: Optional[SettingsManager] = None


def get_settings_manager() -> SettingsManager:
    """Get the global settings manager instance."""
    global _settings_manager
    if _settings_manager is None:
        _settings_manager = SettingsManager()
        _settings_manager.load()
    return _settings_manager
