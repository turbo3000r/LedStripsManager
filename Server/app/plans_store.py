"""Plans storage and validation for the Lighting Control Hub."""

import json
import logging
import os
import re
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)

# Constants
PLANS_DIR = Path("plans")
VALID_MODES = {"4ch_v1"}
MODE_CHANNEL_COUNT = {"4ch_v1": 4}


@dataclass
class PlanMetadata:
    """Lightweight plan info for listing."""
    plan_id: str
    name: str
    mode: str
    channels: int
    interval_ms: int
    step_count: int
    created_at: float
    updated_at: float

    def to_dict(self) -> dict:
        return {
            "plan_id": self.plan_id,
            "name": self.name,
            "mode": self.mode,
            "channels": self.channels,
            "interval_ms": self.interval_ms,
            "step_count": self.step_count,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
        }


@dataclass
class Plan:
    """Full plan data."""
    plan_id: str
    name: str
    mode: str
    channels: int
    intensity_scale: str
    interval_ms: int
    steps: list[list[int]]
    created_at: float
    updated_at: float

    def to_dict(self) -> dict:
        return {
            "plan_id": self.plan_id,
            "name": self.name,
            "mode": self.mode,
            "channels": self.channels,
            "intensity_scale": self.intensity_scale,
            "interval_ms": self.interval_ms,
            "steps": self.steps,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
        }

    def to_metadata(self) -> PlanMetadata:
        return PlanMetadata(
            plan_id=self.plan_id,
            name=self.name,
            mode=self.mode,
            channels=self.channels,
            interval_ms=self.interval_ms,
            step_count=len(self.steps),
            created_at=self.created_at,
            updated_at=self.updated_at,
        )


class PlanValidationError(Exception):
    """Raised when plan validation fails."""
    pass


def _ensure_plans_dir() -> None:
    """Create plans directory if it doesn't exist."""
    PLANS_DIR.mkdir(exist_ok=True)


def _sanitize_plan_id(plan_id: str) -> str:
    """Sanitize plan ID for use as filename."""
    # Remove any path separators and keep only alphanumeric, dash, underscore
    sanitized = re.sub(r'[^a-zA-Z0-9_-]', '_', plan_id)
    return sanitized[:64]  # Limit length


def _get_plan_path(plan_id: str) -> Path:
    """Get the file path for a plan."""
    safe_id = _sanitize_plan_id(plan_id)
    return PLANS_DIR / f"{safe_id}.json"


def validate_plan(data: dict) -> None:
    """
    Validate plan data.
    
    Raises PlanValidationError if validation fails.
    """
    # Required fields
    required = ["name", "mode", "interval_ms", "steps"]
    for field_name in required:
        if field_name not in data:
            raise PlanValidationError(f"Missing required field: {field_name}")

    # Mode validation
    mode = data.get("mode")
    if mode not in VALID_MODES:
        raise PlanValidationError(f"Invalid mode: {mode}. Must be one of: {VALID_MODES}")

    expected_channels = MODE_CHANNEL_COUNT.get(mode, 4)

    # Channels validation (optional, defaults to mode's channel count)
    channels = data.get("channels", expected_channels)
    if channels != expected_channels:
        raise PlanValidationError(f"Mode {mode} requires {expected_channels} channels, got {channels}")

    # Interval validation
    interval_ms = data.get("interval_ms")
    if not isinstance(interval_ms, int) or interval_ms <= 0:
        raise PlanValidationError(f"interval_ms must be a positive integer, got {interval_ms}")

    # Steps validation
    steps = data.get("steps")
    if not isinstance(steps, list) or len(steps) == 0:
        raise PlanValidationError("steps must be a non-empty list")

    for i, step in enumerate(steps):
        if not isinstance(step, list):
            raise PlanValidationError(f"Step {i} must be a list, got {type(step).__name__}")
        if len(step) != expected_channels:
            raise PlanValidationError(f"Step {i} must have {expected_channels} values, got {len(step)}")
        for j, value in enumerate(step):
            if not isinstance(value, (int, float)):
                raise PlanValidationError(f"Step {i}, channel {j}: value must be a number, got {type(value).__name__}")
            if value < 0 or value > 100:
                raise PlanValidationError(f"Step {i}, channel {j}: value must be 0-100, got {value}")

    # Name validation
    name = data.get("name", "")
    if not isinstance(name, str) or len(name.strip()) == 0:
        raise PlanValidationError("name must be a non-empty string")
    if len(name) > 100:
        raise PlanValidationError("name must be 100 characters or less")


