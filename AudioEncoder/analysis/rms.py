"""RMS (Root Mean Square) audio level analyzer."""

import numpy as np
from typing import Optional


class RMSAnalyzer:
    """Analyzes audio RMS level for VU meter visualization."""
    
    def __init__(self, smoothing: float = 0.3):
        """
        Initialize RMS analyzer.
        
        Args:
            smoothing: Smoothing factor (0-1). Higher = smoother, slower response.
        """
        self._smoothing = smoothing
        self._current_level: float = 0.0
        self._peak_level: float = 0.0
        self._peak_decay: float = 0.995
    
    @property
    def smoothing(self) -> float:
        return self._smoothing
    
    @smoothing.setter
    def smoothing(self, value: float) -> None:
        self._smoothing = max(0.0, min(1.0, value))
    
    @property
    def peak_decay(self) -> float:
        return self._peak_decay
    
    @peak_decay.setter
    def peak_decay(self, value: float) -> None:
        self._peak_decay = max(0.0, min(1.0, value))
    
    def analyze(self, samples: np.ndarray) -> float:
        """
        Analyze audio samples and return smoothed RMS level (0-1).
        
        Args:
            samples: Audio samples (float32, -1 to 1)
            
        Returns:
            Smoothed RMS level normalized to 0-1 range
        """
        if len(samples) == 0:
            return self._current_level
        
        # Calculate RMS
        rms = np.sqrt(np.mean(samples ** 2))
        
        # Normalize (typical audio rarely exceeds 0.5 RMS)
        # Use a soft ceiling to avoid clipping
        normalized = min(1.0, rms * 2.0)
        
        # Apply smoothing (exponential moving average)
        self._current_level = (
            self._smoothing * self._current_level + 
            (1 - self._smoothing) * normalized
        )
        
        # Update peak with decay
        if normalized > self._peak_level:
            self._peak_level = normalized
        else:
            self._peak_level *= self._peak_decay
        
        return self._current_level
    
    def get_level(self) -> float:
        """Get current smoothed level."""
        return self._current_level
    
    def get_peak(self) -> float:
        """Get current peak level (with decay)."""
        return self._peak_level
    
    def reset(self) -> None:
        """Reset analyzer state."""
        self._current_level = 0.0
        self._peak_level = 0.0


class MultiChannelRMS:
    """RMS analyzer that outputs to multiple channels with different gains."""
    
    def __init__(self, num_channels: int = 4, smoothing: float = 0.3):
        self._analyzer = RMSAnalyzer(smoothing=smoothing)
        self._num_channels = num_channels
        self._channel_gains = [1.0] * num_channels
        self._channel_offsets = [0.0] * num_channels
    
    def set_channel_gain(self, channel: int, gain: float) -> None:
        """Set gain multiplier for a channel."""
        if 0 <= channel < self._num_channels:
            self._channel_gains[channel] = gain
    
    def set_channel_offset(self, channel: int, offset: float) -> None:
        """Set brightness offset for a channel (-1 to 1)."""
        if 0 <= channel < self._num_channels:
            self._channel_offsets[channel] = offset
    
    def analyze(self, samples: np.ndarray) -> list[float]:
        """
        Analyze samples and return per-channel brightness values (0-1).
        """
        level = self._analyzer.analyze(samples)
        
        result = []
        for i in range(self._num_channels):
            value = level * self._channel_gains[i] + self._channel_offsets[i]
            result.append(max(0.0, min(1.0, value)))
        
        return result
    
    @property
    def smoothing(self) -> float:
        return self._analyzer.smoothing
    
    @smoothing.setter
    def smoothing(self, value: float) -> None:
        self._analyzer.smoothing = value
    
    def reset(self) -> None:
        """Reset analyzer state."""
        self._analyzer.reset()
