"""MQTT client with auto-reconnect and heartbeat subscription."""

import json
import logging
import threading
import time
from typing import Optional

import paho.mqtt.client as mqtt

from app.config import AppConfig, DeviceConfig
from app.state import SharedState

logger = logging.getLogger(__name__)


class MqttClient:
    """MQTT client wrapper with auto-reconnect and heartbeat handling."""

    def __init__(self, config: AppConfig, state: SharedState):
        self._config = config
        self._state = state
        self._client: Optional[mqtt.Client] = None
        self._running = False
        self._thread: Optional[threading.Thread] = None
        self._reconnect_delay = config.mqtt.reconnect_delay_min
        self._lock = threading.Lock()

        # Build topic to device_id mapping for heartbeats
        self._heartbeat_topics: dict[str, str] = {}
        for device in config.get_all_devices():
            if device.topics.heartbeat:
                self._heartbeat_topics[device.topics.heartbeat] = device.device_id

    def start(self) -> None:
        """Start the MQTT client in a background thread."""
        if self._running:
            return

        self._running = True
        self._thread = threading.Thread(target=self._run_loop, daemon=True)
        self._thread.start()

    def stop(self) -> None:
        """Stop the MQTT client."""
        self._running = False
        with self._lock:
            if self._client:
                try:
                    self._client.disconnect()
                    self._client.loop_stop()
                except Exception as e:
                    logger.warning(f"Error during MQTT disconnect: {e}")
        if self._thread:
            self._thread.join(timeout=5)

    def _run_loop(self) -> None:
        """Main loop for MQTT connection management."""
        while self._running:
            try:
                self._connect()
                # Run network loop (blocking with timeout)
                while self._running and self._client:
                    self._client.loop(timeout=1.0)
            except Exception as e:
                logger.error(f"MQTT connection error: {e}")
                self._state.increment_mqtt_error()
                self._state.set_mqtt_connected(False)
                self._backoff_reconnect()

    def _connect(self) -> None:
        """Establish MQTT connection."""
        with self._lock:
            # Create new client
            self._client = mqtt.Client(
                client_id=self._config.mqtt.client_id,
                callback_api_version=mqtt.CallbackAPIVersion.VERSION2,
            )

            # Set callbacks
            self._client.on_connect = self._on_connect
            self._client.on_disconnect = self._on_disconnect
            self._client.on_message = self._on_message

            # Connect
            logger.info(f"Connecting to MQTT broker at {self._config.mqtt.broker_host}:{self._config.mqtt.broker_port}")
            self._client.connect(
                self._config.mqtt.broker_host,
                self._config.mqtt.broker_port,
                keepalive=60
            )

    def _on_connect(self, client, userdata, flags, reason_code, properties=None):
        """Handle successful connection."""
        if reason_code == 0:
            logger.info("Connected to MQTT broker")
            self._state.set_mqtt_connected(True)
            self._reconnect_delay = self._config.mqtt.reconnect_delay_min

            # Subscribe to all heartbeat topics
            for topic in self._heartbeat_topics.keys():
                client.subscribe(topic)
                logger.debug(f"Subscribed to heartbeat topic: {topic}")
        else:
            logger.error(f"MQTT connection failed with code: {reason_code}")
            self._state.set_mqtt_connected(False)

    def _on_disconnect(self, client, userdata, disconnect_flags, reason_code, properties=None):
        """Handle disconnection."""
        logger.warning(f"Disconnected from MQTT broker (code: {reason_code})")
        self._state.set_mqtt_connected(False)

    def _on_message(self, client, userdata, msg):
        """Handle incoming MQTT messages."""
        topic = msg.topic
        try:
            # Check if this is a heartbeat message
            if topic in self._heartbeat_topics:
                device_id = self._heartbeat_topics[topic]
                self._state.update_heartbeat(device_id)
                logger.debug(f"Heartbeat received from {device_id}")

                # Try to parse heartbeat payload for additional info
                try:
                    payload = json.loads(msg.payload.decode("utf-8"))
                    # Could extract firmware version, uptime, etc. here
                    logger.debug(f"Heartbeat payload: {payload}")
                except (json.JSONDecodeError, UnicodeDecodeError):
                    # Simple heartbeat without JSON payload is fine
                    pass

        except Exception as e:
            logger.error(f"Error processing MQTT message on {topic}: {e}")

    def _backoff_reconnect(self) -> None:
        """Wait before reconnecting with exponential backoff."""
        if not self._running:
            return

        logger.info(f"Reconnecting in {self._reconnect_delay} seconds...")
        time.sleep(self._reconnect_delay)

        # Exponential backoff with max limit
        self._reconnect_delay = min(
            self._reconnect_delay * 2,
            self._config.mqtt.reconnect_delay_max
        )

    def publish(self, topic: str, payload: str, qos: int = 1) -> bool:
        """Publish a message to an MQTT topic."""
        with self._lock:
            if not self._client or not self._state.is_mqtt_connected():
                logger.warning(f"Cannot publish to {topic}: not connected")
                return False

            try:
                result = self._client.publish(topic, payload, qos=qos)
                if result.rc == mqtt.MQTT_ERR_SUCCESS:
                    logger.debug(f"Published to {topic}: {payload[:100]}...")
                    return True
                else:
                    logger.error(f"Publish failed to {topic}: {result.rc}")
                    return False
            except Exception as e:
                logger.error(f"Publish error to {topic}: {e}")
                return False

    def publish_plan(self, device: DeviceConfig, plan_payload: dict) -> bool:
        """Publish a lighting plan to a device."""
        if not device.topics.set_plan:
            logger.warning(f"No set_plan topic configured for {device.device_id}")
            return False

        payload = json.dumps(plan_payload)
        return self.publish(device.topics.set_plan, payload)

    def publish_static(self, device: DeviceConfig, values: list[int]) -> bool:
        """Publish static brightness values to a device."""
        if not device.topics.set_static:
            logger.warning(f"No set_static topic configured for {device.device_id}")
            return False

        payload = json.dumps({"values": values})
        return self.publish(device.topics.set_static, payload)

    def is_connected(self) -> bool:
        """Check if MQTT is connected."""
        return self._state.is_mqtt_connected()

