"""Beat strobe visualization mode."""

from typing import Any
import numpy as np

from .base import Mode, ModeOutput, ModeRegistry
from analysis.beat import BeatDetector


@ModeRegistry.register
class BeatMode(Mode):
    """Beat strobe mode - flash on detected beats."""
    
    MODE_ID = "beat"
    MODE_NAME = "Beat Strobe"
    
    def __init__(self):
        super().__init__()
        self._detector = BeatDetector(sensitivity=1.5, decay=0.9)
        self._sensitivity = 1.5
        self._decay = 0.9
        self._base_brightness = 0.05  # Dim when no beat
        
        # Pattern cycling for visual interest
        self._pattern_index = 0
        self._patterns_4ch = [
            [1.0, 0.0, 0.0, 0.0],  # Green only
            [0.0, 1.0, 0.0, 0.0],  # Yellow only
            [0.0, 0.0, 1.0, 0.0],  # Blue only
            [0.0, 0.0, 0.0, 1.0],  # Red only
            [1.0, 1.0, 1.0, 1.0],  # All channels
        ]
    
    @property
    def sensitivity(self) -> float:
        return self._sensitivity
    
    @sensitivity.setter
    def sensitivity(self, value: float) -> None:
        self._sensitivity = max(0.5, min(5.0, value))
        self._detector.sensitivity = value
    
    @property
    def decay(self) -> float:
        return self._decay
    
    @decay.setter
    def decay(self, value: float) -> None:
        self._decay = max(0.0, min(1.0, value))
        self._detector.decay = value
    
    def process(self, samples: np.ndarray, sample_rate: int) -> ModeOutput:
        """Process audio and output beat pulses."""
        intensity = self._detector.analyze(samples)
        
        # Apply gain
        intensity = min(1.0, intensity * self._gain)
        
        # Cycle pattern on beat
        if self._detector.is_beat():
            self._pattern_index = (self._pattern_index + 1) % len(self._patterns_4ch)
        
        pattern = self._patterns_4ch[self._pattern_index]
        
        output = ModeOutput()
        
        # 4ch: Apply pattern with intensity
        output.values_4ch = [
            self._base_brightness + intensity * p for p in pattern
        ]
        output.values_4ch = [min(1.0, v) for v in output.values_4ch]
        
        # 2ch: Alternate between channels on beats
        if self._pattern_index % 2 == 0:
            output.values_2ch = [
                self._base_brightness + intensity,
                self._base_brightness
            ]
        else:
            output.values_2ch = [
                self._base_brightness,
                self._base_brightness + intensity
            ]
        output.values_2ch = [min(1.0, v) for v in output.values_2ch]
        
        # RGB: All flash together
        output.values_rgb = [
            self._base_brightness + intensity,
            self._base_brightness + intensity,
            self._base_brightness + intensity
        ]
        output.values_rgb = [min(1.0, v) for v in output.values_rgb]
        
        return output
    
    def get_parameters(self) -> dict[str, Any]:
        return {
            "gain": self._gain,
            "sensitivity": self._sensitivity,
            "decay": self._decay,
            "base_brightness": self._base_brightness,
        }
    
    def set_parameters(self, params: dict[str, Any]) -> None:
        if "gain" in params:
            self.gain = params["gain"]
        if "sensitivity" in params:
            self.sensitivity = params["sensitivity"]
        if "decay" in params:
            self.decay = params["decay"]
        if "base_brightness" in params:
            self._base_brightness = max(0.0, min(0.5, params["base_brightness"]))
    
    def reset(self) -> None:
        self._detector.reset()
        self._pattern_index = 0
