"""Pulse sweep visualization mode."""

from typing import Any
import numpy as np

from .base import Mode, ModeOutput, ModeRegistry
from analysis.rms import RMSAnalyzer


@ModeRegistry.register
class PulseSweepMode(Mode):
    """A moving pulse that sweeps across channels based on audio level."""

    MODE_ID = "pulse_sweep"
    MODE_NAME = "Pulse Sweep"

    def __init__(self):
        super().__init__()
        self._analyzer = RMSAnalyzer(smoothing=0.25)
        self._phase = 0.0
        self._base_speed = 0.35  # cycles per second
        self._speed_gain = 1.2
        self._width = 0.9
        self._base_floor = 0.02

    def _pulse_values(self, num_channels: int, intensity: float, phase_offset: float) -> list[float]:
        if num_channels <= 1:
            return [min(1.0, self._base_floor + intensity)]

        phase = (self._phase + phase_offset) % 1.0
        pos = phase * (num_channels - 1)
        values = []
        width = max(0.2, self._width)
        for i in range(num_channels):
            dist = abs(i - pos)
            strength = max(0.0, 1.0 - (dist / width))
            v = self._base_floor + intensity * strength
            values.append(min(1.0, v))
        return values

    def process(self, samples: np.ndarray, sample_rate: int) -> ModeOutput:
        """Process audio and output sweeping pulse."""
        if sample_rate <= 0:
            return ModeOutput()

        level = self._analyzer.analyze(samples)
        intensity = min(1.0, level * self._gain)

        frame_time = len(samples) / sample_rate if len(samples) else 0.0
        speed = self._base_speed + self._speed_gain * intensity
        self._phase = (self._phase + speed * frame_time) % 1.0

        output = ModeOutput()
        output.values_4ch = self._pulse_values(4, intensity, 0.0)
        output.values_2ch = self._pulse_values(2, intensity, 0.25)
        output.values_rgb = self._pulse_values(3, intensity, 0.5)
        return output

    def get_parameters(self) -> dict[str, Any]:
        return {
            "gain": self._gain,
            "smoothing": self._analyzer.smoothing,
            "base_speed": self._base_speed,
            "speed_gain": self._speed_gain,
            "width": self._width,
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
        if "width" in params:
            self._width = max(0.2, min(2.0, float(params["width"])))
        if "base_floor" in params:
            self._base_floor = max(0.0, min(0.3, float(params["base_floor"])))

    def reset(self) -> None:
        self._analyzer.reset()
        self._phase = 0.0
