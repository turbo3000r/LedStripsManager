"""FastAPI application entrypoint for the Lighting Control Hub."""

import asyncio
import logging
from contextlib import asynccontextmanager
from typing import Optional

from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from app.config import get_config
from app.state import SharedState, DeviceMode, RoomControlMode, FastModeType, get_state
from app.mqtt_client import MqttClient
from app.planner import PlannerLoop
from app.udp_streamer import UdpStreamer
from app.udp_repeater import UdpRepeater
from app.plans_store import (
    list_plans, load_plan, save_plan, delete_plan,
    PlanValidationError, _ensure_plans_dir
)

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger(__name__)

# Global instances
mqtt_client: Optional[MqttClient] = None
planner_loop: Optional[PlannerLoop] = None
udp_streamer: Optional[UdpStreamer] = None
udp_repeater: Optional[UdpRepeater] = None


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application lifespan handler - startup and shutdown."""
    global mqtt_client, planner_loop, udp_streamer, udp_repeater

    config = get_config()
    state = get_state()

    # Initialize state from config
    state.initialize_from_config(config)

    # Ensure plans directory exists
    _ensure_plans_dir()

    # Start MQTT client
    mqtt_client = MqttClient(config, state)
    mqtt_client.start()
    logger.info("MQTT client started")

    # Start planner loop
    planner_loop = PlannerLoop(config, state, mqtt_client)
    planner_loop.start()
    logger.info("Planner loop started")

    # Start UDP streamer
    udp_streamer = UdpStreamer(config, state)
    udp_streamer.start()
    logger.info("UDP streamer started")

    # Start UDP repeater (for external frame forwarding)
    udp_repeater = UdpRepeater(config, state)
    udp_repeater.start()
    logger.info("UDP repeater started")

    yield

    # Shutdown
    logger.info("Shutting down...")
    if udp_repeater:
        udp_repeater.stop()
    if udp_streamer:
        udp_streamer.stop()
    if planner_loop:
        planner_loop.stop()
    if mqtt_client:
        mqtt_client.stop()
    logger.info("Shutdown complete")


app = FastAPI(
    title="Lighting Control Hub",
    description="Control system for MQTT-connected LED dimmers",
    version="1.0.0",
    lifespan=lifespan,
)

# Mount static files for web UI
app.mount("/static", StaticFiles(directory="app/web"), name="static")


# --- Pydantic models for API ---

class ModeRequest(BaseModel):
    mode: str  # "static", "planned", "fast"


class StaticRequest(BaseModel):
    values: list[int]  # Brightness values per channel (0-255)


class FastRequest(BaseModel):
    values: list[int]  # Fast mode values per channel (0-255)


class PlannedPlanRequest(BaseModel):
    plan_id: str | None  # Plan ID to assign (null to unassign)


class RoomControlModeRequest(BaseModel):
    control_mode: str  # "auto" or "manual"


class RoomModeRequest(BaseModel):
    mode: str  # "static", "planned", "fast"


class RoomStaticRequest(BaseModel):
    values: list[int]  # Brightness values per channel (0-255)


class RoomPlannedPlanRequest(BaseModel):
    plan_id: str | None  # Plan ID to assign (null to unassign)


class RoomFastModeTypeRequest(BaseModel):
    fast_mode_type: str  # "internal" or "udp_repeater"


class DeviceFastModeTypeRequest(BaseModel):
    fast_mode_type: str  # "internal" or "udp_repeater"


class PlanCreateRequest(BaseModel):
    name: str
    mode: str = "4ch_v1"
    channels: int = 4
    intensity_scale: str = "0-100"
    interval_ms: int
    steps: list[list[int]]


class PlanUpdateRequest(BaseModel):
    name: str
    mode: str = "4ch_v1"
    channels: int = 4
    intensity_scale: str = "0-100"
    interval_ms: int
    steps: list[list[int]]


# --- REST API Endpoints ---

@app.get("/")
async def root():
    """Serve the main dashboard page."""
    return FileResponse("app/web/index.html")


@app.get("/plans-ui")
async def plans_ui():
    """Serve the plan editor page."""
    return FileResponse("app/web/plans.html")


@app.get("/api/devices")
async def get_devices():
    """Get all devices with their current status."""
    state = get_state()
    return JSONResponse(content=state.get_all_device_status())


@app.get("/api/rooms")
async def get_rooms():
    """Get room structure with devices."""
    config = get_config()
    state = get_state()

    rooms_data = []
    for room in config.rooms:
        room_data = {
            "name": room.name,
            "devices": []
        }
        for device in room.devices:
            device_status = state.get_device_status(device.device_id)
            if device_status:
                room_data["devices"].append(device_status)
        rooms_data.append(room_data)

    return JSONResponse(content=rooms_data)


@app.post("/api/device/{device_id}/mode")
async def set_device_mode(device_id: str, request: ModeRequest):
    """Set the mode for a specific device."""
    state = get_state()

    try:
        mode = DeviceMode(request.mode)
    except ValueError:
        return JSONResponse(
            status_code=400,
            content={"error": f"Invalid mode: {request.mode}. Must be 'static', 'planned', or 'fast'"}
        )

    if not state.set_device_mode(device_id, mode):
        return JSONResponse(
            status_code=404,
            content={"error": f"Device not found: {device_id}"}
        )

    # Notify WebSocket clients
    await broadcast_state_update()

    return JSONResponse(content={"status": "ok", "device_id": device_id, "mode": mode.value})


@app.post("/api/device/{device_id}/static")
async def set_static_values(device_id: str, request: StaticRequest):
    """Set static brightness values for a device."""
    state = get_state()

    if not state.set_static_values(device_id, request.values):
        return JSONResponse(
            status_code=404,
            content={"error": f"Device not found: {device_id}"}
        )

    # Publish to MQTT if device is in static mode
    if mqtt_client:
        device_state = state.get_device_status(device_id)
        if device_state and device_state.get("mode") == "static":
            config = get_config()
            device_config = config.get_device_by_id(device_id)
            if device_config:
                mqtt_client.publish_static(device_config, request.values)

    # Notify WebSocket clients
    await broadcast_state_update()

    return JSONResponse(content={"status": "ok", "device_id": device_id, "values": request.values})


@app.post("/api/device/{device_id}/fast")
async def set_fast_values(device_id: str, request: FastRequest):
    """Set fast mode values for a device (used by audio analyzer or other sources)."""
    state = get_state()

    if not state.set_fast_values(device_id, request.values):
        return JSONResponse(
            status_code=404,
            content={"error": f"Device not found: {device_id}"}
        )

    return JSONResponse(content={"status": "ok", "device_id": device_id, "values": request.values})


@app.post("/api/device/{device_id}/planned_plan")
async def set_device_planned_plan(device_id: str, request: PlannedPlanRequest):
    """Assign a plan to a device for planned mode."""
    state = get_state()

    # Validate plan exists if not unsetting
    if request.plan_id:
        plan = load_plan(request.plan_id)
        if not plan:
            return JSONResponse(
                status_code=404,
                content={"error": f"Plan not found: {request.plan_id}"}
            )

    if not state.set_device_plan(device_id, request.plan_id):
        return JSONResponse(
            status_code=404,
            content={"error": f"Device not found: {device_id}"}
        )

    # Notify WebSocket clients
    await broadcast_state_update()

    return JSONResponse(content={"status": "ok", "device_id": device_id, "plan_id": request.plan_id})


@app.post("/api/device/{device_id}/fast_mode_type")
async def set_device_fast_mode_type(device_id: str, request: DeviceFastModeTypeRequest):
    """Set the fast mode type for a device."""
    state = get_state()

    try:
        fast_mode_type = FastModeType(request.fast_mode_type)
    except ValueError:
        return JSONResponse(
            status_code=400,
            content={"error": f"Invalid fast_mode_type: {request.fast_mode_type}. Must be 'internal' or 'udp_repeater'"}
        )

    if not state.set_device_fast_mode_type(device_id, fast_mode_type):
        return JSONResponse(
            status_code=404,
            content={"error": f"Device not found: {device_id}"}
        )

    # Notify WebSocket clients
    await broadcast_state_update()

    return JSONResponse(content={"status": "ok", "device_id": device_id, "fast_mode_type": fast_mode_type.value})


# --- Room API ---

@app.get("/api/rooms/control")
async def get_rooms_control():
    """Get room control states."""
    state = get_state()
    return JSONResponse(content=state.get_all_room_control_states())


@app.post("/api/room/{room_name}/control_mode")
async def set_room_control_mode(room_name: str, request: RoomControlModeRequest):
    """Set the control mode (AUTO/MANUAL) for a room."""
    state = get_state()

    try:
        control_mode = RoomControlMode(request.control_mode)
    except ValueError:
        return JSONResponse(
            status_code=400,
            content={"error": f"Invalid control_mode: {request.control_mode}. Must be 'auto' or 'manual'"}
        )

    if not state.set_room_control_mode(room_name, control_mode):
        return JSONResponse(
            status_code=404,
            content={"error": f"Room not found: {room_name}"}
        )

    # If switching to AUTO, publish to MQTT for devices in static mode
    if control_mode == RoomControlMode.AUTO and mqtt_client:
        config = get_config()
        for device_id in state.get_devices_in_room(room_name):
            device_state = state.get_device_status(device_id)
            if device_state and device_state.get("mode") == "static":
                device_config = config.get_device_by_id(device_id)
                if device_config:
                    mqtt_client.publish_static(device_config, device_state.get("static_values", []))

    # Notify WebSocket clients
    await broadcast_state_update()
    await broadcast_rooms_control_update()

    return JSONResponse(content={"status": "ok", "room_name": room_name, "control_mode": control_mode.value})


@app.post("/api/room/{room_name}/mode")
async def set_room_mode(room_name: str, request: RoomModeRequest):
    """Set the operating mode for all devices in a room (when in AUTO mode)."""
    state = get_state()

    try:
        mode = DeviceMode(request.mode)
    except ValueError:
        return JSONResponse(
            status_code=400,
            content={"error": f"Invalid mode: {request.mode}. Must be 'static', 'planned', or 'fast'"}
        )

    if not state.set_room_mode(room_name, mode):
        return JSONResponse(
            status_code=404,
            content={"error": f"Room not found: {room_name}"}
        )

    # Notify WebSocket clients
    await broadcast_state_update()
    await broadcast_rooms_control_update()

    return JSONResponse(content={"status": "ok", "room_name": room_name, "mode": mode.value})


@app.post("/api/room/{room_name}/static")
async def set_room_static_values(room_name: str, request: RoomStaticRequest):
    """Set static brightness values for all devices in a room (when in AUTO mode)."""
    state = get_state()

    if not state.set_room_static_values(room_name, request.values):
        return JSONResponse(
            status_code=404,
            content={"error": f"Room not found: {room_name}"}
        )

    # Publish to MQTT for devices in static mode within this room
    if mqtt_client and state.is_room_auto_mode(room_name):
        config = get_config()
        room_state = state.get_room_control_state(room_name)
        if room_state and room_state.mode == DeviceMode.STATIC:
            for device_id in state.get_devices_in_room(room_name):
                device_config = config.get_device_by_id(device_id)
                if device_config:
                    # Adapt values to device channel count
                    device_values = state.get_effective_static_values(device_id)
                    if device_values:
                        mqtt_client.publish_static(device_config, device_values)

    # Notify WebSocket clients
    await broadcast_state_update()
    await broadcast_rooms_control_update()

    return JSONResponse(content={"status": "ok", "room_name": room_name, "values": request.values})


@app.post("/api/room/{room_name}/planned_plan")
async def set_room_planned_plan(room_name: str, request: RoomPlannedPlanRequest):
    """Assign a plan to all devices in a room for planned mode (when in AUTO mode)."""
    state = get_state()

    # Validate plan exists if not unsetting
    if request.plan_id:
        plan = load_plan(request.plan_id)
        if not plan:
            return JSONResponse(
                status_code=404,
                content={"error": f"Plan not found: {request.plan_id}"}
            )

    if not state.set_room_planned_plan(room_name, request.plan_id):
        return JSONResponse(
            status_code=404,
            content={"error": f"Room not found: {room_name}"}
        )

    # Notify WebSocket clients
    await broadcast_state_update()
    await broadcast_rooms_control_update()

    return JSONResponse(content={"status": "ok", "room_name": room_name, "plan_id": request.plan_id})


@app.post("/api/room/{room_name}/fast_mode_type")
async def set_room_fast_mode_type(room_name: str, request: RoomFastModeTypeRequest):
    """Set the fast mode type for all devices in a room (when in AUTO mode)."""
    state = get_state()

    try:
        fast_mode_type = FastModeType(request.fast_mode_type)
    except ValueError:
        return JSONResponse(
            status_code=400,
            content={"error": f"Invalid fast_mode_type: {request.fast_mode_type}. Must be 'internal' or 'udp_repeater'"}
        )

    if not state.set_room_fast_mode_type(room_name, fast_mode_type):
        return JSONResponse(
            status_code=404,
            content={"error": f"Room not found: {room_name}"}
        )

    # Notify WebSocket clients
    await broadcast_state_update()
    await broadcast_rooms_control_update()

    return JSONResponse(content={"status": "ok", "room_name": room_name, "fast_mode_type": fast_mode_type.value})


# --- Plans API ---

@app.get("/api/plans")
async def get_plans():
    """List all available plans."""
    plans = list_plans()
    return JSONResponse(content=[p.to_dict() for p in plans])


@app.get("/api/plans/{plan_id}")
async def get_plan(plan_id: str):
    """Get a specific plan by ID."""
    plan = load_plan(plan_id)
    if not plan:
        return JSONResponse(
            status_code=404,
            content={"error": f"Plan not found: {plan_id}"}
        )
    return JSONResponse(content=plan.to_dict())


@app.post("/api/plans")
async def create_plan(request: PlanCreateRequest):
    """Create a new plan."""
    try:
        plan = save_plan(request.model_dump())
        return JSONResponse(content=plan.to_dict(), status_code=201)
    except PlanValidationError as e:
        return JSONResponse(
            status_code=400,
            content={"error": str(e)}
        )


@app.put("/api/plans/{plan_id}")
async def update_plan(plan_id: str, request: PlanUpdateRequest):
    """Update an existing plan."""
    # Check if plan exists
    existing = load_plan(plan_id)
    if not existing:
        return JSONResponse(
            status_code=404,
            content={"error": f"Plan not found: {plan_id}"}
        )

    try:
        plan = save_plan(request.model_dump(), plan_id=plan_id)
        return JSONResponse(content=plan.to_dict())
    except PlanValidationError as e:
        return JSONResponse(
            status_code=400,
            content={"error": str(e)}
        )


@app.delete("/api/plans/{plan_id}")
async def delete_plan_endpoint(plan_id: str):
    """Delete a plan."""
    if delete_plan(plan_id):
        return JSONResponse(content={"status": "ok", "plan_id": plan_id})
    return JSONResponse(
        status_code=404,
        content={"error": f"Plan not found: {plan_id}"}
    )


# --- WebSocket ---

connected_websockets: set[WebSocket] = set()


@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    """WebSocket endpoint for real-time updates."""
    await websocket.accept()
    connected_websockets.add(websocket)
    logger.info(f"WebSocket client connected. Total: {len(connected_websockets)}")

    try:
        # Send initial state
        state = get_state()
        await websocket.send_json({
            "type": "init",
            "data": state.get_all_device_status()
        })
        # Also send room control states
        await websocket.send_json({
            "type": "rooms_control",
            "data": state.get_all_room_control_states()
        })

        # Handle incoming messages
        while True:
            data = await websocket.receive_json()
            await handle_websocket_message(websocket, data)

    except WebSocketDisconnect:
        logger.info("WebSocket client disconnected")
    except Exception as e:
        logger.error(f"WebSocket error: {e}")
    finally:
        connected_websockets.discard(websocket)


async def handle_websocket_message(websocket: WebSocket, data: dict):
    """Handle incoming WebSocket messages."""
    msg_type = data.get("type")
    state = get_state()

    if msg_type == "set_mode":
        device_id = data.get("device_id")
        mode_str = data.get("mode")
        try:
            mode = DeviceMode(mode_str)
            state.set_device_mode(device_id, mode)
            await broadcast_state_update()
        except ValueError:
            await websocket.send_json({"type": "error", "message": f"Invalid mode: {mode_str}"})

    elif msg_type == "set_static":
        device_id = data.get("device_id")
        values = data.get("values", [])
        if state.set_static_values(device_id, values):
            # Publish to MQTT
            if mqtt_client:
                device_state = state.get_device_status(device_id)
                if device_state and device_state.get("mode") == "static":
                    config = get_config()
                    device_config = config.get_device_by_id(device_id)
                    if device_config:
                        mqtt_client.publish_static(device_config, values)
            await broadcast_state_update()

    elif msg_type == "set_fast":
        device_id = data.get("device_id")
        values = data.get("values", [])
        state.set_fast_values(device_id, values)

    elif msg_type == "set_planned_plan":
        device_id = data.get("device_id")
        plan_id = data.get("plan_id")  # Can be None to unassign
        if plan_id:
            plan = load_plan(plan_id)
            if not plan:
                await websocket.send_json({"type": "error", "message": f"Plan not found: {plan_id}"})
                return
        state.set_device_plan(device_id, plan_id)
        await broadcast_state_update()

    elif msg_type == "set_device_fast_mode_type":
        device_id = data.get("device_id")
        fast_mode_type_str = data.get("fast_mode_type")
        try:
            fast_mode_type = FastModeType(fast_mode_type_str)
            state.set_device_fast_mode_type(device_id, fast_mode_type)
            await broadcast_state_update()
        except ValueError:
            await websocket.send_json({"type": "error", "message": f"Invalid fast_mode_type: {fast_mode_type_str}"})

    elif msg_type == "get_state":
        await websocket.send_json({
            "type": "state",
            "data": state.get_all_device_status()
        })

    elif msg_type == "get_rooms_control":
        await websocket.send_json({
            "type": "rooms_control",
            "data": state.get_all_room_control_states()
        })

    # --- Room-level commands ---

    elif msg_type == "set_room_control_mode":
        room_name = data.get("room_name")
        control_mode_str = data.get("control_mode")
        try:
            control_mode = RoomControlMode(control_mode_str)
            if state.set_room_control_mode(room_name, control_mode):
                # If switching to AUTO, publish to MQTT for devices in static mode
                if control_mode == RoomControlMode.AUTO and mqtt_client:
                    config = get_config()
                    for device_id in state.get_devices_in_room(room_name):
                        device_state = state.get_device_status(device_id)
                        if device_state and device_state.get("mode") == "static":
                            device_config = config.get_device_by_id(device_id)
                            if device_config:
                                mqtt_client.publish_static(device_config, device_state.get("static_values", []))
                await broadcast_state_update()
                await broadcast_rooms_control_update()
            else:
                await websocket.send_json({"type": "error", "message": f"Room not found: {room_name}"})
        except ValueError:
            await websocket.send_json({"type": "error", "message": f"Invalid control_mode: {control_mode_str}"})

    elif msg_type == "set_room_mode":
        room_name = data.get("room_name")
        mode_str = data.get("mode")
        try:
            mode = DeviceMode(mode_str)
            if state.set_room_mode(room_name, mode):
                await broadcast_state_update()
                await broadcast_rooms_control_update()
            else:
                await websocket.send_json({"type": "error", "message": f"Room not found: {room_name}"})
        except ValueError:
            await websocket.send_json({"type": "error", "message": f"Invalid mode: {mode_str}"})

    elif msg_type == "set_room_static":
        room_name = data.get("room_name")
        values = data.get("values", [])
        if state.set_room_static_values(room_name, values):
            # Publish to MQTT for devices in static mode within this room
            if mqtt_client and state.is_room_auto_mode(room_name):
                config = get_config()
                room_state = state.get_room_control_state(room_name)
                if room_state and room_state.mode == DeviceMode.STATIC:
                    for device_id in state.get_devices_in_room(room_name):
                        device_config = config.get_device_by_id(device_id)
                        if device_config:
                            device_values = state.get_effective_static_values(device_id)
                            if device_values:
                                mqtt_client.publish_static(device_config, device_values)
            await broadcast_state_update()
            await broadcast_rooms_control_update()
        else:
            await websocket.send_json({"type": "error", "message": f"Room not found: {room_name}"})

    elif msg_type == "set_room_planned_plan":
        room_name = data.get("room_name")
        plan_id = data.get("plan_id")  # Can be None to unassign
        if plan_id:
            plan = load_plan(plan_id)
            if not plan:
                await websocket.send_json({"type": "error", "message": f"Plan not found: {plan_id}"})
                return
        if state.set_room_planned_plan(room_name, plan_id):
            await broadcast_state_update()
            await broadcast_rooms_control_update()
        else:
            await websocket.send_json({"type": "error", "message": f"Room not found: {room_name}"})

    elif msg_type == "set_room_fast_mode_type":
        room_name = data.get("room_name")
        fast_mode_type_str = data.get("fast_mode_type")
        try:
            fast_mode_type = FastModeType(fast_mode_type_str)
            if state.set_room_fast_mode_type(room_name, fast_mode_type):
                await broadcast_state_update()
                await broadcast_rooms_control_update()
            else:
                await websocket.send_json({"type": "error", "message": f"Room not found: {room_name}"})
        except ValueError:
            await websocket.send_json({"type": "error", "message": f"Invalid fast_mode_type: {fast_mode_type_str}"})


async def broadcast_state_update(force: bool = False):
    """Broadcast state update to all connected WebSocket clients.
    
    Args:
        force: If True, broadcast even if state hasn't changed (used for liveness ticks)
    """
    if not connected_websockets:
        return

    state = get_state()
    
    # Skip broadcast if state hasn't changed (unless forced)
    if not force and not state.has_state_changed():
        return

    state_data = state.get_all_device_status()
    message = {
        "type": "state",
        "data": state_data
    }

    disconnected = set()
    for ws in connected_websockets:
        try:
            await ws.send_json(message)
        except Exception:
            disconnected.add(ws)

    # Clean up disconnected clients
    for ws in disconnected:
        connected_websockets.discard(ws)
    
    # Mark state as broadcast for change detection
    state.mark_broadcast_complete(state_data)


async def broadcast_rooms_control_update():
    """Broadcast room control state update to all connected WebSocket clients."""
    if not connected_websockets:
        return

    state = get_state()
    rooms_data = state.get_all_room_control_states()
    message = {
        "type": "rooms_control",
        "data": rooms_data
    }

    disconnected = set()
    for ws in connected_websockets:
        try:
            await ws.send_json(message)
        except Exception:
            disconnected.add(ws)

    # Clean up disconnected clients
    for ws in disconnected:
        connected_websockets.discard(ws)


# Background task for liveness checking (online->offline transitions)
async def liveness_check_task():
    """Periodically check for online->offline transitions and broadcast if needed."""
    state = get_state()
    while True:
        await asyncio.sleep(3)  # Check every 3 seconds
        
        # Force-check state and broadcast only if there are actual changes
        # This handles devices going offline due to heartbeat timeout
        if state.has_state_changed():
            await broadcast_state_update(force=True)


@app.on_event("startup")
async def start_status_updates():
    """Start the background liveness check task."""
    asyncio.create_task(liveness_check_task())

