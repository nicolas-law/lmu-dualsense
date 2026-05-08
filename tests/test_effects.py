"""Unit tests for trigger effect calculations — no controller hardware required."""

import pytest
from pydualsense import TriggerModes

from lmu_dualsense.config import RumbleConfig, TriggerConfig
from lmu_dualsense.controller.effects import RumbleEffect, TriggerEffect, compute_effects, compute_rumble
from lmu_dualsense.telemetry.base import TelemetryState

_CFG = TriggerConfig()
_RCFG = RumbleConfig()

# mGripFract: 1.0 = full grip, ~0.0 = full slide.
_FULL_GRIP: tuple[float, float, float, float] = (1.0, 1.0, 1.0, 1.0)
_NO_GRIP: tuple[float, float, float, float] = (0.0, 0.0, 0.0, 0.0)


def _state(
    throttle: float = 0.0,
    brake: float = 0.0,
    wheel_grip: tuple[float, float, float, float] = _FULL_GRIP,
    abs_active: bool = False,
) -> TelemetryState:
    return TelemetryState(
        throttle=throttle,
        brake=brake,
        speed_ms=50.0,
        engine_rpm=6000.0,
        engine_max_rpm=12000.0,
        wheel_grip=wheel_grip,
        abs_active=abs_active,
    )


# ---------------------------------------------------------------------------
# Brake trigger
# ---------------------------------------------------------------------------


class TestBrakeEffect:
    def test_idle_is_off(self) -> None:
        left, _ = compute_effects(_state(), _CFG)
        assert left.mode == TriggerModes.Off

    def test_easy_zone_zero_resistance_is_off(self) -> None:
        # Default brake_easy_resistance=0 → natural spring, not stiff
        for brake in (0.1, 0.25, 0.40, _CFG.brake_threshold):
            left, _ = compute_effects(_state(brake=brake), _CFG)
            assert left.mode == TriggerModes.Off

    def test_easy_zone_nonzero_resistance_is_rigid(self) -> None:
        from lmu_dualsense.config import TriggerConfig
        cfg = TriggerConfig(brake_easy_resistance=50)
        for brake in (0.1, 0.25, 0.40):
            left, _ = compute_effects(_state(brake=brake), cfg)
            assert left.mode == TriggerModes.Rigid
            assert left.forces[1] == 50

    def test_above_threshold_ramps_to_max(self) -> None:
        left, _ = compute_effects(_state(brake=1.0), _CFG)
        assert left.forces[1] == _CFG.brake_max_resistance

    def test_midpoint_above_threshold(self) -> None:
        threshold = _CFG.brake_threshold
        mid = threshold + (1.0 - threshold) / 2
        left, _ = compute_effects(_state(brake=mid), _CFG)
        expected = int(_CFG.brake_easy_resistance + 0.5 * (_CFG.brake_max_resistance - _CFG.brake_easy_resistance))
        assert left.forces[1] == pytest.approx(expected, abs=1)

    def test_rigid_start_position(self) -> None:
        left, _ = compute_effects(_state(brake=0.8), _CFG)
        assert left.forces[0] == 0

    def test_abs_pulse_when_front_grip_drops(self) -> None:
        # Grip drops well below threshold → ABS pulse
        low_grip = _CFG.abs_grip_threshold - 0.20
        left, _ = compute_effects(_state(brake=0.8, wheel_grip=(low_grip, low_grip, 1.0, 1.0)), _CFG)
        assert left.mode == TriggerModes.Pulse

    def test_abs_pulse_when_abs_active_flag(self) -> None:
        left, _ = compute_effects(_state(brake=0.8, abs_active=True), _CFG)
        assert left.mode == TriggerModes.Pulse

    def test_no_abs_when_grip_normal(self) -> None:
        # Grip is high (normal driving) → no ABS pulse
        left, _ = compute_effects(_state(brake=0.9, wheel_grip=_FULL_GRIP), _CFG)
        assert left.mode == TriggerModes.Rigid

    def test_no_abs_when_brake_too_light(self) -> None:
        # Even if grip is low, brake must exceed 0.1 to trigger ABS pulse
        low_grip = _CFG.abs_grip_threshold - 0.20
        left, _ = compute_effects(_state(brake=0.05, wheel_grip=(low_grip, low_grip, 1.0, 1.0)), _CFG)
        assert left.mode != TriggerModes.Pulse


# ---------------------------------------------------------------------------
# Throttle trigger
# ---------------------------------------------------------------------------


class TestThrottleEffect:
    def test_idle_has_base_resistance(self) -> None:
        _, right = compute_effects(_state(), _CFG)
        assert right.mode == TriggerModes.Rigid
        assert right.forces[1] == _CFG.throttle_base_resistance

    def test_partial_throttle_scales_resistance(self) -> None:
        _, right = compute_effects(_state(throttle=0.5), _CFG)
        expected = _CFG.throttle_base_resistance + int(
            0.5 * (_CFG.throttle_max_resistance - _CFG.throttle_base_resistance)
        )
        assert right.forces[1] == expected

    def test_full_throttle_reaches_max(self) -> None:
        _, right = compute_effects(_state(throttle=1.0), _CFG)
        assert right.forces[1] == _CFG.throttle_max_resistance

    def test_rigid_start_position(self) -> None:
        _, right = compute_effects(_state(throttle=0.5), _CFG)
        assert right.forces[0] == 0

    def test_wheelspin_pulse_when_rear_grip_drops(self) -> None:
        low_grip = _CFG.wheelspin_grip_threshold - 0.20
        _, right = compute_effects(_state(throttle=0.9, wheel_grip=(1.0, 1.0, low_grip, low_grip)), _CFG)
        assert right.mode == TriggerModes.Pulse

    def test_no_wheelspin_when_grip_normal(self) -> None:
        _, right = compute_effects(_state(throttle=0.9, wheel_grip=_FULL_GRIP), _CFG)
        assert right.mode == TriggerModes.Rigid

    def test_no_wheelspin_at_low_throttle(self) -> None:
        low_grip = _CFG.wheelspin_grip_threshold - 0.20
        _, right = compute_effects(_state(throttle=0.2, wheel_grip=(1.0, 1.0, low_grip, low_grip)), _CFG)
        assert right.mode == TriggerModes.Rigid


