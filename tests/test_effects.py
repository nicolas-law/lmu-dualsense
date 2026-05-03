"""Unit tests for trigger effect calculations — no controller hardware required."""

import pytest
from pydualsense import TriggerModes

from lmu_dualsense.config import RumbleConfig, TriggerConfig
from lmu_dualsense.controller.effects import RumbleEffect, TriggerEffect, compute_effects, compute_rumble
from lmu_dualsense.telemetry.base import TelemetryState

_CFG = TriggerConfig()
_RCFG = RumbleConfig()


def _state(
    throttle: float = 0.0,
    brake: float = 0.0,
    wheel_grip: tuple[float, float, float, float] = (0.0, 0.0, 0.0, 0.0),
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
# Rigid mode layout: forces[0]=start, forces[1]=end, forces[2]=strength.
# ---------------------------------------------------------------------------


class TestBrakeEffect:
    def test_idle_is_off(self) -> None:
        left, _ = compute_effects(_state(), _CFG)
        assert left.mode == TriggerModes.Rigid
        assert left.forces[1] == 0

    def test_easy_zone_is_flat(self) -> None:
        # Any brake above 2% but below threshold stays at brake_easy_resistance
        for brake in (0.1, 0.25, 0.40, _CFG.brake_threshold):
            left, _ = compute_effects(_state(brake=brake), _CFG)
            assert left.mode == TriggerModes.Rigid
            assert left.forces[1] == _CFG.brake_easy_resistance

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

    def test_abs_pulse_when_front_wheels_slide(self) -> None:
        grip = _CFG.abs_grip_threshold + 0.05
        left, _ = compute_effects(_state(brake=0.8, wheel_grip=(grip, grip, 0.0, 0.0)), _CFG)
        assert left.mode == TriggerModes.Pulse

    def test_abs_pulse_when_abs_active_flag(self) -> None:
        left, _ = compute_effects(_state(brake=0.8, abs_active=True), _CFG)
        assert left.mode == TriggerModes.Pulse

    def test_no_abs_when_grip_below_threshold(self) -> None:
        grip = _CFG.abs_grip_threshold - 0.05
        left, _ = compute_effects(_state(brake=0.9, wheel_grip=(grip, grip, 0.0, 0.0)), _CFG)
        assert left.mode == TriggerModes.Rigid

    def test_no_abs_when_brake_too_light(self) -> None:
        grip = _CFG.abs_grip_threshold + 0.1
        left, _ = compute_effects(_state(brake=0.05, wheel_grip=(grip, grip, 0.0, 0.0)), _CFG)
        assert left.mode == TriggerModes.Rigid


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

    def test_wheelspin_pulse_when_rear_slides(self) -> None:
        grip = _CFG.wheelspin_grip_threshold + 0.05
        _, right = compute_effects(_state(throttle=0.9, wheel_grip=(0.0, 0.0, grip, grip)), _CFG)
        assert right.mode == TriggerModes.Pulse

    def test_no_wheelspin_below_threshold(self) -> None:
        grip = _CFG.wheelspin_grip_threshold - 0.05
        _, right = compute_effects(_state(throttle=0.9, wheel_grip=(0.0, 0.0, grip, grip)), _CFG)
        assert right.mode == TriggerModes.Rigid

    def test_no_wheelspin_at_low_throttle(self) -> None:
        grip = _CFG.wheelspin_grip_threshold + 0.1
        _, right = compute_effects(_state(throttle=0.2, wheel_grip=(0.0, 0.0, grip, grip)), _CFG)
        assert right.mode == TriggerModes.Rigid


# ---------------------------------------------------------------------------
# Grip rumble
# ---------------------------------------------------------------------------


class TestRumbleEffect:
    def test_no_slip_no_rumble(self) -> None:
        r = compute_rumble(_state(), _RCFG)
        # Engine drone only (engine_rpm=6000, max=12000 → 0.5 * 20 = 10)
        assert r.left == r.right == 10

    def test_disabled_returns_zero(self) -> None:
        cfg = RumbleConfig(enabled=False)
        r = compute_rumble(_state(), cfg)
        assert r == RumbleEffect(left=0, right=0)

    def test_below_threshold_no_grip_rumble(self) -> None:
        slip = _RCFG.grip_threshold - 0.01
        r = compute_rumble(_state(wheel_grip=(slip, slip, slip, slip)), _RCFG)
        # Only engine drone
        assert r.left == r.right

    def test_full_slide_left_side(self) -> None:
        r = compute_rumble(_state(wheel_grip=(1.0, 0.0, 1.0, 0.0)), _RCFG)
        assert r.left > r.right

    def test_full_slide_right_side(self) -> None:
        r = compute_rumble(_state(wheel_grip=(0.0, 1.0, 0.0, 1.0)), _RCFG)
        assert r.right > r.left

    def test_full_slide_both_sides(self) -> None:
        r = compute_rumble(_state(wheel_grip=(1.0, 1.0, 1.0, 1.0)), _RCFG)
        assert r.left == r.right
        assert r.left >= _RCFG.grip_max_intensity

    def test_rear_only_slip_fires(self) -> None:
        slip = _RCFG.grip_threshold + 0.1
        r = compute_rumble(_state(wheel_grip=(0.0, 0.0, slip, slip)), _RCFG)
        assert r.left > 0 and r.right > 0

    def test_front_only_slip_fires(self) -> None:
        slip = _RCFG.grip_threshold + 0.1
        r = compute_rumble(_state(wheel_grip=(slip, slip, 0.0, 0.0)), _RCFG)
        assert r.left > 0 and r.right > 0

    def test_clamped_to_255(self) -> None:
        cfg = RumbleConfig(grip_max_intensity=255, engine_max_intensity=255)
        r = compute_rumble(_state(wheel_grip=(1.0, 1.0, 1.0, 1.0)), cfg)
        assert r.left <= 255 and r.right <= 255

    def test_intensity_scales_with_slip(self) -> None:
        slip_lo = _RCFG.grip_threshold + 0.05
        slip_hi = _RCFG.grip_threshold + 0.40
        r_lo = compute_rumble(_state(wheel_grip=(slip_lo, slip_lo, 0.0, 0.0)), _RCFG)
        r_hi = compute_rumble(_state(wheel_grip=(slip_hi, slip_hi, 0.0, 0.0)), _RCFG)
        assert r_hi.left > r_lo.left


# ---------------------------------------------------------------------------
# ABS pulse scaling
# ---------------------------------------------------------------------------


class TestAbsPulseScaling:
    def test_abs_pulse_at_threshold_is_lighter_than_full_slide(self) -> None:
        threshold = _CFG.abs_grip_threshold
        mild_grip = threshold + 0.01
        full_grip = 0.99
        mild, _ = compute_effects(_state(brake=0.8, wheel_grip=(mild_grip, mild_grip, 0.0, 0.0)), _CFG)
        hard, _ = compute_effects(_state(brake=0.8, wheel_grip=(full_grip, full_grip, 0.0, 0.0)), _CFG)
        assert mild.mode == TriggerModes.Pulse
        assert hard.mode == TriggerModes.Pulse
        assert hard.forces[1] > mild.forces[1]

    def test_wheelspin_pulse_scales_with_rear_grip(self) -> None:
        threshold = _CFG.wheelspin_grip_threshold
        mild_grip = threshold + 0.01
        full_grip = 0.99
        _, mild = compute_effects(_state(throttle=0.9, wheel_grip=(0.0, 0.0, mild_grip, mild_grip)), _CFG)
        _, hard = compute_effects(_state(throttle=0.9, wheel_grip=(0.0, 0.0, full_grip, full_grip)), _CFG)
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
