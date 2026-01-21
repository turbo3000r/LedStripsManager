"""Planner loop for generating and publishing lighting plans."""

import logging
import math
import threading
import time
from typing import Optional

from app.config import AppConfig
from app.state import SharedState, DeviceMode
from app.mqtt_client import MqttClient
from app.plans_store import get_plan_cache, Plan

logger = logging.getLogger(__name__)


class PlannerLoop:
    """
    Planner that generates and publishes lighting plans for devices in 'planned' mode.
    
    Plans are generated for T+1 (the next interval) to ensure ESPs have data
    before they need it (latency compensation).
    
    Timestamps are UTC Unix timestamps (seconds since epoch). ESP devices must
    also use UTC (configTime(0, 0, ...)) for proper synchronization.
    """

    def __init__(self, config: AppConfig, state: SharedState, mqtt_client: MqttClient):
        self._config = config
        self._state = state
        self._mqtt = mqtt_client
        self._running = False
        self._thread: Optional[threading.Thread] = None
        self._plan_cache = get_plan_cache()
        # Track step index per device for looping through plan steps
        self._device_step_index: dict[str, int] = {}

    def start(self) -> None:
        """Start the planner loop in a background thread."""
        if self._running:
            return

        self._running = True
        self._thread = threading.Thread(target=self._run_loop, daemon=True)
        self._thread.start()

    def stop(self) -> None:
        """Stop the planner loop."""
        self._running = False
        if self._thread:
            self._thread.join(timeout=5)

    def _run_loop(self) -> None:
        """Main planner loop - runs every interval_sec."""
        interval = self._config.planner.interval_sec
        logger.info(f"Planner loop started with interval: {interval}s")

        while self._running:
            loop_start = time.time()

            try:
                self._process_planned_devices()
            except Exception as e:
                logger.error(f"Planner loop error: {e}")

            # Sleep for the remainder of the interval
            elapsed = time.time() - loop_start
            sleep_time = max(0, interval - elapsed)
            if sleep_time > 0:
                time.sleep(sleep_time)

    def _process_planned_devices(self) -> None:
        """Generate and publish plans for all devices in 'planned' mode."""
        # Get devices in planned mode
        planned_device_ids = self._state.get_devices_by_mode(DeviceMode.PLANNED)

        if not planned_device_ids:
            return

        # Calculate timestamp for T+1 (next interval)
        # Note: time.time() returns UTC Unix timestamp (seconds since epoch)
        # ESP devices must also use UTC (configTime(0, 0, ...)) for synchronization
        current_time = time.time()
        interval = self._config.planner.interval_sec
        
        # Round up to next interval boundary for T+1
        next_interval_start = math.ceil(current_time / interval) * interval + interval
        timestamp = int(next_interval_start)  # UTC Unix timestamp

        for device_id in planned_device_ids:
            try:
                self._publish_plan_for_device(device_id, timestamp)
            except Exception as e:
                logger.error(f"Failed to publish plan for {device_id}: {e}")
                self._state.increment_device_error(device_id)

    def _publish_plan_for_device(self, device_id: str, timestamp: int) -> None:
        """Generate and publish a plan for a single device."""
        device_config = self._config.get_device_by_id(device_id)
        if not device_config:
            logger.warning(f"Device config not found: {device_id}")
            return

        device_state = self._state.get_device_state(device_id)
        if not device_state:
            logger.warning(f"Device state not found: {device_id}")
            return

        # Get the selected plan for this device
        plan_id = self._state.get_device_plan(device_id)
        
        if plan_id:
            # Use the selected plan
            plan = self._plan_cache.get(plan_id)
            if plan:
                sequence, interval_ms = self._get_plan_sequence(device_id, plan)
            else:
                logger.warning(f"Plan not found for device {device_id}: {plan_id}")
                # Fallback to static values
                sequence = self._generate_sequence(device_state.static_values)
                interval_ms = self._config.planner.interval_ms
        else:
            # No plan selected - use static values
            sequence = self._generate_sequence(device_state.static_values)
            interval_ms = self._config.planner.interval_ms

        # Build the plan payload based on configured version
        payload_version = self._config.planner.plan_payload_version
        
        if payload_version == 2:
            # V2 format: per-step absolute timestamps with values
            start_ms = timestamp * 1000  # Convert seconds to milliseconds
            steps = []
            for i, values in enumerate(sequence):
                steps.append({
                    "ts_ms": start_ms + (i * interval_ms),
                    "values": values
                })
            plan_payload = {
                "format_version": 2,
                "steps": steps
            }
        else:
            # V1 format: legacy packed format (timestamp + interval_ms + sequence)
            plan_payload = {
                "timestamp": timestamp,
                "interval_ms": interval_ms,
                "sequence": sequence,
            }

        # Publish via MQTT
        success = self._mqtt.publish_plan(device_config, plan_payload)
        if success:
            logger.debug(f"Published plan v{payload_version} for {device_id}: timestamp={timestamp}")
        else:
            logger.warning(f"Failed to publish plan for {device_id}")
            self._state.increment_device_error(device_id)

    def _get_plan_sequence(self, device_id: str, plan: Plan) -> tuple[list[list[int]], int]:
        """
        Get the next sequence of steps from the plan for this device.
        
        Loops through the plan's steps, advancing the step index each tick.
        Converts intensity from 0-100 to 0-255 for devices.
        
        Returns:
            Tuple of (sequence, interval_ms)
        """
        steps_per_interval = self._config.planner.steps_per_interval
        
        # Get or initialize step index for this device
        if device_id not in self._device_step_index:
            self._device_step_index[device_id] = 0
        
        current_index = self._device_step_index[device_id]
        plan_steps = plan.steps
        num_plan_steps = len(plan_steps)
        
        if num_plan_steps == 0:
            # Empty plan, return zeros
            return [[0] * plan.channels for _ in range(steps_per_interval)], plan.interval_ms
        
        # Extract the next steps_per_interval steps from the plan, wrapping around
        sequence = []
        for i in range(steps_per_interval):
            step_idx = (current_index + i) % num_plan_steps
            raw_step = plan_steps[step_idx]
            # Convert 0-100 to 0-255
            converted_step = [int(round(v * 255 / 100)) for v in raw_step]
            sequence.append(converted_step)
        
        # Advance the step index for next tick
        self._device_step_index[device_id] = (current_index + steps_per_interval) % num_plan_steps
        
        return sequence, plan.interval_ms

    def _generate_sequence(self, target_values: list[int]) -> list[list[int]]:
        """
        Generate a sequence of brightness values for the interval.
        
        This is a simple implementation that holds the target values constant.
        More sophisticated implementations could:
        - Interpolate between current and target values
        - Apply easing functions
        - Follow a schedule/scene timeline
        
        Returns:
            List of [ch0, ch1, ...] values for each step in the interval.
            Length = steps_per_interval
        """
        steps = self._config.planner.steps_per_interval

        # For now, just repeat the target values for all steps
        # Each step is a list of channel values
        sequence = []
        for _ in range(steps):
            sequence.append(target_values.copy())

        return sequence

    def generate_transition_sequence(
        self,
        start_values: list[int],
        end_values: list[int],
        steps: Optional[int] = None
    ) -> list[list[int]]:
        """
        Generate a smooth transition sequence from start to end values.
        
        Args:
            start_values: Starting brightness values per channel
            end_values: Ending brightness values per channel
            steps: Number of steps (defaults to config value)
            
        Returns:
            List of [ch0, ch1, ...] values for each step
        """
        if steps is None:
            steps = self._config.planner.steps_per_interval

        if len(start_values) != len(end_values):
            raise ValueError("start_values and end_values must have same length")

        num_channels = len(start_values)
        sequence = []

        for step in range(steps):
            # Linear interpolation
            t = step / (steps - 1) if steps > 1 else 1.0
            step_values = []
            for ch in range(num_channels):
                value = int(start_values[ch] + t * (end_values[ch] - start_values[ch]))
                value = max(0, min(255, value))
                step_values.append(value)
            sequence.append(step_values)

        return sequence

    def generate_eased_sequence(
        self,
        start_values: list[int],
        end_values: list[int],
        steps: Optional[int] = None,
        ease_type: str = "ease_in_out"
    ) -> list[list[int]]:
        """
        Generate an eased transition sequence.
        
        Args:
            start_values: Starting brightness values per channel
            end_values: Ending brightness values per channel
            steps: Number of steps (defaults to config value)
            ease_type: Type of easing ("linear", "ease_in", "ease_out", "ease_in_out")
            
        Returns:
            List of [ch0, ch1, ...] values for each step
        """
        if steps is None:
            steps = self._config.planner.steps_per_interval

        if len(start_values) != len(end_values):
            raise ValueError("start_values and end_values must have same length")

        num_channels = len(start_values)
        sequence = []

        for step in range(steps):
            # Calculate normalized time (0 to 1)
            t = step / (steps - 1) if steps > 1 else 1.0
            
            # Apply easing function
            if ease_type == "ease_in":
                t = t * t
            elif ease_type == "ease_out":
                t = 1 - (1 - t) * (1 - t)
            elif ease_type == "ease_in_out":
                if t < 0.5:
                    t = 2 * t * t
                else:
                    t = 1 - (-2 * t + 2) ** 2 / 2
            # else: linear, no modification

            step_values = []
            for ch in range(num_channels):
                value = int(start_values[ch] + t * (end_values[ch] - start_values[ch]))
                value = max(0, min(255, value))
                step_values.append(value)
            sequence.append(step_values)

        return sequence

