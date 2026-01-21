# System Audio Loopback Setup Guide

AudioEncoder requires capturing system audio (what you hear through speakers) to create LED visualizations. This guide explains how to set this up on Windows.

## Solution 1: VB-Audio Virtual Cable (Recommended)

**Best for:** Systems without "Stereo Mix" (like ThinkPad T580)

### Installation Steps:

1. **Download VB-Audio Virtual Cable**
   - Visit: https://vb-audio.com/Cable/
   - Download `VBCABLE_Driver_Pack43.zip` (or latest version)
   - Extract the ZIP file

2. **Install the Driver**
   - Right-click `VBCABLE_Setup_x64.exe` (or x86 for 32-bit)
   - Select "Run as Administrator"
   - Click "Install Driver"
   - Restart your computer if prompted

3. **Configure Windows Audio**
   - Right-click the speaker icon → **Sounds**
   - **Playback** tab:
     - Set **"CABLE Input"** as your default playback device
     - OR use "Listen to this device" feature (see below)
   
   - **Recording** tab:
     - **"CABLE Output"** should appear as a recording device
     - This is what AudioEncoder will capture from

4. **Route Audio Through Cable**
   
   **Option A - Set as Default (captures ALL system audio):**
   - Set "CABLE Input" as default playback device
   - You won't hear audio unless you route it back to speakers:
     - Open **"CABLE Input" properties** → **Listen** tab
     - Check "Listen to this device"
     - Select your speakers/headphones in the dropdown
   
   **Option B - Route Specific Apps:**
   - Keep your speakers as default
   - In Windows Volume Mixer (Windows 10/11):
     - Click app audio settings
     - Set specific apps (e.g., browser, Spotify) to output to "CABLE Input"
   - Set CABLE Input to listen through your speakers (as above)

5. **Configure AudioEncoder**
   - Audio Source: **"Microphone"** (not System Audio)
   - Device: Select **"CABLE Output"**
   - Click **Start**

### Uninstall (if needed):
- Run `VBCABLE_Setup_x64.exe` as administrator
- Click "Uninstall Driver"

---

## Solution 2: Enable Stereo Mix (if available)

**Best for:** Older systems or desktops where Stereo Mix is available

### Steps:

1. Right-click the speaker icon → **Sounds**
2. Go to **Recording** tab
3. Right-click empty space → **Show Disabled Devices**
4. If "Stereo Mix" appears:
   - Right-click it → **Enable**
   - Right-click it → **Set as Default Device** (optional)
5. In AudioEncoder:
   - Audio Source: **"System Audio (WASAPI)"**
   - Device: **"System Audio (Default Output)"**
   - Click **Start**

**Note:** Stereo Mix is often disabled or missing on:
- Modern laptops (ThinkPads, Dell XPS, etc.)
- Systems with Realtek audio drivers after ~2015
- Devices with power-saving features

---

## Solution 3: Update PyAudio for Native WASAPI Loopback

**Best for:** Developers who want native loopback without virtual devices

### Steps:

1. Install PyAudio with WASAPI support:
   ```bash
   pip uninstall pyaudio
   pip install --upgrade pyaudio
   ```
   
   Or build from source with WASAPI enabled (advanced)

2. In AudioEncoder:
   - Audio Source: **"System Audio (WASAPI)"**
   - Device: **"System Audio (Default Output)"**
   
   The app will automatically try to use `as_loopback=True` parameter

**Note:** Standard PyAudio from pip may not include WASAPI loopback support. You might need a custom Windows build.

---

## Troubleshooting

### "No audio detected" with VB-Cable:
1. Verify audio is playing through CABLE Input in Volume Mixer
2. Check that "Listen to this device" is enabled so you can hear audio
3. Make sure AudioEncoder is using "CABLE Output" as the device

### "Invalid number of channels" error:
- This means WASAPI loopback is not working
- Use VB-Audio Virtual Cable solution instead

### Audio quality issues:
- In VB-Cable Input properties → Advanced tab:
  - Set to "2 channel, 24 bit, 48000 Hz" (or 44100 Hz)
- In AudioEncoder, ensure FPS is set appropriately (25-60)

### High latency:
- In VB-Cable properties → Advanced:
  - Reduce buffer size (may cause crackling if too low)
- In AudioEncoder:
  - Use lower FPS (25-30) if UDP packets are dropping

---

## How It Works

### VB-Audio Virtual Cable:
```
[Your App] → CABLE Input → [Virtual Cable] → CABLE Output → [AudioEncoder]
     ↓
  (Listen)
     ↓
[Speakers/Headphones]
```

### WASAPI Loopback (when supported):
```
[Your App] → [Audio Driver] → [Speakers]
                   ↓ (loopback capture)
            [AudioEncoder]
```

### Stereo Mix:
```
[Your App] → [Audio Mixer] → [Speakers]
                   ↓ (hardware mix)
              [Stereo Mix Device] → [AudioEncoder]
```

---

## Recommended Setup for ThinkPad T580

Since Stereo Mix is not available on your ThinkPad T580:

1. **Install VB-Audio Virtual Cable** (Solution 1)
2. Use **Option B** (route specific apps) to keep normal audio playback
3. Set your browser or music player to output to "CABLE Input"
4. Enable "Listen to this device" on CABLE Input → route to your headphones
5. In AudioEncoder:
   - Source: **Microphone**
   - Device: **CABLE Output**

This way, you can visualize specific apps without affecting your entire system audio.
