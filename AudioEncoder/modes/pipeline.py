"""Mode pipeline with post-processing effects."""

from typing import Optional, Any
import numpy as np

from .base import Mode, ModeOutput, ModeRegistry


class AGC:
    """Automatic Gain Control for consistent output levels."""
    
    def __init__(self, 
                 target: float = 0.7,
                 attack: float = 0.1,
                 release: float = 0.01,
                 min_gain: float = 0.5,
                 max_gain: float = 3.0):
        """
        Initialize AGC.
        
        Args:
            target: Target output level (0-1)
            attack: How fast gain increases when signal is low
            release: How fast gain decreases when signal is high
            min_gain: Minimum gain multiplier
            max_gain: Maximum gain multiplier
        """
        self.target = target
        self.attack = attack
        self.release = release
        self.min_gain = min_gain
        self.max_gain = max_gain
        self._current_gain = 1.0
    
    def process(self, values: list[float]) -> list[float]:
        """Apply AGC to values."""
        if not values:
            return values
        
        # Calculate current peak
        peak = max(values) if values else 0.0
        
        if peak > 0.01:  # Avoid division by zero / noise
            # Calculate desired gain to reach target
            desired_gain = self.target / peak
            
            # Smooth gain changes
            if desired_gain > self._current_gain:
                # Signal too quiet, increase gain (attack)
                self._current_gain += self.attack * (desired_gain - self._current_gain)
            else:
                # Signal too loud, decrease gain (release)
                self._current_gain += self.release * (desired_gain - self._current_gain)
            
            # Clamp gain
            self._current_gain = max(self.min_gain, min(self.max_gain, self._current_gain))
        
        # Apply gain
        return [min(1.0, v * self._current_gain) for v in values]
    
    def reset(self) -> None:
        self._current_gain = 1.0


class PeakHold:
    """Peak hold with decay for each channel."""
    
    def __init__(self, num_channels: int = 4, decay: float = 0.98):
        self.decay = decay
        self._peaks = [0.0] * num_channels
    
    def process(self, values: list[float]) -> list[float]:
        """Apply peak hold - output is max of current value and decaying peak."""
        result = []
        for i, v in enumerate(values):
            if i >= len(self._peaks):
                self._peaks.append(0.0)
            
            # Update peak
            if v > self._peaks[i]:
                self._peaks[i] = v
            else:
                self._peaks[i] *= self.decay
            
            # Output is the peak (which is >= current value)
            result.append(self._peaks[i])
        
        return result
    
    def reset(self) -> None:
        self._peaks = [0.0] * len(self._peaks)


class ModePipeline:
    """Pipeline that runs a mode and applies post-processing."""
    
    def __init__(self):
        self._mode: Optional[Mode] = None
        
        # Post-processing
        self._agc_enabled = True
        self._agc = AGC()
        
        self._peak_hold_enabled = False
        self._peak_hold_4ch = PeakHold(4)
        self._peak_hold_2ch = PeakHold(2)
        self._peak_hold_rgb = PeakHold(3)
    
    @property
    def mode(self) -> Optional[Mode]:
        return self._mode
    
    @mode.setter
    def mode(self, value: Optional[Mode]) -> None:
        self._mode = value
    
    def set_mode_by_id(self, mode_id: str) -> bool:
        """Set active mode by ID. Returns True if found."""
        mode = ModeRegistry.create(mode_id)
        if mode:
            self._mode = mode
            return True
        return False
    
    @property
    def agc_enabled(self) -> bool:
        return self._agc_enabled
    
    @agc_enabled.setter
    def agc_enabled(self, value: bool) -> None:
        self._agc_enabled = value
    
    @property
    def peak_hold_enabled(self) -> bool:
        return self._peak_hold_enabled
    
    @peak_hold_enabled.setter
    def peak_hold_enabled(self, value: bool) -> None:
        self._peak_hold_enabled = value
    
    def set_agc_params(self, target: float = 0.7, attack: float = 0.1, release: float = 0.01) -> None:
        """Configure AGC parameters."""
        self._agc.target = target
        self._agc.attack = attack
        self._agc.release = release
    
    def set_peak_decay(self, decay: float) -> None:
        """Set peak hold decay rate."""
        self._peak_hold_4ch.decay = decay
        self._peak_hold_2ch.decay = decay
        self._peak_hold_rgb.decay = decay
    
    def process(self, samples: np.ndarray, sample_rate: int) -> ModeOutput:
        """Process audio through the pipeline."""
        if self._mode is None:
            return ModeOutput()
        
        # Run mode
        output = self._mode.process(samples, sample_rate)
        
        # Apply AGC
        if self._agc_enabled:
            output.values_4ch = self._agc.process(output.values_4ch)
            # Share AGC state across channel configs for consistency
            output.values_2ch = [min(1.0, v * self._agc._current_gain) for v in output.values_2ch]
            output.values_rgb = [min(1.0, v * self._agc._current_gain) for v in output.values_rgb]
        
        # Apply peak hold
        if self._peak_hold_enabled:
            output.values_4ch = self._peak_hold_4ch.process(output.values_4ch)
            output.values_2ch = self._peak_hold_2ch.process(output.values_2ch)
            output.values_rgb = self._peak_hold_rgb.process(output.values_rgb)
        
        return output
    
    def reset(self) -> None:
        """Reset pipeline state."""
        if self._mode:
            self._mode.reset()
        self._agc.reset()
        self._peak_hold_4ch.reset()
        self._peak_hold_2ch.reset()
        self._peak_hold_rgb.reset()
    
    def get_config(self) -> dict[str, Any]:
        """Get pipeline configuration."""
        config = {
            "mode_id": self._mode.MODE_ID if self._mode else None,
            "mode_params": self._mode.get_parameters() if self._mode else {},
            "agc_enabled": self._agc_enabled,
            "agc_target": self._agc.target,
            "agc_attack": self._agc.attack,
            "agc_release": self._agc.release,
            "peak_hold_enabled": self._peak_hold_enabled,
            "peak_decay": self._peak_hold_4ch.decay,
        }
        return config
    
    def set_config(self, config: dict[str, Any]) -> None:
        """Set pipeline configuration."""
        if "mode_id" in config and config["mode_id"]:
            self.set_mode_by_id(config["mode_id"])
            if self._mode and "mode_params" in config:
                self._mode.set_parameters(config["mode_params"])
        
        if "agc_enabled" in config:
            self._agc_enabled = config["agc_enabled"]
        if "agc_target" in config:
            self._agc.target = config["agc_target"]
        if "agc_attack" in config:
            self._agc.attack = config["agc_attack"]
        if "agc_release" in config:
            self._agc.release = config["agc_release"]
        
        if "peak_hold_enabled" in config:
            self._peak_hold_enabled = config["peak_hold_enabled"]
        if "peak_decay" in config:
            self.set_peak_decay(config["peak_decay"])
