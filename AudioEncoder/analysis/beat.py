"""Beat and onset detection for strobe/pulse effects."""

import numpy as np
from typing import Optional
from collections import deque


class BeatDetector:
    """Detects beats and onsets in audio for strobe effects."""
    
    def __init__(self, 
                 sample_rate: int = 44100,
                 sensitivity: float = 1.5,
                 decay: float = 0.95,
                 history_size: int = 43):  # ~1 second at 60fps
        """
        Initialize beat detector.
        
        Args:
            sample_rate: Audio sample rate in Hz
            sensitivity: Beat detection threshold multiplier (higher = less sensitive)
            decay: Decay rate for beat intensity (0-1)
            history_size: Number of frames to keep in energy history
        """
        self._sample_rate = sample_rate
        self._sensitivity = sensitivity
        self._decay = decay
        
        # Energy history for adaptive threshold
        self._energy_history = deque(maxlen=history_size)
        
        # Current beat state
        self._beat_intensity: float = 0.0
        self._is_beat: bool = False
        self._last_energy: float = 0.0
        
        # Cooldown to prevent rapid re-triggering
        self._cooldown = 0
        self._cooldown_frames = 5  # Minimum frames between beats
    
    @property
    def sensitivity(self) -> float:
        return self._sensitivity
    
    @sensitivity.setter
    def sensitivity(self, value: float) -> None:
        self._sensitivity = max(0.5, min(5.0, value))
    
    @property
    def decay(self) -> float:
        return self._decay
    
    @decay.setter
    def decay(self, value: float) -> None:
        self._decay = max(0.0, min(1.0, value))
    
    def analyze(self, samples: np.ndarray) -> float:
        """
        Analyze samples for beat detection.
        
        Args:
            samples: Audio samples (float32, -1 to 1)
            
        Returns:
            Beat intensity (0-1), spikes on beats then decays
        """
        if len(samples) == 0:
            self._beat_intensity *= self._decay
            return self._beat_intensity
        
        # Calculate instantaneous energy
        energy = np.mean(samples ** 2)
        
        # Calculate energy difference (onset detection)
        energy_diff = max(0, energy - self._last_energy)
        self._last_energy = energy
        
        # Add to history
        self._energy_history.append(energy)
        
        # Calculate adaptive threshold
        if len(self._energy_history) > 10:
            avg_energy = np.mean(list(self._energy_history))
            std_energy = np.std(list(self._energy_history))
            threshold = avg_energy + self._sensitivity * std_energy
        else:
            threshold = 0.01  # Initial threshold
        
        # Beat detection
        self._is_beat = False
        if self._cooldown <= 0:
            # Check both energy and energy difference
            if energy > threshold and energy_diff > threshold * 0.5:
                self._is_beat = True
                self._beat_intensity = 1.0
                self._cooldown = self._cooldown_frames
        else:
            self._cooldown -= 1
        
        # Apply decay when no beat
        if not self._is_beat:
            self._beat_intensity *= self._decay
        
        return self._beat_intensity
    
    def is_beat(self) -> bool:
        """Check if a beat was detected in the last analysis."""
        return self._is_beat
    
    def get_intensity(self) -> float:
        """Get current beat intensity (with decay)."""
        return self._beat_intensity
    
    def reset(self) -> None:
        """Reset detector state."""
        self._energy_history.clear()
        self._beat_intensity = 0.0
        self._is_beat = False
        self._last_energy = 0.0
        self._cooldown = 0


class MultiChannelBeat:
    """Beat detector that outputs to multiple channels with different patterns."""
    
    def __init__(self, num_channels: int = 4, sensitivity: float = 1.5):
        self._detector = BeatDetector(sensitivity=sensitivity)
        self._num_channels = num_channels
        
        # Pattern: which channels react to beats and how
        # Default: alternating pattern
        self._patterns = [
            [1.0, 0.5, 0.0, 0.5],  # First beat pattern
            [0.5, 1.0, 0.5, 0.0],  # Second beat pattern
        ]
        self._current_pattern = 0
        self._base_level = 0.1  # Base brightness when no beat
    
    def set_patterns(self, patterns: list[list[float]]) -> None:
        """Set beat patterns. Each pattern is a list of channel multipliers."""
        self._patterns = patterns
    
    def analyze(self, samples: np.ndarray) -> list[float]:
        """
        Analyze samples and return per-channel brightness values (0-1).
        """
        intensity = self._detector.analyze(samples)
        
        # Switch pattern on beat
        if self._detector.is_beat():
            self._current_pattern = (self._current_pattern + 1) % len(self._patterns)
        
        pattern = self._patterns[self._current_pattern]
        
        # Apply pattern to intensity
        result = []
        for i in range(self._num_channels):
            if i < len(pattern):
                value = self._base_level + intensity * pattern[i]
            else:
                value = self._base_level + intensity
            result.append(max(0.0, min(1.0, value)))
        
        return result
    
    @property
    def sensitivity(self) -> float:
        return self._detector.sensitivity
    
    @sensitivity.setter
    def sensitivity(self, value: float) -> None:
        self._detector.sensitivity = value
    
    def reset(self) -> None:
        """Reset detector state."""
        self._detector.reset()
        self._current_pattern = 0
