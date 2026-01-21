# Lighting Control Hub

A Python-based control system for orchestrating multiple MQTT-connected LED dimmers via a web dashboard.

## Features

- **Web Dashboard**: Real-time control UI with WebSocket updates
- **Per-Device Modes**: Static, Planned Schedule, or Fast/Music mode per device
- **MQTT Integration**: Publish lighting plans and receive device heartbeats
- **UDP Fast Mode**: Low-latency streaming for music-reactive lighting
- **Room Grouping**: Organize devices by room for intuitive control

## Requirements

- Python 3.9+
- MQTT Broker (e.g., Mosquitto) running on localhost or network
- ESP devices configured to connect to the broker

## Installation

```bash
# Create virtual environment
python -m venv venv

# Activate (Windows)
venv\Scripts\activate

# Activate (Linux/macOS/Raspberry Pi)
source venv/bin/activate

# Install dependencies
pip install -r requirements.txt
```

## Configuration

Edit `config/config.yaml` to define:
- MQTT broker connection details
- Device definitions (IP, channels, topics)
- Room groupings

## Running the Server

```bash
# Development
uvicorn app.main:app --reload --host 0.0.0.0 --port 8000

# Production (Raspberry Pi)
uvicorn app.main:app --host 0.0.0.0 --port 8000
```

Access the dashboard at: http://localhost:8000

## Docker Deployment (Raspberry Pi)

### Files Created

- [Dockerfile](Dockerfile)
- [docker-compose.yml](docker-compose.yml)
- [mosquitto.conf](mosquitto.conf)

### Configuration Notes

- [config/config.yaml](config/config.yaml) uses `mqtt.broker_host: "mosquitto"` for container networking.
- Plans are persisted via the mounted [plans](plans) folder.

### Run with Docker Compose

From the [Server](.) directory:

```bash
docker compose up -d --build
```

Open the Web UI at: http://<raspberrypi-ip>:8000

## API Endpoints

### REST API
- `GET /api/devices` - List all devices with status
- `POST /api/device/{id}/mode` - Set device mode (`static`, `planned`, `fast`)
- `POST /api/device/{id}/static` - Set static brightness values
- `POST /api/device/{id}/fast` - Set fast-mode values

### WebSocket
- `WS /ws` - Real-time status updates and control

## Testing with Mock Devices

To test without real ESP devices, publish fake heartbeats:

```bash
# Install mosquitto clients
# Publish heartbeat every 5 seconds
while true; do
  mosquitto_pub -h localhost -t "lights/livingroom/heartbeat" -m '{"device_id":"esp_livingroom_1","uptime":12345}'
  sleep 5
done
```

## Architecture

```
┌─────────────┐     HTTP/WS      ┌──────────────┐
│   Browser   │◄────────────────►│   FastAPI    │
└─────────────┘                  └──────┬───────┘
                                        │
                                        ▼
                                 ┌──────────────┐
                                 │ SharedState  │
                                 └──────┬───────┘
                    ┌───────────────────┼───────────────────┐
                    ▼                   ▼                   ▼
            ┌──────────────┐    ┌──────────────┐    ┌──────────────┐
            │ MQTT Client  │    │   Planner    │    │ UDP Streamer │
            │ (heartbeats) │    │  (T+1 plans) │    │ (fast mode)  │
            └──────┬───────┘    └──────┬───────┘    └──────┬───────┘
                   │                   │                   │
                   ▼                   ▼                   ▼
            ┌─────────────────────────────────────────────────────┐
            │                    ESP Devices                       │
            └─────────────────────────────────────────────────────┘
```