def list_plans() -> list[PlanMetadata]:
    """List all available plans."""
    _ensure_plans_dir()
    plans = []

    for file_path in PLANS_DIR.glob("*.json"):
        try:
            with open(file_path, "r", encoding="utf-8") as f:
                data = json.load(f)
            plan = _dict_to_plan(data)
            plans.append(plan.to_metadata())
        except Exception as e:
            logger.warning(f"Failed to load plan {file_path}: {e}")

    # Sort by updated_at descending
    plans.sort(key=lambda p: p.updated_at, reverse=True)
    return plans


def load_plan(plan_id: str) -> Optional[Plan]:
    """Load a plan by ID."""
    _ensure_plans_dir()
    path = _get_plan_path(plan_id)

    if not path.exists():
        return None

    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        return _dict_to_plan(data)
    except Exception as e:
        logger.error(f"Failed to load plan {plan_id}: {e}")
        return None


def save_plan(data: dict, plan_id: Optional[str] = None) -> Plan:
    """
    Save a plan.
    
    Args:
        data: Plan data dict
        plan_id: Optional existing plan ID (for updates)
        
    Returns:
        The saved Plan
        
    Raises:
        PlanValidationError if validation fails
    """
    _ensure_plans_dir()

    # Validate
    validate_plan(data)

    now = time.time()

    # Determine plan_id
    if plan_id:
        # Update existing
        existing = load_plan(plan_id)
        created_at = existing.created_at if existing else now
        final_id = plan_id
    else:
        # Create new - generate ID from name
        base_id = _sanitize_plan_id(data["name"].lower().replace(" ", "_"))
        final_id = base_id
        counter = 1
        while _get_plan_path(final_id).exists():
            final_id = f"{base_id}_{counter}"
            counter += 1
        created_at = now

    # Normalize steps to integers
    steps = [[int(round(v)) for v in step] for step in data["steps"]]

    plan = Plan(
        plan_id=final_id,
        name=data["name"],
        mode=data["mode"],
        channels=data.get("channels", MODE_CHANNEL_COUNT[data["mode"]]),
        intensity_scale=data.get("intensity_scale", "0-100"),
        interval_ms=data["interval_ms"],
        steps=steps,
        created_at=created_at,
        updated_at=now,
    )

    # Write to file
    path = _get_plan_path(final_id)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(plan.to_dict(), f, indent=2)

    logger.info(f"Saved plan: {final_id}")
    return plan


def delete_plan(plan_id: str) -> bool:
    """Delete a plan by ID."""
    path = _get_plan_path(plan_id)
    if path.exists():
        try:
            path.unlink()
            logger.info(f"Deleted plan: {plan_id}")
            return True
        except Exception as e:
            logger.error(f"Failed to delete plan {plan_id}: {e}")
            return False
    return False


def _dict_to_plan(data: dict) -> Plan:
    """Convert a dict to a Plan object."""
    return Plan(
        plan_id=data.get("plan_id", "unknown"),
        name=data.get("name", "Untitled"),
        mode=data.get("mode", "4ch_v1"),
        channels=data.get("channels", 4),
        intensity_scale=data.get("intensity_scale", "0-100"),
        interval_ms=data.get("interval_ms", 100),
        steps=data.get("steps", []),
        created_at=data.get("created_at", 0),
        updated_at=data.get("updated_at", 0),
    )


class PlanCache:
    """
    Thread-safe cache for plans with mtime-based invalidation.
    
    Used by the planner to avoid re-reading plans from disk every tick.
    """

    def __init__(self, ttl_seconds: float = 5.0):
        self._lock = threading.Lock()
        self._cache: dict[str, tuple[Plan, float, float]] = {}  # plan_id -> (plan, mtime, cached_at)
        self._ttl = ttl_seconds

    def get(self, plan_id: str) -> Optional[Plan]:
        """Get a plan from cache, reloading if stale."""
        with self._lock:
            cached = self._cache.get(plan_id)
            path = _get_plan_path(plan_id)

            if not path.exists():
                # Plan was deleted
                self._cache.pop(plan_id, None)
                return None

            current_mtime = path.stat().st_mtime

            if cached:
                plan, cached_mtime, cached_at = cached
                # Check if file was modified or cache expired
                if cached_mtime == current_mtime and (time.time() - cached_at) < self._ttl:
                    return plan

            # Reload from disk
            plan = load_plan(plan_id)
            if plan:
                self._cache[plan_id] = (plan, current_mtime, time.time())
            return plan

    def invalidate(self, plan_id: str) -> None:
        """Remove a plan from cache."""
        with self._lock:
            self._cache.pop(plan_id, None)

    def clear(self) -> None:
        """Clear the entire cache."""
        with self._lock:
            self._cache.clear()


# Global cache instance
_plan_cache: Optional[PlanCache] = None


def get_plan_cache() -> PlanCache:
    """Get the global plan cache instance."""
    global _plan_cache
    if _plan_cache is None:
        _plan_cache = PlanCache()
    return _plan_cache

