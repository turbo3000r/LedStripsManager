"""Flet UI for AudioEncoder application."""

import flet as ft
import threading
import time
import asyncio
from typing import Optional
import numpy as np

from config.settings import get_settings_manager, AppSettings
from audio.base import AudioProvider, AudioFrame, RingBuffer
from audio.mic import MicrophoneProvider
from modes.pipeline import ModePipeline
from modes.base import ModeRegistry, ModeOutput
from modes.vu_mode import VUMode  # Register modes
from modes.fft_mode import FFTMode
from modes.beat_mode import BeatMode
from modes.random_peaks_mode import RandomPeaksMode
from modes.vu_mix_mode import VUMixMode
from modes.pulse_sweep_mode import PulseSweepMode
from modes.spectral_mix_mode import SpectralMixMode
from modes.quad_wave_mode import QuadWaveMode
from output.udp_sender import UdpSender, FrameBuilder


class AudioEncoderApp:
    """Main AudioEncoder Flet application."""
    
    def __init__(self, page: ft.Page):
        self.page = page
        self.settings_manager = get_settings_manager()
        self.settings = self.settings_manager.settings
        
        # Audio components
        self._audio_provider: Optional[AudioProvider] = None
        self._ring_buffer = RingBuffer(capacity=44100)  # 1 second buffer
        
        # Processing
        self._pipeline = ModePipeline()
        self._pipeline.set_mode_by_id("vu")  # Default mode
        
        # Output
        self._sender = UdpSender(
            host=self.settings.connection.host,
            port=self.settings.connection.port
        )
        self._sender.target_fps = self.settings.connection.fps
        self._frame_builder = FrameBuilder()
        
        # Engine state
        self._engine_running = False
        self._engine_thread: Optional[threading.Thread] = None
        self._current_output = ModeOutput()
        self._input_level: float = 0.0
        
        # UI update timer
        self._ui_update_running = False

        # Pending mode selection (applied via button)
        self._pending_mode_id = self.settings.mode.active_mode
        
        # Create UI components
        self._create_ui_components()

        # Stop background tasks on disconnect
        self.page.on_disconnect = self._on_page_disconnect
    
    def _create_ui_components(self) -> None:
        """Create all UI components."""
        # Connection section
        self.host_field = ft.TextField(
            label="Server Host",
            value=self.settings.connection.host,
            width=200,
            on_change=self._on_host_change
        )
        self.port_field = ft.TextField(
            label="Port",
            value=str(self.settings.connection.port),
            width=100,
            on_change=self._on_port_change
        )
        self.fps_field = ft.TextField(
            label="FPS",
            value=str(self.settings.connection.fps),
            width=80,
            on_change=self._on_fps_change
        )
        self.start_stop_btn = ft.ElevatedButton(
            "Start",
            icon=ft.Icons.PLAY_ARROW,
            on_click=self._on_start_stop,
            style=ft.ButtonStyle(
                bgcolor={ft.ControlState.DEFAULT: ft.Colors.GREEN_700}
            )
        )
        self.status_text = ft.Text("Stopped", size=14, color=ft.Colors.GREY_400)
        self.stats_text = ft.Text("", size=12, color=ft.Colors.GREY_500)
        
        # Audio source section (removed - only Microphone with Virtual Cable)
        # User should install VB-Audio Virtual Cable and select CABLE Output device

        self.device_dropdown = ft.Dropdown(
            label="Device",
            width=300
        )
        self.refresh_devices_btn = ft.IconButton(
            icon=ft.Icons.REFRESH,
            on_click=self._on_refresh_devices
        )
        self.apply_device_btn = ft.ElevatedButton(
            "Apply",
            icon=ft.Icons.CHECK,
            on_click=self._on_apply_device,
            style=ft.ButtonStyle(
                bgcolor={ft.ControlState.DEFAULT: ft.Colors.BLUE_700}
            )
        )
        self.input_level_bar = ft.ProgressBar(
            width=300,
            value=0,
            color=ft.Colors.GREEN_400,
            bgcolor=ft.Colors.GREY_800
        )
        
        # Mode section
        self.mode_dropdown = ft.Dropdown(
            label="Visualization Mode",
            width=200,
            options=[
                ft.dropdown.Option(mode_id, mode_name)
                for mode_id, mode_name in ModeRegistry.list_modes()
            ],
            value=self.settings.mode.active_mode
        )
        self.mode_dropdown.on_change = self._on_mode_change
        self.apply_mode_btn = ft.IconButton(
            icon=ft.Icons.CHECK,
            on_click=self._on_apply_mode,
            tooltip="Apply selected mode",
            style=ft.ButtonStyle(
                bgcolor={ft.ControlState.DEFAULT: ft.Colors.BLUE_700}
            )
        )
        self.gain_slider = ft.Slider(
            min=0.1,
            max=3.0,
            value=self.settings.mode.vu_gain,
            label="Gain: {value:.1f}",
            width=250,
            on_change=self._on_gain_change
        )
        self.smoothing_slider = ft.Slider(
            min=0.0,
            max=0.9,
            value=self.settings.mode.vu_smoothing,
            label="Smoothing: {value:.2f}",
            width=250,
            on_change=self._on_smoothing_change
        )
        
        # Post-processing
        self.agc_switch = ft.Switch(
            label="Auto Gain Control",
            value=self.settings.mode.agc_enabled,
            on_change=self._on_agc_change
        )
        self.peak_hold_switch = ft.Switch(
            label="Peak Hold",
            value=self.settings.mode.peak_hold_enabled,
            on_change=self._on_peak_hold_change
        )
        
        # Output streams section
        self.send_4ch_switch = ft.Switch(
            label="Send 4ch_v1",
            value=self.settings.streams.send_4ch_v1,
            on_change=self._on_stream_toggle
        )
        self.send_2ch_switch = ft.Switch(
            label="Send 2ch_v1",
            value=self.settings.streams.send_2ch_v1,
            on_change=self._on_stream_toggle
        )
        self.send_rgb_switch = ft.Switch(
            label="Send rgb_v1",
            value=self.settings.streams.send_rgb_v1,
            on_change=self._on_stream_toggle
        )
        
        # Output preview
        self.preview_4ch = [
            ft.Container(
                width=40,
                height=100,
                bgcolor=ft.Colors.GREY_900,
                border_radius=5,
                alignment=ft.alignment.Alignment(0, 1),  # bottom_center
                content=ft.Container(
                    width=36,
                    height=0,
                    bgcolor=color,
                    border_radius=3
                )
            )
            for color in [ft.Colors.GREEN_400, ft.Colors.YELLOW_400, 
                         ft.Colors.BLUE_400, ft.Colors.RED_400]
        ]
        self.preview_4ch_labels = [
            ft.Text(label, size=10, color=ft.Colors.GREY_400)
            for label in ["G", "Y", "B", "R"]
        ]
        
        self.preview_2ch = [
            ft.Container(
                width=60,
                height=100,
                bgcolor=ft.Colors.GREY_900,
                border_radius=5,
                alignment=ft.alignment.Alignment(0, 1),  # bottom_center
                content=ft.Container(
                    width=56,
                    height=0,
                    bgcolor=color,
                    border_radius=3
                )
            )
            for color in [ft.Colors.ORANGE_400, ft.Colors.TEAL_400]
        ]
        self.preview_2ch_labels = [
            ft.Text(label, size=10, color=ft.Colors.GREY_400)
            for label in ["R+Y", "G+B"]
        ]
        
        # Presets section
        self.preset_dropdown = ft.Dropdown(
            label="Preset",
            width=200
        )
        self.preset_dropdown.on_change = self._on_preset_select
        self.preset_name_field = ft.TextField(
            label="Preset Name",
            width=150
        )
        self.save_preset_btn = ft.ElevatedButton(
            "Save",
            icon=ft.Icons.SAVE,
            on_click=self._on_save_preset
        )
        self.delete_preset_btn = ft.IconButton(
            icon=ft.Icons.DELETE,
            on_click=self._on_delete_preset
        )
        
        # Initialize
        self._refresh_device_list()
        self._refresh_preset_list()
        self._apply_settings_to_pipeline()
        
        # Start UI update loop (always running for the level bar)
        self._start_ui_updates()
        
        # Start audio capture for level bar (always running)
        self._start_audio_capture()
    
    def build(self) -> ft.Control:
        """Build the main UI layout."""
        return ft.Container(
            padding=20,
            content=ft.Column(
                scroll=ft.ScrollMode.AUTO,
                controls=[
                    # Header
                    ft.Row([
                        ft.Icon(ft.Icons.GRAPHIC_EQ, size=32, color=ft.Colors.PURPLE_400),
                        ft.Text("AudioEncoder", size=24, weight=ft.FontWeight.BOLD),
                        ft.Container(expand=True),
                        self.status_text,
                    ]),
                    ft.Divider(height=20),
                    
                    # Connection section
                    ft.Text("Connection", size=18, weight=ft.FontWeight.W_500),
                    ft.Row([
                        self.host_field,
                        self.port_field,
                        self.fps_field,
                        self.start_stop_btn,
                    ], spacing=10),
                    self.stats_text,
                    ft.Divider(height=20),
                    
                    # Audio source section
                    ft.Text("Audio Source (use VB-Audio Virtual Cable)", size=18, weight=ft.FontWeight.W_500),
                    ft.Row([
                        self.device_dropdown,
                        self.refresh_devices_btn,
                        self.apply_device_btn,
                    ], spacing=10),
                    ft.Row([
                        ft.Text("Input Level:", size=12),
                        self.input_level_bar,
                    ], spacing=10),
                    ft.Divider(height=20),
                    
                    # Mode section
                    ft.Text("Visualization Mode", size=18, weight=ft.FontWeight.W_500),
                    ft.Row([
                        self.mode_dropdown,
                        self.apply_mode_btn,
                        ft.Container(width=20),
                        ft.Column([
                            ft.Text("Gain", size=12),
                            self.gain_slider,
                        ]),
                        ft.Column([
                            ft.Text("Smoothing", size=12),
                            self.smoothing_slider,
                        ]),
                    ], spacing=10),
                    ft.Row([
                        self.agc_switch,
                        ft.Container(width=30),
                        self.peak_hold_switch,
                    ]),
                    ft.Divider(height=20),
                    
                    # Output streams section
                    ft.Text("Output Streams", size=18, weight=ft.FontWeight.W_500),
                    ft.Row([
                        self.send_4ch_switch,
                        self.send_2ch_switch,
                        self.send_rgb_switch,
                    ], spacing=20),
                    ft.Container(height=10),
                    
                    # Preview section
                    ft.Row([
                        # 4ch preview
                        ft.Container(
                            padding=10,
                            border=ft.border.all(1, ft.Colors.GREY_700),
                            border_radius=10,
                            content=ft.Column([
                                ft.Text("4ch_v1 Preview", size=12, color=ft.Colors.GREY_400),
                                ft.Row(self.preview_4ch, spacing=5),
                                ft.Row(self.preview_4ch_labels, spacing=15),
                            ], horizontal_alignment=ft.CrossAxisAlignment.CENTER, spacing=5)
                        ),
                        ft.Container(width=20),
                        # 2ch preview
                        ft.Container(
                            padding=10,
                            border=ft.border.all(1, ft.Colors.GREY_700),
                            border_radius=10,
                            content=ft.Column([
                                ft.Text("2ch_v1 Preview", size=12, color=ft.Colors.GREY_400),
                                ft.Row(self.preview_2ch, spacing=5),
                                ft.Row(self.preview_2ch_labels, spacing=25),
                            ], horizontal_alignment=ft.CrossAxisAlignment.CENTER, spacing=5)
                        ),
                    ]),
                    ft.Divider(height=20),
                    
                    # Presets section
                    ft.Text("Presets", size=18, weight=ft.FontWeight.W_500),
                    ft.Row([
                        self.preset_dropdown,
                        ft.Container(width=20),
                        self.preset_name_field,
                        self.save_preset_btn,
                        self.delete_preset_btn,
                    ], spacing=10),
                ]
            )
        )
    
    def _refresh_device_list(self) -> None:
        """Refresh the audio device list (Microphone input devices only)."""
        provider = MicrophoneProvider()
        devices = provider.list_devices()
        
        self.device_dropdown.options = [
            ft.dropdown.Option(str(idx), name)
            for idx, name in devices
        ]
        
        if devices:
            # Default to "CABLE Output" if available, otherwise first device
            cable_device = None
            for idx, name in devices:
                if "cable" in name.lower() and "output" in name.lower():
                    cable_device = str(idx)
                    break
            
            if cable_device:
                self.device_dropdown.value = cable_device
                self.settings.audio.device_index = int(cable_device)
                print(f"[DEBUG] UI: Device list refreshed, selected {int(cable_device)} (CABLE Output)")
            else:
                self.device_dropdown.value = str(devices[0][0])
                self.settings.audio.device_index = devices[0][0]
                print(f"[DEBUG] UI: Device list refreshed, selected {devices[0][0]} ({devices[0][1]})")
        else:
            print(f"[DEBUG] UI: No devices found, cannot start audio capture")
        
        self.page.update()
        
        if devices:
            # Start audio capture with the selected device
            # Note: We do this directly instead of relying on change event,
            # because programmatic value changes may not always trigger the event
            print(f"[DEBUG] UI: Starting audio capture after device list refresh...")
            self._start_audio_capture()
    
    def _refresh_preset_list(self) -> None:
        """Refresh the preset dropdown."""
        presets = self.settings_manager.list_presets()
        self.preset_dropdown.options = [
            ft.dropdown.Option(name, name)
            for name in presets
        ]
        self.page.update()
    
    def _apply_settings_to_pipeline(self) -> None:
        """Apply current settings to the processing pipeline."""
        mode = self.settings.mode
        
        # Set mode
        self._pipeline.set_mode_by_id(mode.active_mode)
        
        # Set mode parameters
        if self._pipeline.mode:
            self._pipeline.mode.gain = mode.vu_gain
            params = self._pipeline.mode.get_parameters()
            if "smoothing" in params:
                self._pipeline.mode.set_parameters({"smoothing": mode.vu_smoothing})
        
        # Set post-processing
        self._pipeline.agc_enabled = mode.agc_enabled
        self._pipeline.set_agc_params(
            target=mode.agc_target,
            attack=mode.agc_attack,
            release=mode.agc_release
        )
        self._pipeline.peak_hold_enabled = mode.peak_hold_enabled
        self._pipeline.set_peak_decay(mode.peak_decay)
        
        # Set output streams
        streams = self.settings.streams
        self._frame_builder.send_4ch = streams.send_4ch_v1
        self._frame_builder.send_2ch = streams.send_2ch_v1
        self._frame_builder.send_rgb = streams.send_rgb_v1
        self._frame_builder.use_v2 = streams.use_v2_protocol
    
    # Event handlers
    def _on_host_change(self, e):
        self.settings.connection.host = e.control.value
        self._sender.host = e.control.value
    
    def _on_port_change(self, e):
        try:
            port = int(e.control.value)
            self.settings.connection.port = port
            self._sender.port = port
        except ValueError:
            pass
    
    def _on_fps_change(self, e):
        try:
            fps = int(e.control.value)
            self.settings.connection.fps = fps
            self._sender.target_fps = fps
        except ValueError:
            pass
    
    def _on_start_stop(self, e):
        if self._engine_running:
            self._stop_engine()
        else:
            self._start_engine()
    
    
    def _on_apply_device(self, e):
        """Handle Apply button click to switch to selected device."""
        device_value = self.device_dropdown.value
        print(f"[DEBUG] UI: Apply device button clicked. Selected value: {device_value}")
        
        if device_value is None or device_value == "":
            print(f"[DEBUG] UI: No device selected, cannot apply")
            return
        
        try:
            device_idx = int(device_value)
            print(f"[DEBUG] UI: Parsed device index: {device_idx}")
            
            # Get device name for debug
            device_name = "Unknown"
            for opt in self.device_dropdown.options:
                if opt.key == device_value:
                    device_name = opt.text
                    break
            
            # Update settings
            self.settings.audio.device_index = device_idx
            print(f"[DEBUG] UI: Applying device {device_idx} ({device_name})")
            
            # Restart audio capture with new device
            self._start_audio_capture()
            
        except (ValueError, TypeError) as ex:
            print(f"[DEBUG] UI: Error parsing device value: {ex}")
            self.status_text.value = f"Error: Invalid device selection"
            self.status_text.color = ft.Colors.RED_400
            self.page.update()
    
    def _on_refresh_devices(self, e):
        self._refresh_device_list()
    
    def _on_mode_change(self, e):
        self._pending_mode_id = e.control.value

    def _on_apply_mode(self, _e):
        selected_mode = self.mode_dropdown.value
        if not selected_mode:
            return

        self.settings.mode.active_mode = selected_mode
        self._apply_settings_to_pipeline()
        if self._pipeline.mode:
            self._pipeline.reset()
    
    def _on_gain_change(self, e):
        self.settings.mode.vu_gain = e.control.value
        if self._pipeline.mode:
            self._pipeline.mode.gain = e.control.value
    
    def _on_smoothing_change(self, e):
        self.settings.mode.vu_smoothing = e.control.value
        if self._pipeline.mode:
            params = self._pipeline.mode.get_parameters()
            if "smoothing" in params:
                self._pipeline.mode.set_parameters({"smoothing": e.control.value})
    
    def _on_agc_change(self, e):
        self.settings.mode.agc_enabled = e.control.value
        self._pipeline.agc_enabled = e.control.value
    
    def _on_peak_hold_change(self, e):
        self.settings.mode.peak_hold_enabled = e.control.value
        self._pipeline.peak_hold_enabled = e.control.value
    
    def _on_stream_toggle(self, e):
        self.settings.streams.send_4ch_v1 = self.send_4ch_switch.value
        self.settings.streams.send_2ch_v1 = self.send_2ch_switch.value
        self.settings.streams.send_rgb_v1 = self.send_rgb_switch.value
        
        self._frame_builder.send_4ch = self.send_4ch_switch.value
        self._frame_builder.send_2ch = self.send_2ch_switch.value
        self._frame_builder.send_rgb = self.send_rgb_switch.value
    
    def _on_preset_select(self, e):
        if e.control.value:
            if self.settings_manager.load_preset(e.control.value):
                self.settings = self.settings_manager.settings
                self._update_ui_from_settings()
                self._apply_settings_to_pipeline()
    
    def _on_save_preset(self, e):
        name = self.preset_name_field.value
        if name:
            self.settings_manager.save_preset(name)
            self._refresh_preset_list()
            self.preset_name_field.value = ""
            self.page.update()
    
    def _on_delete_preset(self, e):
        name = self.preset_dropdown.value
        if name:
            self.settings_manager.delete_preset(name)
            self._refresh_preset_list()
    
    def _update_ui_from_settings(self) -> None:
        """Update UI controls from current settings."""
        s = self.settings
        
        self.host_field.value = s.connection.host
        self.port_field.value = str(s.connection.port)
        self.fps_field.value = str(s.connection.fps)
        
        self.mode_dropdown.value = s.mode.active_mode
        self._pending_mode_id = s.mode.active_mode
        self.gain_slider.value = s.mode.vu_gain
        self.smoothing_slider.value = s.mode.vu_smoothing
        self.agc_switch.value = s.mode.agc_enabled
        self.peak_hold_switch.value = s.mode.peak_hold_enabled
        
        self.send_4ch_switch.value = s.streams.send_4ch_v1
        self.send_2ch_switch.value = s.streams.send_2ch_v1
        self.send_rgb_switch.value = s.streams.send_rgb_v1
        
        self.page.update()
    
    # Audio capture control (always running for level bar)
    def _start_audio_capture(self) -> None:
        """Start audio capture for monitoring level bar (always running)."""
        # Stop existing provider
        if self._audio_provider:
            try:
                self._audio_provider.stop()
            except Exception:
                pass
            self._audio_provider = None
        
        # Get device index
        device_idx = self.settings.audio.device_index
        if device_idx is None:
            return
        
        # Create and start audio provider
        self._audio_provider = MicrophoneProvider()
        
        # Set up audio callback
        self._frame_received_count = 0
        self._last_frame_debug = time.time()
        
        def on_audio_frame(frame: AudioFrame):
            self._frame_received_count += 1
            self._ring_buffer.write(frame.data)
            # Update input level (simple peak)
            try:
                peak = float(np.max(np.abs(frame.data)))
            except Exception:
                peak = 0.0
            self._input_level = float(min(1.0, peak * 2.0))
            
            # Debug output every 2 seconds
            current_time = time.time()
            if current_time - self._last_frame_debug >= 2.0:
                print(f"[DEBUG] Audio: Received {self._frame_received_count} frames, peak={peak:.4f}, level={self._input_level:.4f}")
                self._last_frame_debug = current_time
        
        self._audio_provider.set_callback(on_audio_frame)
        
        # Start audio capture
        print(f"[DEBUG] Audio: Starting audio capture on device {device_idx}")
        if not self._audio_provider.start(
            device_index=device_idx,
            sample_rate=self.settings.audio.sample_rate,
            chunk_size=self.settings.audio.chunk_size
        ):
            print(f"[DEBUG] Audio: Failed to start: {self._audio_provider.last_error}")
            self._audio_provider = None
    
    # Engine control
    def _start_engine(self) -> None:
        """Start the audio processing engine (sending to server)."""
        if self._engine_running:
            return
        
        # Audio provider is already running from _start_audio_capture()
        if not self._audio_provider:
            self.status_text.value = "Error: No audio device selected"
            self.status_text.color = ft.Colors.RED_400
            self.page.update()
            return
        
        # Set up frame callback for sender
        def get_frame() -> bytes:
            # Read audio from buffer
            samples = self._ring_buffer.read(self.settings.audio.chunk_size)
            
            # Process through pipeline
            output = self._pipeline.process(samples, self.settings.audio.sample_rate)
            self._current_output = output
            
            # Build packet
            self._frame_builder.set_values(
                output.to_bytes_4ch(),
                output.to_bytes_2ch(),
                output.to_bytes_rgb()
            )
            return self._frame_builder.build_packet()
        
        self._sender.set_frame_callback(get_frame)
        self._sender.host = self.settings.connection.host
        self._sender.port = self.settings.connection.port
        self._sender.target_fps = self.settings.connection.fps
        
        # Start sender
        if not self._sender.start():
            self.status_text.value = f"Error: {self._sender.last_error}"
            self.status_text.color = ft.Colors.RED_400
            self.page.update()
            self._audio_provider.stop()
            return
        
        self._engine_running = True
        self.settings.connection.enabled = True
        
        # Update UI
        self.start_stop_btn.text = "Stop"
        self.start_stop_btn.icon = ft.Icons.STOP
        self.start_stop_btn.style = ft.ButtonStyle(
            bgcolor={ft.ControlState.DEFAULT: ft.Colors.RED_700}
        )
        self.status_text.value = "Running"
        self.status_text.color = ft.Colors.GREEN_400
        self.page.update()
        
        # UI update loop is already running from initialization
    
    def _stop_engine(self) -> None:
        """Stop the audio processing engine (stop sending to server)."""
        self._engine_running = False
        self.settings.connection.enabled = False
        
        # Note: Don't stop audio provider - it keeps running for the level bar
        # Note: Don't stop UI updates - they should keep running for the level bar
        
        # Stop sender
        self._sender.stop()
        
        # Reset pipeline
        self._pipeline.reset()
        
        # Update UI
        self.start_stop_btn.text = "Start"
        self.start_stop_btn.icon = ft.Icons.PLAY_ARROW
        self.start_stop_btn.style = ft.ButtonStyle(
            bgcolor={ft.ControlState.DEFAULT: ft.Colors.GREEN_700}
        )
        self.status_text.value = "Stopped"
        self.status_text.color = ft.Colors.GREY_400
        self.stats_text.value = ""
        
        # Reset preview
        self.input_level_bar.value = 0
        for container in self.preview_4ch:
            container.content.height = 0
        for container in self.preview_2ch:
            container.content.height = 0
        
        self.page.update()
        
        # Save settings
        self.settings_manager.save()
    
    def _start_ui_updates(self) -> None:
        """Start periodic UI updates (always running)."""
        if self._ui_update_running:
            return
        
        self._ui_update_running = True
        
        async def update_loop():
            """Async UI updates on the main event loop."""
            update_counter = 0
            
            while self._ui_update_running:
                try:
                    # Update UI values
                    level = float(self._input_level) if self._input_level is not None else 0.0
                    self.input_level_bar.value = max(0.0, min(1.0, level))
                    
                    # Stats - only show when engine is running
                    if self._engine_running:
                        stats = self._sender.stats
                        self.stats_text.value = (
                            f"Packets: {stats.packets_sent} | "
                            f"FPS: {stats.actual_fps:.1f} | "
                            f"Errors: {stats.errors}"
                        )
                        
                        # 4ch preview
                        for i, container in enumerate(self.preview_4ch):
                            if i < len(self._current_output.values_4ch):
                                height = float(self._current_output.values_4ch[i]) * 90.0
                                container.content.height = max(2.0, height)
                        
                        # 2ch preview
                        for i, container in enumerate(self.preview_2ch):
                            if i < len(self._current_output.values_2ch):
                                height = float(self._current_output.values_2ch[i]) * 90.0
                                container.content.height = max(2.0, height)
                    
                    self.page.update()
                    
                    # Debug output every second to verify updates are happening
                    update_counter += 1
                    if update_counter % 30 == 0:  # Every ~1 second at 30Hz
                        print(f"[DEBUG] UI: Level bar updated to {level:.4f}")
                except RuntimeError as e:
                    if "destroyed session" in str(e).lower():
                        self._ui_update_running = False
                        break
                    print(f"[DEBUG] UI: Error in update loop: {e}")
                except Exception as e:
                    print(f"[DEBUG] UI: Error in update loop: {e}")
                
                await asyncio.sleep(1.0 / 30)  # 30 Hz UI updates for smoother animation
        
        self.page.run_task(update_loop)

    def _on_page_disconnect(self, _e) -> None:
        """Stop background tasks when the page is closed."""
        self._ui_update_running = False
    
