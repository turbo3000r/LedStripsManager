# Audio capture module
from .base import AudioProvider, AudioFrame
from .mic import MicrophoneProvider
from .loopback import LoopbackProvider

__all__ = ["AudioProvider", "AudioFrame", "MicrophoneProvider", "LoopbackProvider"]
