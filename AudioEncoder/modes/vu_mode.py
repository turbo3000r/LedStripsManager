"""VU meter visualization mode."""

from typing import Any
import numpy as np

from .base import Mode, ModeOutput, ModeRegistry
from analysis.rms import RMSAnalyzer


@ModeRegistry.register
class VUMode(Mode):
    """VU/RMS meter mode - all channels follow audio level."""
    
    MODE_ID = "vu"
    MODE_NAME = "VU Meter"
    
    def __init__(self):
        super().__init__()
        self._analyzer = RMSAnalyzer(smoothing=0.3)
        self._smoothing = 0.3
    
    @property
    def smoothing(self) -> float:
        return self._smoothing
    
    @smoothing.setter
    def smoothing(self, value: float) -> None:
        self._smoothing = max(0.0, min(1.0, value))
        self._analyzer.smoothing = value
    
    def process(self, samples: np.ndarray, sample_rate: int) -> ModeOutput:
        """Process audio and output VU level to all channels."""
        level = self._analyzer.analyze(samples)
        
        # Apply gain
        level = min(1.0, level * self._gain)
        
        output = ModeOutput()
        
        # 4ch: All channels same level (G, Y, B, R)
        output.values_4ch = [level, level, level, level]
        
        # 2ch: Both channels same level
        output.values_2ch = [level, level]
        
        # RGB: All channels same level
        output.values_rgb = [level, level, level]
        
        return output
    
    def get_parameters(self) -> dict[str, Any]:
        return {
            "gain": self._gain,
            "smoothing": self._smoothing,
        }
    
    def set_parameters(self, params: dict[str, Any]) -> None:
        if "gain" in params:
            self.gain = params["gain"]
        if "smoothing" in params:
            self.smoothing = params["smoothing"]
    
    def reset(self) -> None:
        self._analyzer.reset()
