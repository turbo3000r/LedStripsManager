"""FFT-based frequency band analyzer."""

import numpy as np
from typing import Optional
from scipy import signal


class FFTAnalyzer:
    """Analyzes audio frequency spectrum and splits into bands."""
    
    # Default frequency ranges for 4 bands (Hz)
    DEFAULT_BANDS = [
        (20, 150),     # Sub-bass / Bass
        (150, 500),    # Low-mid
        (500, 2000),   # Mid
        (2000, 20000), # High / Treble
    ]
    
    def __init__(self, 
                 sample_rate: int = 44100,
                 fft_size: int = 2048,
                 num_bands: int = 4,
                 smoothing: float = 0.2):
        """
        Initialize FFT analyzer.
        
        Args:
            sample_rate: Audio sample rate in Hz
            fft_size: FFT window size (power of 2 recommended)
            num_bands: Number of frequency bands to output
            smoothing: Smoothing factor (0-1)
        """
        self._sample_rate = sample_rate
        self._fft_size = fft_size
        self._smoothing = smoothing
        
        # Set up frequency bands
        self._bands = self._create_bands(num_bands)
        self._band_levels = [0.0] * len(self._bands)
        self._peak_levels = [0.0] * len(self._bands)
        self._peak_decay = 0.98
        
        # Precompute frequency bins
        self._freq_bins = np.fft.rfftfreq(fft_size, 1.0 / sample_rate)
        
        # Window function for better frequency resolution
        self._window = signal.windows.hann(fft_size)
    
    def _create_bands(self, num_bands: int) -> list[tuple[float, float]]:
        """Create logarithmically spaced frequency bands."""
        if num_bands == 4:
            return self.DEFAULT_BANDS.copy()
        
        # Create logarithmically spaced bands
        min_freq = 20
        max_freq = 20000
        
        log_min = np.log10(min_freq)
        log_max = np.log10(max_freq)
        
        edges = np.logspace(log_min, log_max, num_bands + 1)
        bands = []
        for i in range(num_bands):
            bands.append((edges[i], edges[i + 1]))
        
        return bands
    
    @property
    def num_bands(self) -> int:
        return len(self._bands)
    
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
    
    def set_bands(self, bands: list[tuple[float, float]]) -> None:
        """Set custom frequency bands."""
        self._bands = bands
        self._band_levels = [0.0] * len(bands)
        self._peak_levels = [0.0] * len(bands)
    
    def analyze(self, samples: np.ndarray) -> list[float]:
        """
        Analyze audio samples and return per-band levels (0-1).
        
        Args:
            samples: Audio samples (float32, -1 to 1)
            
        Returns:
            List of band levels normalized to 0-1
        """
        if len(samples) < self._fft_size:
            # Pad with zeros if not enough samples
            padded = np.zeros(self._fft_size, dtype=np.float32)
            padded[:len(samples)] = samples
            samples = padded
        else:
            # Use the most recent samples
            samples = samples[-self._fft_size:]
        
        # Apply window and compute FFT
        windowed = samples * self._window
        spectrum = np.abs(np.fft.rfft(windowed))
        
        # Normalize spectrum
        spectrum = spectrum / (self._fft_size / 2)
        
        # Calculate energy in each band
        new_levels = []
        for low_freq, high_freq in self._bands:
            # Find bins in this frequency range
            mask = (self._freq_bins >= low_freq) & (self._freq_bins < high_freq)
            if np.any(mask):
                # Use mean energy in the band
                energy = np.mean(spectrum[mask])
                # Apply log scaling for perceptual linearity
                if energy > 0:
                    db = 20 * np.log10(energy + 1e-10)
                    # Normalize: -60dB to 0dB -> 0 to 1
                    normalized = (db + 60) / 60
                    normalized = max(0.0, min(1.0, normalized))
                else:
                    normalized = 0.0
            else:
                normalized = 0.0
            new_levels.append(normalized)
        
        # Apply smoothing and update peaks
        for i in range(len(self._bands)):
            # Smoothing
            self._band_levels[i] = (
                self._smoothing * self._band_levels[i] +
                (1 - self._smoothing) * new_levels[i]
            )
            
            # Peak tracking
            if new_levels[i] > self._peak_levels[i]:
                self._peak_levels[i] = new_levels[i]
            else:
                self._peak_levels[i] *= self._peak_decay
        
        return self._band_levels.copy()
    
    def get_levels(self) -> list[float]:
        """Get current band levels."""
        return self._band_levels.copy()
    
    def get_peaks(self) -> list[float]:
        """Get current peak levels."""
        return self._peak_levels.copy()
    
    def reset(self) -> None:
        """Reset analyzer state."""
        self._band_levels = [0.0] * len(self._bands)
        self._peak_levels = [0.0] * len(self._bands)
