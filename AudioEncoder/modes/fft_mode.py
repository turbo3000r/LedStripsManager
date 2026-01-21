"""FFT frequency bands visualization mode."""

from typing import Any
import numpy as np

from .base import Mode, ModeOutput, ModeRegistry
from analysis.fft import FFTAnalyzer


@ModeRegistry.register
class FFTMode(Mode):
    """FFT bands mode - channels represent frequency bands."""
    
    MODE_ID = "fft"
    MODE_NAME = "FFT Bands"
    
    def __init__(self):
        super().__init__()
        self._analyzer = FFTAnalyzer(num_bands=4, smoothing=0.2)
        self._smoothing = 0.2
        self._sample_rate = 44100
    
    @property
    def smoothing(self) -> float:
        return self._smoothing
    
    @smoothing.setter
    def smoothing(self, value: float) -> None:
        self._smoothing = max(0.0, min(1.0, value))
        self._analyzer.smoothing = value
    
    def process(self, samples: np.ndarray, sample_rate: int) -> ModeOutput:
        """Process audio and output FFT bands to channels."""
        # Update sample rate if changed
        if sample_rate != self._sample_rate:
            self._sample_rate = sample_rate
            self._analyzer = FFTAnalyzer(
                sample_rate=sample_rate,
                num_bands=4,
                smoothing=self._smoothing
            )
        
        bands = self._analyzer.analyze(samples)
        
        # Apply gain
        bands = [min(1.0, b * self._gain) for b in bands]
        
        output = ModeOutput()
        
        # 4ch: Map bands directly to channels (G=bass, Y=lowmid, B=mid, R=treble)
        # Adjust for 4ch_v1 order: Green, Yellow, Blue, Red
        if len(bands) >= 4:
            output.values_4ch = [bands[0], bands[1], bands[2], bands[3]]
        else:
            # Pad with zeros if fewer bands
            output.values_4ch = bands + [0.0] * (4 - len(bands))
        
        # 2ch: Combine bands
        # Channel 0 (Red+Yellow): Low frequencies (bass + low-mid)
        # Channel 1 (Green+Blue): High frequencies (mid + treble)
        low = (bands[0] + bands[1]) / 2 if len(bands) >= 2 else bands[0] if bands else 0.0
        high = (bands[2] + bands[3]) / 2 if len(bands) >= 4 else 0.0
        output.values_2ch = [low, high]
        
        # RGB: Map bass to R, mid to G, treble to B
        output.values_rgb = [
            bands[0] if len(bands) > 0 else 0.0,  # Red = Bass
            bands[2] if len(bands) > 2 else 0.0,  # Green = Mid
            bands[3] if len(bands) > 3 else 0.0,  # Blue = Treble
        ]
        
        return output
    
    def get_parameters(self) -> dict[str, Any]:
        return {
            "gain": self._gain,
            "smoothing": self._smoothing,
            "num_bands": self._analyzer.num_bands,
        }
    
    def set_parameters(self, params: dict[str, Any]) -> None:
        if "gain" in params:
            self.gain = params["gain"]
        if "smoothing" in params:
            self.smoothing = params["smoothing"]
    
    def reset(self) -> None:
        self._analyzer.reset()