# ---------------------------------------------------------------------------
# Grip rumble
# ---------------------------------------------------------------------------


class TestRumbleEffect:
    def test_full_grip_only_engine_drone(self) -> None:
        r = compute_rumble(_state(wheel_grip=_FULL_GRIP), _RCFG)
        # Only engine drone: 6000/12000 * 20 = 10
        assert r.left == r.right == 10

    def test_disabled_returns_zero(self) -> None:
        cfg = RumbleConfig(enabled=False)
        r = compute_rumble(_state(), cfg)
        assert r == RumbleEffect(left=0, right=0)

    def test_above_threshold_no_grip_rumble(self) -> None:
        # Grip just above threshold → no grip component
        grip = _RCFG.grip_threshold + 0.01
        r = compute_rumble(_state(wheel_grip=(grip, grip, grip, grip)), _RCFG)
        assert r.left == r.right  # only engine drone

    def test_full_slide_left_side(self) -> None:
        r = compute_rumble(_state(wheel_grip=(0.0, 1.0, 0.0, 1.0)), _RCFG)
        assert r.left > r.right

    def test_full_slide_right_side(self) -> None:
        r = compute_rumble(_state(wheel_grip=(1.0, 0.0, 1.0, 0.0)), _RCFG)
        assert r.right > r.left

    def test_full_slide_both_sides(self) -> None:
        r = compute_rumble(_state(wheel_grip=_NO_GRIP), _RCFG)
        assert r.left == r.right
        assert r.left >= _RCFG.grip_max_intensity

    def test_rear_only_slide_fires(self) -> None:
        low_grip = _RCFG.grip_threshold - 0.10
        r = compute_rumble(_state(wheel_grip=(1.0, 1.0, low_grip, low_grip)), _RCFG)
        assert r.left > 0 and r.right > 0

    def test_front_only_slide_fires(self) -> None:
        low_grip = _RCFG.grip_threshold - 0.10
        r = compute_rumble(_state(wheel_grip=(low_grip, low_grip, 1.0, 1.0)), _RCFG)
        assert r.left > 0 and r.right > 0

    def test_clamped_to_255(self) -> None:
        cfg = RumbleConfig(grip_max_intensity=255, engine_max_intensity=255)
        r = compute_rumble(_state(wheel_grip=_NO_GRIP), cfg)
        assert r.left <= 255 and r.right <= 255

    def test_intensity_scales_with_slip(self) -> None:
        grip_lo = _RCFG.grip_threshold - 0.05   # just sliding
        grip_hi = 0.01                            # nearly full slide
        r_lo = compute_rumble(_state(wheel_grip=(grip_lo, grip_lo, 1.0, 1.0)), _RCFG)
        r_hi = compute_rumble(_state(wheel_grip=(grip_hi, grip_hi, 1.0, 1.0)), _RCFG)
        assert r_hi.left > r_lo.left


# ---------------------------------------------------------------------------
# ABS and wheelspin pulse scaling
# ---------------------------------------------------------------------------


class TestPulseScaling:
    def test_abs_pulse_mild_lighter_than_full_lock(self) -> None:
        threshold = _CFG.abs_grip_threshold
        mild_grip = threshold - 0.05   # just below threshold
        full_lock = 0.01               # nearly zero
        mild, _ = compute_effects(_state(brake=0.8, wheel_grip=(mild_grip, mild_grip, 1.0, 1.0)), _CFG)
        hard, _ = compute_effects(_state(brake=0.8, wheel_grip=(full_lock, full_lock, 1.0, 1.0)), _CFG)
        assert mild.mode == TriggerModes.Pulse
        assert hard.mode == TriggerModes.Pulse
        assert hard.forces[1] > mild.forces[1]

    def test_wheelspin_pulse_scales_with_rear_slip(self) -> None:
        threshold = _CFG.wheelspin_grip_threshold
        mild_grip = threshold - 0.05
        full_spin = 0.01
        _, mild = compute_effects(_state(throttle=0.9, wheel_grip=(1.0, 1.0, mild_grip, mild_grip)), _CFG)
        _, hard = compute_effects(_state(throttle=0.9, wheel_grip=(1.0, 1.0, full_spin, full_spin)), _CFG)
        assert mild.mode == TriggerModes.Pulse
        assert hard.mode == TriggerModes.Pulse
        assert hard.forces[2] > mild.forces[2]


# ---------------------------------------------------------------------------
# Effect immutability
# ---------------------------------------------------------------------------


def test_trigger_effect_is_immutable() -> None:
    effect = TriggerEffect(mode=TriggerModes.Rigid, forces={0: 0, 1: 255, 2: 100})
    with pytest.raises((AttributeError, TypeError)):
        effect.mode = TriggerModes.Off  # type: ignore[misc]


def test_rumble_effect_is_immutable() -> None:
    effect = RumbleEffect(left=100, right=200)
    with pytest.raises((AttributeError, TypeError)):
        effect.left = 0  # type: ignore[misc]
