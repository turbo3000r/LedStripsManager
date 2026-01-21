"""Random peaks visualization mode."""

from typing import Any
import numpy as np

from .base import Mode, ModeOutput, ModeRegistry
from analysis.rms import RMSAnalyzer


@ModeRegistry.register
class RandomPeaksMode(Mode):
    """Randomly flash channels on loud peaks."""

    MODE_ID = "random_peaks"
    MODE_NAME = "Random Peaks"

    def __init__(self):
        super().__init__()
        self._analyzer = RMSAnalyzer(smoothing=0.2)
        self._threshold = 0.6
        self._decay = 0.85
        self._hold_time = 0.12
        self._min_channels = 1
        self._max_channels = 3
        self._min_brightness = 0.15
        self._max_brightness = 1.0
        self._rng = np.random.default_rng()
        self._hold_remaining = 0.0
        self._values_4ch = [0.0, 0.0, 0.0, 0.0]
        self._values_2ch = [0.0, 0.0]
        self._values_rgb = [0.0, 0.0, 0.0]

    def _random_values(self, num_channels: int, intensity: float) -> list[float]:
        min_channels = max(1, min(self._min_channels, num_channels))
        max_channels = max(min_channels, min(self._max_channels, num_channels))
        count = int(self._rng.integers(min_channels, max_channels + 1))
        indices = self._rng.choice(num_channels, size=count, replace=False)

        values = [0.0] * num_channels
        for idx in indices:
            value = self._rng.uniform(self._min_brightness, self._max_brightness)
            values[idx] = min(1.0, value * intensity)
        return values

    def process(self, samples: np.ndarray, sample_rate: int) -> ModeOutput:
        """Trigger random peaks on loud audio."""
        if len(samples) == 0 or sample_rate <= 0:
            return ModeOutput(
                values_4ch=self._values_4ch,
                values_2ch=self._values_2ch,
                values_rgb=self._values_rgb,
            )

        frame_time = len(samples) / sample_rate
        peak = float(np.max(np.abs(samples))) if len(samples) else 0.0
        _ = self._analyzer.analyze(samples)

        intensity = min(1.0, peak * self._gain)

        if intensity >= self._threshold:
            self._hold_remaining = self._hold_time
            self._values_4ch = self._random_values(4, intensity)
            self._values_2ch = self._random_values(2, intensity)
            self._values_rgb = self._random_values(3, intensity)
        else:
            self._hold_remaining = max(0.0, self._hold_remaining - frame_time)

        decay = self._decay if self._hold_remaining <= 0.0 else max(self._decay, 0.95)
        self._values_4ch = [v * decay for v in self._values_4ch]
        self._values_2ch = [v * decay for v in self._values_2ch]
        self._values_rgb = [v * decay for v in self._values_rgb]

        return ModeOutput(
            values_4ch=self._values_4ch,
            values_2ch=self._values_2ch,
            values_rgb=self._values_rgb,
        )

    def get_parameters(self) -> dict[str, Any]:
        return {
            "gain": self._gain,
            "smoothing": self._analyzer.smoothing,
            "threshold": self._threshold,
            "decay": self._decay,
            "hold_time": self._hold_time,
            "min_channels": self._min_channels,
            "max_channels": self._max_channels,
            "min_brightness": self._min_brightness,
            "max_brightness": self._max_brightness,
        }

    def set_parameters(self, params: dict[str, Any]) -> None:
        if "gain" in params:
            self.gain = params["gain"]
        if "smoothing" in params:
            self._analyzer.smoothing = params["smoothing"]
        if "threshold" in params:
            self._threshold = max(0.05, min(1.0, float(params["threshold"])))
        if "decay" in params:
            self._decay = max(0.5, min(0.99, float(params["decay"])))
        if "hold_time" in params:
            self._hold_time = max(0.02, min(1.0, float(params["hold_time"])))
        if "min_channels" in params:
            self._min_channels = max(1, int(params["min_channels"]))
        if "max_channels" in params:
            self._max_channels = max(1, int(params["max_channels"]))
        if "min_brightness" in params:
            self._min_brightness = max(0.0, min(1.0, float(params["min_brightness"])))
        if "max_brightness" in params:
            self._max_brightness = max(0.0, min(1.0, float(params["max_brightness"])))

    def reset(self) -> None:
        self._analyzer.reset()
        self._hold_remaining = 0.0
        self._values_4ch = [0.0, 0.0, 0.0, 0.0]
        self._values_2ch = [0.0, 0.0]
        self._values_rgb = [0.0, 0.0, 0.0]
