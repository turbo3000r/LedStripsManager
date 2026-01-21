"""VU mix visualization mode with per-channel gains."""

from typing import Any
import numpy as np

from .base import Mode, ModeOutput, ModeRegistry
from analysis.rms import RMSAnalyzer


@ModeRegistry.register
class VUMixMode(Mode):
    """VU mode with different gains per channel."""

    MODE_ID = "vu_mix"
    MODE_NAME = "VU Mix"

    def __init__(self):
        super().__init__()
        self._analyzer = RMSAnalyzer(smoothing=0.25)
        self._base_floor = 0.02
        self._weights_4ch = [1.0, 0.85, 0.7, 0.55]
        self._offsets_4ch = [0.0, 0.0, 0.0, 0.0]
        self._weights_2ch = [1.0, 0.65]
        self._offsets_2ch = [0.0, 0.0]
        self._weights_rgb = [0.9, 0.7, 0.5]
        self._offsets_rgb = [0.0, 0.0, 0.0]

    def _apply_mix(self, level: float, weights: list[float], offsets: list[float]) -> list[float]:
        values = []
        for i, weight in enumerate(weights):
            offset = offsets[i] if i < len(offsets) else 0.0
            v = self._base_floor + level * weight + offset
            values.append(max(0.0, min(1.0, v)))
        return values

    def process(self, samples: np.ndarray, sample_rate: int) -> ModeOutput:
        """Process audio and output per-channel VU mix."""
        level = self._analyzer.analyze(samples)
        level = min(1.0, level * self._gain)

        output = ModeOutput()
        output.values_4ch = self._apply_mix(level, self._weights_4ch, self._offsets_4ch)
        output.values_2ch = self._apply_mix(level, self._weights_2ch, self._offsets_2ch)
        output.values_rgb = self._apply_mix(level, self._weights_rgb, self._offsets_rgb)
        return output

    def get_parameters(self) -> dict[str, Any]:
        return {
            "gain": self._gain,
            "smoothing": self._analyzer.smoothing,
            "base_floor": self._base_floor,
            "weights_4ch": self._weights_4ch,
            "offsets_4ch": self._offsets_4ch,
            "weights_2ch": self._weights_2ch,
            "offsets_2ch": self._offsets_2ch,
            "weights_rgb": self._weights_rgb,
            "offsets_rgb": self._offsets_rgb,
        }

    def set_parameters(self, params: dict[str, Any]) -> None:
        if "gain" in params:
            self.gain = params["gain"]
        if "smoothing" in params:
            self._analyzer.smoothing = params["smoothing"]
        if "base_floor" in params:
            self._base_floor = max(0.0, min(0.3, float(params["base_floor"])))
        if "weights_4ch" in params and isinstance(params["weights_4ch"], list):
            self._weights_4ch = [float(v) for v in params["weights_4ch"]][:4]
        if "offsets_4ch" in params and isinstance(params["offsets_4ch"], list):
            self._offsets_4ch = [float(v) for v in params["offsets_4ch"]][:4]
        if "weights_2ch" in params and isinstance(params["weights_2ch"], list):
            self._weights_2ch = [float(v) for v in params["weights_2ch"]][:2]
        if "offsets_2ch" in params and isinstance(params["offsets_2ch"], list):
            self._offsets_2ch = [float(v) for v in params["offsets_2ch"]][:2]
        if "weights_rgb" in params and isinstance(params["weights_rgb"], list):
            self._weights_rgb = [float(v) for v in params["weights_rgb"]][:3]
        if "offsets_rgb" in params and isinstance(params["offsets_rgb"], list):
            self._offsets_rgb = [float(v) for v in params["offsets_rgb"]][:3]

    def reset(self) -> None:
        self._analyzer.reset()
