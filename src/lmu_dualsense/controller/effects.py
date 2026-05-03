"""
Pure-function effect calculations: TelemetryState → trigger / rumble parameters.

No side effects; fully unit-testable without hardware.
"""

from dataclasses import dataclass

from pydualsense import TriggerModes

from lmu_dualsense.config import RumbleConfig, TriggerConfig
from lmu_dualsense.telemetry.base import TelemetryState

# Pulse force bounds for ABS and wheelspin — scaled by slip severity.
_ABS_FORCE_MIN = (60, 20)    # (primary, secondary) at grip threshold
_ABS_FORCE_MAX = (200, 60)   # at full slide
_SPIN_FORCE_MIN = (10, 60)
_SPIN_FORCE_MAX = (40, 200)


@dataclass(frozen=True, slots=True)
class TriggerEffect:
    mode: TriggerModes
    # Maps pydualsense forceID (0–6) to force value (0–255).
    forces: dict[int, int]


@dataclass(frozen=True, slots=True)
class RumbleEffect:
    left: int   # 0-255, left grip motor (FL + RL wheels)
    right: int  # 0-255, right grip motor (FR + RR wheels)


def compute_effects(
    state: TelemetryState, cfg: TriggerConfig
) -> tuple[TriggerEffect, TriggerEffect]:
    """Return (left=brake, right=throttle) trigger effects for the given state."""
    return _brake_effect(state, cfg), _throttle_effect(state, cfg)


def compute_rumble(state: TelemetryState, cfg: RumbleConfig) -> RumbleEffect:
    """Return grip motor intensities derived from per-side wheel slip and engine RPM."""
    if not cfg.enabled:
        return RumbleEffect(left=0, right=0)

    # Per-side: take the worse of front or rear so both lock-up and wheelspin contribute.
    left_slip = max(state.wheel_grip[0], state.wheel_grip[2])   # FL, RL
    right_slip = max(state.wheel_grip[1], state.wheel_grip[3])  # FR, RR

    left_grip = _slip_to_intensity(left_slip, cfg)
    right_grip = _slip_to_intensity(right_slip, cfg)

    rpm_frac = state.engine_rpm / state.engine_max_rpm if state.engine_max_rpm > 0 else 0.0
    engine = int(rpm_frac * cfg.engine_max_intensity)

    return RumbleEffect(
        left=min(left_grip + engine, 255),
        right=min(right_grip + engine, 255),
    )


def _slip_to_intensity(slip: float, cfg: RumbleConfig) -> int:
    if slip <= cfg.grip_threshold:
        return 0
    t = min((slip - cfg.grip_threshold) / (1.0 - cfg.grip_threshold), 1.0)
    return int(t * cfg.grip_max_intensity)


def _brake_effect(state: TelemetryState, cfg: TriggerConfig) -> TriggerEffect:
    front_grip = max(state.wheel_grip[0], state.wheel_grip[1])
    # abs_active is set directly by games that expose the flag (e.g. ACC);
    # fall back to wheel_grip threshold for games that don't (e.g. LMU).
    abs_firing = state.abs_active or (state.brake > 0.1 and front_grip > cfg.abs_grip_threshold)
    if abs_firing:
        t = _slip_fraction(front_grip, cfg.abs_grip_threshold)
        f1 = int(_ABS_FORCE_MIN[0] + t * (_ABS_FORCE_MAX[0] - _ABS_FORCE_MIN[0]))
        f2 = int(_ABS_FORCE_MIN[1] + t * (_ABS_FORCE_MAX[1] - _ABS_FORCE_MIN[1]))
        return TriggerEffect(mode=TriggerModes.Pulse, forces={0: 0, 1: f1, 2: f2})

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
        span = cfg.brake_max_resistance - cfg.brake_easy_resistance
        strength = int(cfg.brake_easy_resistance + t * span)
    # Rigid mode: forces[0]=start position, forces[1]=resistance strength (0-255).
    return TriggerEffect(mode=TriggerModes.Rigid, forces={0: 0, 1: strength})


def _throttle_effect(state: TelemetryState, cfg: TriggerConfig) -> TriggerEffect:
    rear_grip = max(state.wheel_grip[2], state.wheel_grip[3])
    # Wheelspin: driver on throttle and rear wheels are sliding
    if state.throttle > 0.3 and rear_grip > cfg.wheelspin_grip_threshold:
        t = _slip_fraction(rear_grip, cfg.wheelspin_grip_threshold)
        f1 = int(_SPIN_FORCE_MIN[0] + t * (_SPIN_FORCE_MAX[0] - _SPIN_FORCE_MIN[0]))
        f2 = int(_SPIN_FORCE_MIN[1] + t * (_SPIN_FORCE_MAX[1] - _SPIN_FORCE_MIN[1]))
        return TriggerEffect(mode=TriggerModes.Pulse, forces={0: 0, 1: f1, 2: f2})

    strength = cfg.throttle_base_resistance + int(
        state.throttle * (cfg.throttle_max_resistance - cfg.throttle_base_resistance)
    )
    return TriggerEffect(mode=TriggerModes.Rigid, forces={0: 0, 1: strength})


def _slip_fraction(slip: float, threshold: float) -> float:
    """Normalise slip to 0–1 range above threshold, clamped."""
    return min((slip - threshold) / (1.0 - threshold), 1.0)
