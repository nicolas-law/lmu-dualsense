"""
Pure-function effect calculations: TelemetryState → trigger parameters.

No side effects; fully unit-testable without hardware.
"""

from dataclasses import dataclass

from pydualsense import TriggerModes

from lmu_dualsense.config import TriggerConfig
from lmu_dualsense.telemetry.base import TelemetryState


@dataclass(frozen=True, slots=True)
class TriggerEffect:
    mode: TriggerModes
    # Maps pydualsense forceID (0–6) to force value (0–255).
    forces: dict[int, int]


def compute_effects(
    state: TelemetryState, cfg: TriggerConfig
) -> tuple[TriggerEffect, TriggerEffect]:
    """Return (left=brake, right=throttle) trigger effects for the given state."""
    return _brake_effect(state, cfg), _throttle_effect(state, cfg)


def _brake_effect(state: TelemetryState, cfg: TriggerConfig) -> TriggerEffect:
    front_grip = max(state.wheel_grip[0], state.wheel_grip[1])
    # ABS condition: driver is braking and front wheels are sliding
    if state.brake > 0.1 and front_grip > cfg.abs_grip_threshold:
        return TriggerEffect(mode=TriggerModes.Pulse, forces={0: 0, 1: 8, 2: 30})

    strength = int(state.brake * cfg.brake_max_resistance)
    return TriggerEffect(mode=TriggerModes.Rigid, forces={0: 0, 1: strength})


def _throttle_effect(state: TelemetryState, cfg: TriggerConfig) -> TriggerEffect:
    rear_grip = max(state.wheel_grip[2], state.wheel_grip[3])
    # Wheelspin: driver on throttle and rear wheels are sliding
    if state.throttle > 0.3 and rear_grip > cfg.wheelspin_grip_threshold:
        return TriggerEffect(mode=TriggerModes.Pulse, forces={0: 0, 1: 8, 2: 20})

    strength = cfg.throttle_base_resistance + int(
        state.throttle * (cfg.throttle_max_resistance - cfg.throttle_base_resistance)
    )
    return TriggerEffect(mode=TriggerModes.Rigid, forces={0: 0, 1: strength})
