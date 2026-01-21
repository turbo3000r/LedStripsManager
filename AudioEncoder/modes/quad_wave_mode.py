"""Quad wave visualization mode."""

from typing import Any
import numpy as np

from .base import Mode, ModeOutput, ModeRegistry
from analysis.rms import RMSAnalyzer


@ModeRegistry.register
class QuadWaveMode(Mode):
    """Phase-shifted wave across channels driven by RMS level."""

    MODE_ID = "quad_wave"
    MODE_NAME = "Quad Wave"

    def __init__(self):
        super().__init__()
        self._analyzer = RMSAnalyzer(smoothing=0.2)
        self._phase = 0.0
        self._base_speed = 0.3
        self._speed_gain = 1.0
        self._depth = 1.0
        self._base_floor = 0.03
        self._offsets_4ch = [0.0, 0.25, 0.5, 0.75]
        self._offsets_2ch = [0.0, 0.5]
        self._offsets_rgb = [0.0, 1 / 3, 2 / 3]

    def _wave_values(self, num_channels: int, intensity: float, offsets: list[float]) -> list[float]:
        values = []
        for i in range(num_channels):
            offset = offsets[i] if i < len(offsets) else 0.0
            wave = 0.5 + 0.5 * np.sin(2 * np.pi * (self._phase + offset))
            v = self._base_floor + intensity * self._depth * wave
            values.append(max(0.0, min(1.0, v)))
        return values

    def process(self, samples: np.ndarray, sample_rate: int) -> ModeOutput:
        """Process audio and output phase-shifted wave pattern."""
        if sample_rate <= 0:
            return ModeOutput()

        level = self._analyzer.analyze(samples)
        intensity = min(1.0, level * self._gain)

        frame_time = len(samples) / sample_rate if len(samples) else 0.0
        speed = self._base_speed + self._speed_gain * intensity
        self._phase = (self._phase + speed * frame_time) % 1.0

        output = ModeOutput()
        output.values_4ch = self._wave_values(4, intensity, self._offsets_4ch)
        output.values_2ch = self._wave_values(2, intensity, self._offsets_2ch)
        output.values_rgb = self._wave_values(3, intensity, self._offsets_rgb)
        return output

    def get_parameters(self) -> dict[str, Any]:
        return {
            "gain": self._gain,
            "smoothing": self._analyzer.smoothing,
            "base_speed": self._base_speed,
            "speed_gain": self._speed_gain,
            "depth": self._depth,
            "base_floor": self._base_floor,
        }

    def set_parameters(self, params: dict[str, Any]) -> None:
        if "gain" in params:
            self.gain = params["gain"]
        if "smoothing" in params:
            self._analyzer.smoothing = params["smoothing"]
        if "base_speed" in params:
            self._base_speed = max(0.05, min(2.0, float(params["base_speed"])))
        if "speed_gain" in params:
            self._speed_gain = max(0.0, min(3.0, float(params["speed_gain"])))
        if "depth" in params:
            self._depth = max(0.0, min(1.5, float(params["depth"])))
        if "base_floor" in params:
            self._base_floor = max(0.0, min(0.3, float(params["base_floor"])))

    def reset(self) -> None:
        self._analyzer.reset()
        self._phase = 0.0
