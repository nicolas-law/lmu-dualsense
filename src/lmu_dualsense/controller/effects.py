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
    # abs_active is set directly by games that expose the flag (e.g. ACC);
    # fall back to wheel_grip threshold for games that don't (e.g. LMU).
    abs_firing = state.abs_active or (state.brake > 0.1 and front_grip > cfg.abs_grip_threshold)
    if abs_firing:
        return TriggerEffect(mode=TriggerModes.Pulse, forces={0: 0, 1: 150, 2: 50})

    # Two-zone feel:
    #   easy zone (0 → threshold): flat low/no resistance — brake freely
    #   hard zone (threshold → 1): ramps from easy up to max — prevents over-braking
    b = state.brake
    if b < 0.02:
        strength = 0
    elif b <= cfg.brake_threshold:
        strength = cfg.brake_easy_resistance
    else:
        t = (b - cfg.brake_threshold) / (1.0 - cfg.brake_threshold)
        strength = int(cfg.brake_easy_resistance + t * (cfg.brake_max_resistance - cfg.brake_easy_resistance))
    # Rigid mode: forces[0]=start position, forces[1]=resistance strength (0-255).
    return TriggerEffect(mode=TriggerModes.Rigid, forces={0: 0, 1: strength})


def _throttle_effect(state: TelemetryState, cfg: TriggerConfig) -> TriggerEffect:
    rear_grip = max(state.wheel_grip[2], state.wheel_grip[3])
    # Wheelspin: driver on throttle and rear wheels are sliding
    if state.throttle > 0.3 and rear_grip > cfg.wheelspin_grip_threshold:
        return TriggerEffect(mode=TriggerModes.Pulse, forces={0: 0, 1: 20, 2: 150})

    strength = cfg.throttle_base_resistance + int(
        state.throttle * (cfg.throttle_max_resistance - cfg.throttle_base_resistance)
    )
    return TriggerEffect(mode=TriggerModes.Rigid, forces={0: 0, 1: strength})
