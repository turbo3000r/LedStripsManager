# AudioEncoder

A Python Flet desktop application that captures audio (microphone or system audio), analyzes it in real-time, and streams LED brightness frames to the Lighting Control Hub server.

## Features

- **Audio Capture**: Microphone input and Windows system audio (WASAPI loopback)
- **Visualization Modes**: VU/RMS, FFT bands, beat detection, peak hold with decay
- **Multi-Stream Output**: Sends frames for multiple hardware modes (4ch_v1, 2ch_v1, rgb_v1)
- **Auto-Gain Control**: Keeps output reactive across different volume levels
- **Preset System**: Save and load configuration presets

## Requirements

- Python 3.9+
- Windows 10/11 (for system audio capture via WASAPI)
- Lighting Control Hub server running with UDP repeater enabled

## Installation

```bash
# Create virtual environment
python -m venv venv

# Activate (Windows)
venv\Scripts\activate

# Install dependencies
pip install -r requirements.txt
```

## Running

```bash
python main.py
```

## System Audio Setup (Important!)

To capture system audio (what you hear through speakers), you need to set up audio loopback. See **[LOOPBACK_SETUP.md](LOOPBACK_SETUP.md)** for detailed instructions.

**Quick Start:**
- If you have **"Stereo Mix"** available: Enable it in Windows Sound settings, then select "System Audio (WASAPI)" as the source
- If **"Stereo Mix" is missing** (common on laptops like ThinkPad T580): Install **VB-Audio Virtual Cable** (free), then select it as the audio device in AudioEncoder

Without proper loopback setup, you can only use microphone input.

## Configuration

Settings are persisted in `config/user_settings.json` and include:
- Server connection (host, port)
- Audio source selection
- Mode parameters (gain, smoothing, FFT bands, etc.)
- Output stream configuration

## Architecture

```
AudioEncoder/
├── main.py              # Application entrypoint
├── config/
│   └── settings.py      # Settings management and presets
├── audio/
│   ├── base.py          # Audio provider base class
│   ├── mic.py           # Microphone capture
│   └── loopback.py      # Windows WASAPI loopback capture
├── analysis/
│   ├── rms.py           # RMS/VU meter analysis
│   ├── fft.py           # FFT frequency band analysis
│   └── beat.py          # Beat/onset detection
├── modes/
│   ├── base.py          # Mode base class and registry
│   ├── vu_mode.py       # VU meter mode
│   ├── fft_mode.py      # FFT bands mode
│   ├── beat_mode.py     # Beat strobe mode
│   └── pipeline.py      # Mode composition and post-FX
├── protocol/
│   └── led_packets.py   # LED v1/v2 packet builders
├── output/
│   └── udp_sender.py    # UDP sender with frame pacing
└── ui/
    └── app.py           # Flet UI components
```

## Protocol

AudioEncoder sends UDP packets to the server's `udp_repeater.listen_port` (default: 5001).

### LED v1 (Single Stream)
Simple single-stream format for backward compatibility.

### LED v2 (Multi-Stream)
Sends multiple hardware-mode-specific streams in one packet. Server selects the best match per device.
