"""Windows WASAPI loopback audio capture for system audio."""

import time
import threading
import logging
from typing import Optional
import numpy as np

try:
    import pyaudio
except ImportError:
    pyaudio = None

from .base import AudioProvider

logger = logging.getLogger(__name__)


class LoopbackProvider(AudioProvider):
    """Capture system audio via Windows WASAPI loopback.
    
    This captures the audio output of the system (what you hear through speakers).
    Only works on Windows with WASAPI support.
    """
    
    def __init__(self):
        super().__init__()
        self._pa: Optional[pyaudio.PyAudio] = None
        self._stream = None
        self._sample_rate = 44100
        self._chunk_size = 1024
        self._thread: Optional[threading.Thread] = None
    
    def list_devices(self) -> list[tuple[int, str]]:
        """
        Return a single entry for system audio (default output) to avoid clutter.
        For WASAPI loopback, we need to find loopback-capable input devices.
        """
        if pyaudio is None:
            print("[DEBUG] Loopback: PyAudio not available")
            return []
        
        try:
            pa = pyaudio.PyAudio()
            
            # Find WASAPI host API
            wasapi_api_index = None
            for i in range(pa.get_host_api_count()):
                try:
                    api_info = pa.get_host_api_info_by_index(i)
                    if "WASAPI" in api_info.get("name", ""):
                        wasapi_api_index = i
                        break
                except Exception:
                    continue
            
            if wasapi_api_index is None:
                print("[DEBUG] Loopback: WASAPI not found")
                pa.terminate()
                return []
            
            # Look for loopback input devices
            # WASAPI loopback devices appear as input devices with names containing the output device name
            # or as special loopback devices
            api_info = pa.get_host_api_info_by_index(wasapi_api_index)
            default_output_idx = api_info.get("defaultOutputDevice", -1)
            
            if default_output_idx >= 0:
                output_info = pa.get_device_info_by_index(default_output_idx)
                output_name = output_info.get("name", "")
                print(f"[DEBUG] Loopback: Default output device: {output_name} (index {default_output_idx})")
                
                # Search for a loopback input device that matches this output
                # Loopback devices often have "Stereo Mix" or similar in the name, or match the output name
                for i in range(pa.get_device_count()):
                    try:
                        dev_info = pa.get_device_info_by_index(i)
                        if dev_info.get("hostApi") != wasapi_api_index:
                            continue
                        
                        # Check if it's an input device
                        if dev_info.get("maxInputChannels", 0) > 0:
                            dev_name = dev_info.get("name", "")
                            # Check if it looks like a loopback device
                            # Loopback devices often contain output device name or "Stereo Mix", "What U Hear", etc.
                            if (output_name.lower() in dev_name.lower() or 
                                "stereo mix" in dev_name.lower() or 
                                "what u hear" in dev_name.lower() or
                                "loopback" in dev_name.lower()):
                                print(f"[DEBUG] Loopback: Found loopback input device {i}: {dev_name}")
                                pa.terminate()
                                return [(i, "System Audio (Default Output)")]
                    except Exception:
                        continue
                
                # If no specific loopback device found, return the output device index
                # We'll try to use it as input (may not work, but worth trying)
                print(f"[DEBUG] Loopback: No specific loopback device found, will try output device {default_output_idx}")
                pa.terminate()
                return [(default_output_idx, "System Audio (Default Output)")]
            
            pa.terminate()
        except Exception as e:
            print(f"[DEBUG] Loopback: Error listing devices: {e}")
            import traceback
            traceback.print_exc()
        
        return []
    
    def start(self, device_index: Optional[int] = None,
              sample_rate: int = 44100, chunk_size: int = 1024) -> bool:
        """Start capturing system audio via WASAPI loopback using PyAudio."""
        if pyaudio is None:
            self._error = "PyAudio not installed"
            print("[DEBUG] Loopback: PyAudio not installed")
            return False
        
        if self._running:
            print("[DEBUG] Loopback: Already running")
            return True
        
        self._sample_rate = sample_rate
        self._chunk_size = chunk_size
        self._start_time = time.time()
        self._error = None
        self._frame_count = 0
        self._last_debug_time = time.time()
        
        try:
            self._pa = pyaudio.PyAudio()
            
            # Find WASAPI host API
            wasapi_api_index = None
            for i in range(self._pa.get_host_api_count()):
                try:
                    api_info = self._pa.get_host_api_info_by_index(i)
                    if "WASAPI" in api_info.get("name", ""):
                        wasapi_api_index = i
                        break
                except Exception:
                    continue
            
            if wasapi_api_index is None:
                self._error = "WASAPI not found"
                print("[DEBUG] Loopback: WASAPI host API not found")
                self._pa.terminate()
                return False
            
            # If no device specified, get default output from WASAPI
            if device_index is None:
                api_info = self._pa.get_host_api_info_by_index(wasapi_api_index)
                device_index = api_info.get("defaultOutputDevice", -1)
                print(f"[DEBUG] Loopback: Using default WASAPI output device: {device_index}")
            
            if device_index < 0:
                self._error = "No output device found"
                print("[DEBUG] Loopback: No device index available")
                self._pa.terminate()
                return False
            
            # Get device info
            dev_info = self._pa.get_device_info_by_index(device_index)
            dev_name = dev_info.get("name", "")
            max_input = dev_info.get("maxInputChannels", 0)
            max_output = dev_info.get("maxOutputChannels", 0)
            
            print(f"[DEBUG] Loopback: Device {device_index}: {dev_name}")
            print(f"[DEBUG] Loopback: maxInputChannels: {max_input}, maxOutputChannels: {max_output}")
            
            # Check if this is an input device (loopback device) or output device
            if max_input > 0:
                # This is a loopback input device - use it normally
                channels = min(2, max_input)
                sr = int(dev_info.get("defaultSampleRate", sample_rate)) or sample_rate
                print(f"[DEBUG] Loopback: Using loopback input device with {channels} channels, {sr}Hz")
            elif max_output > 0:
                # This is an output device - PyAudio can't open it as input directly
                # We need to find the corresponding loopback input device
                print(f"[DEBUG] Loopback: Device is output-only, searching for loopback input device...")
                
                # Search for a loopback input device
                loopback_device = None
                for i in range(self._pa.get_device_count()):
                    try:
                        check_info = self._pa.get_device_info_by_index(i)
                        if check_info.get("hostApi") != wasapi_api_index:
                            continue
                        if check_info.get("maxInputChannels", 0) > 0:
                            check_name = check_info.get("name", "")
                            # Check if it matches the output device or is a known loopback device
                            if (dev_name.lower() in check_name.lower() or 
                                "stereo mix" in check_name.lower() or 
                                "what u hear" in check_name.lower() or
                                "loopback" in check_name.lower()):
                                loopback_device = i
                                dev_info = check_info
                                dev_name = check_name
                                max_input = check_info.get("maxInputChannels", 0)
                                print(f"[DEBUG] Loopback: Found loopback input device {i}: {check_name}")
                                break
                    except Exception:
                        continue
                
                if loopback_device is None:
                    error_msg = (
                        "No loopback input device found (Stereo Mix is missing/disabled).\n"
                        "Since your hardware doesn't support Stereo Mix, you must install a virtual cable:\n"
                        "1. Download & Install VB-Audio Virtual Cable: https://vb-audio.com/Cable/\n"
                        "2. Restart your computer\n"
                        "3. In AudioEncoder, select Source: 'Microphone' and Device: 'CABLE Output'\n"
                        "4. Route your music player to 'CABLE Input' in Windows Sound Settings"
                    )
                    self._error = error_msg
                    print(f"[DEBUG] Loopback: ERROR - {error_msg}")
                    self._pa.terminate()
                    return False
                
                device_index = loopback_device
                channels = min(2, max_input)
                sr = int(dev_info.get("defaultSampleRate", sample_rate)) or sample_rate
                print(f"[DEBUG] Loopback: Using loopback device {device_index} with {channels} channels, {sr}Hz")
            else:
                self._error = "Device has no input or output channels"
                print(f"[DEBUG] Loopback: ERROR - Device has no channels")
                self._pa.terminate()
                return False
            
            print(f"[DEBUG] Loopback: Opening stream with device={device_index}, channels={channels}, samplerate={sr}")
            
            # Try to open with WASAPI loopback flag first
            # This allows capturing output directly without needing Stereo Mix
            try:
                print("[DEBUG] Loopback: Attempting WASAPI loopback mode (as_loopback=True)...")
                self._stream = self._pa.open(
                    format=pyaudio.paFloat32,
                    channels=channels,
                    rate=sr,
                    input=True,
                    input_device_index=device_index,
                    frames_per_buffer=chunk_size,
                    stream_callback=None,
                    as_loopback=True  # WASAPI loopback mode - captures output directly
                )
                print("[DEBUG] Loopback: Successfully opened with WASAPI loopback mode!")
            except TypeError:
                # as_loopback parameter not supported in this PyAudio version
                print("[DEBUG] Loopback: as_loopback parameter not supported, trying standard mode...")
                try:
                    self._stream = self._pa.open(
                        format=pyaudio.paFloat32,
                        channels=channels,
                        rate=sr,
                        input=True,
                        input_device_index=device_index,
                        frames_per_buffer=chunk_size,
                        stream_callback=None
                    )
                    print("[DEBUG] Loopback: Opened in standard mode (requires Stereo Mix to be enabled)")
                except Exception as e:
                    error_msg = (
                        f"Failed to open audio stream: {str(e)}\n\n"
                        "WASAPI loopback is not available in your PyAudio version.\n"
                        "Solutions:\n"
                        "1. Enable 'Stereo Mix' in Windows (if available)\n"
                        "2. Install VB-Audio Virtual Cable (recommended): https://vb-audio.com/Cable/\n"
                        "3. Use an updated PyAudio build with WASAPI loopback support"
                    )
                    self._error = error_msg
                    print(f"[DEBUG] Loopback: {error_msg}")
                    raise
            
            print("[DEBUG] Loopback: Stream opened, starting capture thread...")
            
            self._running = True
            self._thread = threading.Thread(target=self._capture_loop, daemon=True)
            self._thread.start()
            
            print("[DEBUG] Loopback: Stream started successfully")
            return True
            
        except Exception as e:
            self._error = str(e)
            print(f"[DEBUG] Loopback: Error starting stream: {e}")
            import traceback
            traceback.print_exc()
            if self._pa:
                try:
                    self._pa.terminate()
                except Exception:
                    pass
                self._pa = None
            return False
    
    def _capture_loop(self) -> None:
        """Background thread to capture audio via blocking read."""
        while self._running and self._stream:
            try:
                # Read audio data (blocking)
                data = self._stream.read(self._chunk_size, exception_on_overflow=False)
                audio = np.frombuffer(data, dtype=np.float32)
                
                # Reshape to (frames, channels) if stereo
                if len(audio) > self._chunk_size:
                    audio = audio.reshape(-1, 2)
                    # Convert to mono by averaging channels
                    audio = np.mean(audio, axis=1).astype(np.float32)
                else:
                    # Already mono or single channel
                    audio = audio.astype(np.float32)
                
                self._frame_count += 1
                current_time = time.time()
                
                # Print debug info every 2 seconds
                if current_time - self._last_debug_time >= 2.0:
                    peak = float(np.max(np.abs(audio)))
                    rms = float(np.sqrt(np.mean(audio ** 2)))
                    print(f"[DEBUG] Loopback callback: Frame #{self._frame_count}, peak={peak:.4f}, rms={rms:.4f}, len={len(audio)}")
                    self._last_debug_time = current_time
                
                timestamp = time.time() - self._start_time
                self._emit_frame(audio, self._sample_rate, timestamp)
                
            except Exception as e:
                if self._running:
                    self._error = str(e)
                    print(f"[DEBUG] Loopback: Error in capture loop: {e}")
                break
    
    def stop(self) -> None:
        """Stop capturing."""
        print(f"[DEBUG] Loopback: Stopping, received {self._frame_count} frames total")
        self._running = False
        
        if self._stream:
            try:
                self._stream.stop_stream()
                self._stream.close()
                print("[DEBUG] Loopback: Stream stopped and closed")
            except Exception as e:
                print(f"[DEBUG] Loopback: Error stopping stream: {e}")
            self._stream = None
        
        if self._pa:
            try:
                self._pa.terminate()
                print("[DEBUG] Loopback: PyAudio terminated")
            except Exception as e:
                print(f"[DEBUG] Loopback: Error terminating PyAudio: {e}")
            self._pa = None
        
        if self._thread:
            self._thread.join(timeout=2)
            self._thread = None