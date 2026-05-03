"""
Pure-function effect calculations: TelemetryState → trigger / rumble parameters.

No side effects; fully unit-testable without hardware.

mGripFract convention: 1.0 = full grip, ~0.0 = full slide.
Effects fire when grip DROPS below a threshold (i.e. grip < threshold).
"""

from dataclasses import dataclass

from pydualsense import TriggerModes

from lmu_dualsense.config import RumbleConfig, TriggerConfig
from lmu_dualsense.telemetry.base import TelemetryState

# Pulse force bounds for ABS and wheelspin — scaled by slip severity.
_ABS_FORCE_MIN = (60, 20)    # (primary, secondary) at grip threshold
_ABS_FORCE_MAX = (200, 60)   # at full slide (grip = 0)
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
    """Return grip motor intensities derived from per-side wheel grip and engine RPM."""
    if not cfg.enabled:
        return RumbleEffect(left=0, right=0)

    # Per-side: worst (lowest) grip of front or rear on each side.
    left_grip = min(state.wheel_grip[0], state.wheel_grip[2])   # FL, RL
    right_grip = min(state.wheel_grip[1], state.wheel_grip[3])  # FR, RR

    left_intensity = _grip_to_intensity(left_grip, cfg)
    right_intensity = _grip_to_intensity(right_grip, cfg)

    rpm_frac = state.engine_rpm / state.engine_max_rpm if state.engine_max_rpm > 0 else 0.0
    engine = int(rpm_frac * cfg.engine_max_intensity)

    return RumbleEffect(
        left=min(left_intensity + engine, 255),
        right=min(right_intensity + engine, 255),
    )


def _grip_to_intensity(grip: float, cfg: RumbleConfig) -> int:
    """Map grip fraction to rumble intensity: fires when grip drops below threshold."""
    if grip >= cfg.grip_threshold:
        return 0
    t = min((cfg.grip_threshold - grip) / cfg.grip_threshold, 1.0)
    return int(t * cfg.grip_max_intensity)


def _brake_effect(state: TelemetryState, cfg: TriggerConfig) -> TriggerEffect:
    front_grip = min(state.wheel_grip[0], state.wheel_grip[1])
    # abs_active: set directly by games that expose the flag (e.g. ACC).
    # Fallback for LMU: grip drops below threshold during braking = lock-up detected.
    abs_firing = state.abs_active or (state.brake > 0.1 and front_grip < cfg.abs_grip_threshold)
    if abs_firing:
        t = _grip_loss_fraction(front_grip, cfg.abs_grip_threshold)
        if state.abs_active:
            t = max(0.3, t)  # ensure perceptible pulse when game reports ABS directly
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
    return TriggerEffect(mode=TriggerModes.Rigid, forces={0: 0, 1: strength})


def _throttle_effect(state: TelemetryState, cfg: TriggerConfig) -> TriggerEffect:
    rear_grip = min(state.wheel_grip[2], state.wheel_grip[3])
    # Wheelspin: driver on throttle and rear wheels are losing grip
    if state.throttle > 0.3 and rear_grip < cfg.wheelspin_grip_threshold:
        t = _grip_loss_fraction(rear_grip, cfg.wheelspin_grip_threshold)
        f1 = int(_SPIN_FORCE_MIN[0] + t * (_SPIN_FORCE_MAX[0] - _SPIN_FORCE_MIN[0]))
        f2 = int(_SPIN_FORCE_MIN[1] + t * (_SPIN_FORCE_MAX[1] - _SPIN_FORCE_MIN[1]))
        return TriggerEffect(mode=TriggerModes.Pulse, forces={0: 0, 1: f1, 2: f2})

    strength = cfg.throttle_base_resistance + int(
        state.throttle * (cfg.throttle_max_resistance - cfg.throttle_base_resistance)
    )
    return TriggerEffect(mode=TriggerModes.Rigid, forces={0: 0, 1: strength})


def _grip_loss_fraction(grip: float, threshold: float) -> float:
    """Normalise grip loss to 0–1 as grip falls below threshold, clamped."""
    if grip >= threshold:
        return 0.0
    return min((threshold - grip) / threshold, 1.0)
