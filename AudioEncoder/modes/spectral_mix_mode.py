"""Spectral mix visualization mode."""

from typing import Any
import numpy as np

from .base import Mode, ModeOutput, ModeRegistry
from analysis.fft import FFTAnalyzer


@ModeRegistry.register
class SpectralMixMode(Mode):
    """FFT-based mode that mixes bands into non-uniform channel brightness."""

    MODE_ID = "spectral_mix"
    MODE_NAME = "Spectral Mix"

    def __init__(self):
        super().__init__()
        self._sample_rate = 44100
        self._smoothing = 0.25
        self._analyzer = FFTAnalyzer(sample_rate=self._sample_rate, num_bands=8, smoothing=self._smoothing)

    @property
    def smoothing(self) -> float:
        return self._smoothing

    @smoothing.setter
    def smoothing(self, value: float) -> None:
        self._smoothing = max(0.0, min(1.0, value))
        self._analyzer.smoothing = self._smoothing

    def process(self, samples: np.ndarray, sample_rate: int) -> ModeOutput:
        """Process audio and output mixed spectral bands."""
        if sample_rate != self._sample_rate:
            self._sample_rate = sample_rate
            self._analyzer = FFTAnalyzer(sample_rate=sample_rate, num_bands=8, smoothing=self._smoothing)

        bands = self._analyzer.analyze(samples)
        bands = [min(1.0, b * self._gain) for b in bands]

        def avg(items: list[float]) -> float:
            return sum(items) / len(items) if items else 0.0

        # 4ch: Weighted mixes for distinct channel responses
        ch0 = bands[0] * 1.2 + bands[1] * 0.4
        ch1 = bands[2] * 1.1 + bands[3] * 0.7
        ch2 = bands[4] * 1.0 + bands[5] * 0.8
        ch3 = bands[6] * 1.1 + bands[7] * 0.9
        values_4ch = [min(1.0, ch) for ch in [ch0, ch1, ch2, ch3]]

        # 2ch: Low vs high frequency energy
        low = avg(bands[:4])
        high = avg(bands[4:])
        values_2ch = [min(1.0, low), min(1.0, high)]

        # RGB: Bass, mids, treble
        red = avg(bands[:2])
        green = avg(bands[2:5])
        blue = avg(bands[5:])
        values_rgb = [min(1.0, red), min(1.0, green), min(1.0, blue)]

        return ModeOutput(values_4ch=values_4ch, values_2ch=values_2ch, values_rgb=values_rgb)

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
