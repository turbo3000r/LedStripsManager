# ESP <-> Server Communication Protocol

This document defines the communication protocols between the Lighting Control Hub server and ESP8266/ESP32 devices.

## Overview

The system uses three distinct communication channels depending on the operating mode:
1. **MQTT** for "Static" and "Planned" modes (control & telemetry).
2. **UDP** for "Fast" mode (low-latency streaming).
3. **HTTP/WebSocket** for User Interface (Client <-> Server only).

## 1. MQTT Communication

Devices must connect to the MQTT broker configured in `config/config.yaml`.

### Topics

Topics are **fully configurable per device** in the server's `config/config.yaml` file. The server does not enforce a specific topic structure; it simply publishes to and subscribes from the exact topic strings defined in the configuration.

Common conventions you can use (pick any structure you like; the server does not care) include:

- **Per-device topics**: `lights/{room}/{device_id}/set_static`, `lights/{room}/{device_id}/set_plan`, `lights/{room}/{device_id}/heartbeat`
- **Per-group topics**: `lights/{group}/set_static`, `lights/{group}/set_plan`, `lights/{group}/heartbeat`

**Important (current implementation)**: The server determines which device sent a heartbeat by looking up the *topic string* in its loaded configuration (`topic -> device_id`). Therefore, each device should have a **unique** heartbeat topic. The heartbeat payload is currently *not* used for disambiguation.

**Example Configuration**:
```yaml
rooms:
  - name: "Living Room"
    devices:
      - device_id: "esp_livingroom_1"
        topics:
          set_plan: "lights/room1/esp_dimmer_1/set_plan"
          set_static: "lights/room1/esp_dimmer_1/set_static"
          heartbeat: "lights/room1/esp_dimmer_1/heartbeat"
```

### Payload Formats

#### A. Heartbeat (Device -> Server)
Devices must publish to their heartbeat topic periodically (e.g., every 5s) to be considered "Online".

**Payload (JSON optional, or empty)**:
```json
{
  "device_id": "esp_livingroom_1",
  "uptime": 12345,
  "firmware": "1.0.0",
  "ip": "192.168.1.101"
}
```
*Note: The server currently uses the MQTT message arrival to mark the device online; the payload content is logged for debugging but not strictly enforced.*

#### B. Set Static Values (Server -> Device)
Used when the device is in "Static" mode. The server sends target brightness values.

**Topic**: `{set_static_topic}`
**Payload (JSON)**:
```json
{
  "values": [255, 128, 0, 50]
}
```
- `values`: Array of integers [0-255] corresponding to each channel.

#### C. Set Planned Sequence (Server -> Device)
Used when the device is in "Planned" mode. The server publishes a plan for a **future interval boundary** (latency compensation) every planner tick.

**Topic**: `{set_plan_topic}`

The server supports two payload formats, configurable via `planner.plan_payload_version` in config (default: 2).

##### Format Version 2 (Default - Per-Step Timestamps)

Each step has an absolute millisecond timestamp, making it ready-to-use without interval calculation:

```json
{
  "format_version": 2,
  "steps": [
    {"ts_ms": 1704067201000, "values": [0, 0, 0, 0]},
    {"ts_ms": 1704067201100, "values": [25, 25, 25, 25]},
    {"ts_ms": 1704067201200, "values": [50, 50, 50, 50]},
    {"ts_ms": 1704067201300, "values": [75, 75, 75, 75]},
    {"ts_ms": 1704067201400, "values": [100, 100, 100, 100]}
  ]
}
```
- `format_version`: Always `2` for this format.
- `steps`: Array of step objects, each containing:
  - `ts_ms`: Absolute Unix timestamp in **milliseconds** when this step should be applied.
  - `values`: Array of channel values [0-255].

##### Format Version 1 (Legacy - Packed Format)

The original format with a start timestamp and fixed interval:

```json
{
  "timestamp": 1704067201,
  "interval_ms": 100,
  "sequence": [
    [0, 0, 0, 0],
    [25, 25, 25, 25],
    [50, 50, 50, 50],
    [75, 75, 75, 75],
    [100, 100, 100, 100]
  ]
}
```
- `timestamp`: Unix timestamp (seconds) when this sequence **starts**.
- `interval_ms`: Duration of each step in milliseconds.
- `sequence`: Array of steps. Each step is an array of channel values [0-255].

**Timing**: The device should buffer the payload and start executing it exactly when `system_time >= timestamp` (v1) or `system_time_ms >= ts_ms` (v2). The server sends plans ahead of their execution time for latency compensation.

## 2. UDP Communication (Fast Mode)

Used for high-speed updates (e.g., music syncing). The server streams UDP packets directly to the device IP.

**Port**: Configurable (Default: 5000)
**Rate**: Configurable (Default: 60Hz)

### Fast Mode Types

The server supports two fast mode types per device/room:

1. **Internal** (`fast_mode_type: internal`): Server-controlled values set via the UI or API.
2. **UDP Repeater** (`fast_mode_type: udp_repeater`): Server relays frames from an external UDP source.

### Packet Structure (LED v1 Protocol)

A binary protocol is used for efficiency.

| Offset | Size | Field | Description |
|--------|------|-------|-------------|
| 0 | 3 | Header | ASCII "LED" |
| 3 | 1 | Version | Protocol Version (currently 1) |
| 4 | 1 | Channels | Number of channels (N) |
| 5 | N | Values | Brightness values (0-255) per channel |

**Example (4 channels)**:
```
Bytes:  4C 45 44 01 04 FF 80 00 32
ASCII:   L  E  D  v1 N=4 [Values]
```

### UDP Repeater Mode

When devices are configured for `udp_repeater` fast mode, the server listens for external UDP packets and forwards them to all target devices.

