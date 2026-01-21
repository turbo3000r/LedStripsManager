"""Device hardware mode definitions.

Each mode defines the number of channels and their labels/order for a device.
"""

from dataclasses import dataclass
from typing import Optional


@dataclass(frozen=True)
class HardwareMode:
    """Definition of a device hardware mode."""
    mode_id: str
    channels: int
    labels: tuple[str, ...]
    description: str = ""


# --- Mode Registry ---

MODES: dict[str, HardwareMode] = {
    "4ch_v1": HardwareMode(
        mode_id="4ch_v1",
        channels=4,
        labels=("Green", "Yellow", "Blue", "Red"),
        description="4-channel dimmer (Green, Yellow, Blue, Red)",
    ),
    "2ch_v1": HardwareMode(
        mode_id="2ch_v1",
        channels=2,
        labels=("Red+Yellow", "Green+Blue"),
        description="2-channel dimmer with paired colors (output1=Red+Yellow, output2=Green+Blue)",
    ),
    "rgb_v1": HardwareMode(
        mode_id="rgb_v1",
        channels=3,
        labels=("Red", "Green", "Blue"),
        description="RGB LED strip (stub)",
    ),
}

DEFAULT_MODE = "4ch_v1"


def get_mode(mode_id: str) -> Optional[HardwareMode]:
    """Get a hardware mode by ID."""
    return MODES.get(mode_id)


def get_mode_or_default(mode_id: str) -> HardwareMode:
    """Get a hardware mode by ID, falling back to default if not found."""
    return MODES.get(mode_id) or MODES[DEFAULT_MODE]


def channels_for(mode_id: str) -> int:
    """Get the number of channels for a hardware mode."""
    mode = get_mode(mode_id)
    return mode.channels if mode else MODES[DEFAULT_MODE].channels


def labels_for(mode_id: str) -> tuple[str, ...]:
    """Get channel labels for a hardware mode."""
    mode = get_mode(mode_id)
    return mode.labels if mode else MODES[DEFAULT_MODE].labels


def list_modes() -> list[HardwareMode]:
    """List all available hardware modes."""
    return list(MODES.values())

