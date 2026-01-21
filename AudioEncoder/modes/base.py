"""Base classes for visualization modes."""

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Optional, Any
import numpy as np


@dataclass
class ModeOutput:
    """Output from a visualization mode."""
    values_4ch: list[float] = field(default_factory=lambda: [0.0, 0.0, 0.0, 0.0])
    values_2ch: list[float] = field(default_factory=lambda: [0.0, 0.0])
    values_rgb: list[float] = field(default_factory=lambda: [0.0, 0.0, 0.0])
    
    def to_bytes_4ch(self) -> list[int]:
        """Convert 4ch values to 0-255 bytes."""
        return [max(0, min(255, int(v * 255))) for v in self.values_4ch]
    
    def to_bytes_2ch(self) -> list[int]:
        """Convert 2ch values to 0-255 bytes."""
        return [max(0, min(255, int(v * 255))) for v in self.values_2ch]
    
    def to_bytes_rgb(self) -> list[int]:
        """Convert RGB values to 0-255 bytes."""
        return [max(0, min(255, int(v * 255))) for v in self.values_rgb]


class Mode(ABC):
    """Abstract base class for visualization modes."""
    
    # Mode identifier (override in subclasses)
    MODE_ID: str = "base"
    MODE_NAME: str = "Base Mode"
    
    def __init__(self):
        self._enabled = True
        self._gain = 1.0
    
    @property
    def enabled(self) -> bool:
        return self._enabled
    
    @enabled.setter
    def enabled(self, value: bool) -> None:
        self._enabled = value
    
    @property
    def gain(self) -> float:
        return self._gain
    
    @gain.setter
    def gain(self, value: float) -> None:
        self._gain = max(0.0, min(5.0, value))
    
    @abstractmethod
    def process(self, samples: np.ndarray, sample_rate: int) -> ModeOutput:
        """
        Process audio samples and produce LED output values.
        
        Args:
            samples: Audio samples (float32, -1 to 1)
            sample_rate: Sample rate in Hz
            
        Returns:
            ModeOutput with brightness values for each channel configuration
        """
        pass
    
    @abstractmethod
    def get_parameters(self) -> dict[str, Any]:
        """Get current mode parameters for UI/serialization."""
        pass
    
    @abstractmethod
    def set_parameters(self, params: dict[str, Any]) -> None:
        """Set mode parameters from dict."""
        pass
    
    def reset(self) -> None:
        """Reset mode state."""
        pass


class ModeRegistry:
    """Registry for available visualization modes."""
    
    _modes: dict[str, type[Mode]] = {}
    
    @classmethod
    def register(cls, mode_class: type[Mode]) -> type[Mode]:
        """Register a mode class. Can be used as decorator."""
        cls._modes[mode_class.MODE_ID] = mode_class
        return mode_class
    
    @classmethod
    def get(cls, mode_id: str) -> Optional[type[Mode]]:
        """Get a mode class by ID."""
        return cls._modes.get(mode_id)
    
    @classmethod
    def create(cls, mode_id: str) -> Optional[Mode]:
        """Create a mode instance by ID."""
        mode_class = cls._modes.get(mode_id)
        if mode_class:
            return mode_class()
        return None
    
    @classmethod
    def list_modes(cls) -> list[tuple[str, str]]:
        """List available modes as (id, name) tuples."""
        return [(m.MODE_ID, m.MODE_NAME) for m in cls._modes.values()]