**Server Listen Port**: Configurable via `udp_repeater.listen_port` (Default: 5001)

**External Source -> Server**: Send LED v1 packets to the server's listen port. The server will:
1. Validate the packet format
2. Forward to all devices in FAST mode with `fast_mode_type: udp_repeater`
3. Adapt channel count for each device (e.g., 4ch input to 2ch device)

**Channel Adaptation for 2ch_v1**:
When a 4-channel input (from `4ch_v1`: Green, Yellow, Blue, Red) is sent to a `2ch_v1` device:
- Output 0 (Red+Yellow) = max(Red, Yellow)
- Output 1 (Green+Blue) = max(Green, Blue)

### Packet Structure (LED v2 Protocol - Multi-Stream)

LED v2 extends the protocol to support **multiple streams per packet**, allowing external sources (e.g., AudioEncoder) to send pre-computed values for different hardware modes simultaneously. The server selects the best-matching stream for each target device.

| Offset | Size | Field | Description |
|--------|------|-------|-------------|
| 0 | 3 | Header | ASCII "LED" |
| 3 | 1 | Version | Protocol Version (2) |
| 4 | 1 | StreamCount | Number of streams (S) in this packet |
| 5+ | variable | Streams | S stream blocks (see below) |

**Stream Block Format** (repeated `StreamCount` times):

| Offset | Size | Field | Description |
|--------|------|-------|-------------|
| 0 | 1 | StreamID | Hardware mode identifier (see table) |
| 1 | 1 | Channels | Number of channels (N) in this stream |
| 2 | N | Values | Brightness values (0-255) per channel |

**Stream ID Mapping**:

| StreamID | hw_mode | Channel Order |
|----------|---------|---------------|
| 1 | `4ch_v1` | Green, Yellow, Blue, Red |
| 2 | `2ch_v1` | Red+Yellow, Green+Blue |
| 3 | `rgb_v1` | Red, Green, Blue |

**Example (2 streams: 4ch_v1 + 2ch_v1)**:
```
Bytes:  4C 45 44 02 02 01 04 FF 80 00 32 02 02 80 FF
ASCII:   L  E  D  v2 S=2 [Stream1: id=1, N=4, values] [Stream2: id=2, N=2, values]
```

**Server Stream Selection Logic**:
1. Find a stream with `StreamID` matching the device's `hw_mode`.
2. If no exact match, fall back to `4ch_v1` stream and apply channel adaptation.
3. If no `4ch_v1` stream, use the first available stream and truncate/pad.

**Backward Compatibility**:
- The server continues to accept LED v1 packets (version=1).
- External sources can send either v1 (single stream) or v2 (multi-stream) packets.

## 3. Device Logic Recommendations

### Mode Switching
The device firmware should maintain a current "Mode" state.
- **Static Mode**: Listen to MQTT `set_static` topic. Apply values immediately.
- **Planned Mode**: Listen to MQTT `set_plan` topic. Buffer the future interval plan and execute it at `timestamp`, synchronized with NTP time.
- **Fast Mode**: Listen on UDP port. Apply values immediately upon receipt. Ignore MQTT control messages (except mode changes if implemented via MQTT, though currently mode is server-side logic).

*Note: In the current server implementation, the server decides which stream to send based on the mode selected in the UI. The device effectively receives data on only one channel at a time (or ignores the others).*

### Time Synchronization
For "Planned" mode to work correctly, the ESP **must** synchronize its clock via NTP and use **UTC timezone**.

**Important**: The server sends `timestamp` as a **UTC Unix timestamp** (seconds since epoch). The ESP device must also use UTC to avoid timezone offset issues.

**ESP Configuration**:
```cpp
// Configure NTP with UTC timezone (offset 0, DST offset 0)
configTime(0, 0, "pool.ntp.org", "time.nist.gov");
```

- **Latency Compensation**: The server sends plans ahead of their execution time (future-aligned `timestamp`; see Timing note in the Set Planned Sequence section).
- The device should buffer the latest received plan and begin playback exactly when its local clock reaches `timestamp`.
- **No timezone conversion needed**: Both server and ESP use UTC, so timestamps can be compared directly.

### Failsafe
- If no Heartbeat is sent for `heartbeat_timeout_sec` (default 10s), the server marks the device as Offline.
- If the device stops receiving data in Fast/Planned mode, it should hold the last value or fade to black (firmware choice).

## 4. Hardware Modes

The server supports multiple hardware modes (`hw_mode`) that define channel count and labels:

| Mode | Channels | Labels | Description |
|------|----------|--------|-------------|
| `4ch_v1` | 4 | Green, Yellow, Blue, Red | Standard 4-channel dimmer |
| `2ch_v1` | 2 | Red+Yellow, Green+Blue | 2-channel dimmer with paired colors |
| `rgb_v1` | 3 | Red, Green, Blue | RGB LED strip |

### 2ch_v1 Mode

The `2ch_v1` mode controls two outputs where each output drives a pair of colors together:
- **Output 0**: Controls Red and Yellow LEDs together
- **Output 1**: Controls Green and Blue LEDs together

This is useful for simplified wiring or when using LED strips with paired color channels.

**Configuration Example**:
```yaml
devices:
  - device_id: "esp_bedroom_2ch"
    ip: "192.168.1.105"
    udp_port: 5000
    hw_mode: "2ch_v1"
    topics:
      set_plan: "lights/bedroom/2ch/set_plan"
      set_static: "lights/bedroom/2ch/set_static"
      heartbeat: "lights/bedroom/2ch/heartbeat"
```

## 5. Room Control

Rooms support two control modes:

- **Manual**: Each device is controlled individually (default).
- **Auto**: All devices in the room share the same mode, values, and settings.

In Auto mode, changes to room settings are immediately applied to all devices in that room.
