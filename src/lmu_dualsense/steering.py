"""
Speed-scaled gyro steering via a uinput virtual joystick.

The DualSense gyro Yaw axis (signed int16, ±32767 = ±2000 deg/s) is integrated
over time into a steering angle (-1.0 to 1.0) and written to a virtual ABS_X axis.
Sensitivity is linearly interpolated between a low-speed and a high-speed value
based on the car's current speed from telemetry.

The game (LMU / ACC) must have the virtual device bound as the steering axis.
It appears in the controller list as "lmu-dualsense-steering".
"""

import logging
import math
import time

from evdev import AbsInfo, UInput, ecodes

from lmu_dualsense.config import SteeringConfig

logger = logging.getLogger(__name__)

# DualSense gyro: ±32767 raw = ±2000 deg/s
_GYRO_TO_RADS: float = (2000.0 / 32767.0) * (math.pi / 180.0)
_AXIS_MAX = 32767


class VirtualSteering:
    """
    Manages the uinput virtual joystick and integrates gyro into a steering angle.

    Lifecycle mirrors SharedMemoryProvider — call open() before update(), close() when done.
    The SteeringConfig is read each update() call so GUI slider changes take effect immediately.
    """

    def __init__(self, cfg: SteeringConfig) -> None:
        self.cfg = cfg
        self._angle: float = 0.0
        self._last_t: float = time.monotonic()
        self._ui: UInput | None = None

    def open(self) -> None:
        cap = {
            ecodes.EV_ABS: [(ecodes.ABS_X, AbsInfo(0, -_AXIS_MAX, _AXIS_MAX, 16, 128, 0))],
            ecodes.EV_KEY: [ecodes.BTN_SOUTH],  # minimal button so games recognise as gamepad
        }
        self._ui = UInput(cap, name="lmu-dualsense-steering")  # type: ignore[arg-type]
        logger.info("Virtual steering device opened: %s", self._ui.device.path)

    def close(self) -> None:
        if self._ui is not None:
            self._write(0)
            self._ui.close()  # type: ignore[no-untyped-call]
            self._ui = None
            logger.info("Virtual steering device closed")

    def __enter__(self) -> "VirtualSteering":
        self.open()
        return self

    def __exit__(self, *_: object) -> None:
        self.close()

    def update(self, gyro_yaw_raw: int, speed_ms: float) -> None:
        """Integrate one frame of gyro input and push the result to uinput."""
        now = time.monotonic()
        dt = min(now - self._last_t, 0.05)  # cap delta so jumps after pauses don't over-steer
        self._last_t = now

        cfg = self.cfg
        gyro_rads = gyro_yaw_raw * _GYRO_TO_RADS

        # Linear sensitivity interpolation: low_speed_sens at 0, high_speed_sens at max_speed_ms
        t = min(speed_ms / cfg.max_speed_ms, 1.0) if cfg.max_speed_ms > 0 else 0.0
        sens = cfg.sens_low_speed + (cfg.sens_high_speed - cfg.sens_low_speed) * t

        if abs(gyro_rads) > cfg.dead_zone_rads:
            self._angle = max(-1.0, min(1.0, self._angle + gyro_rads * sens * dt))
        else:
            # Controller is still — spring back toward centre
            decay = max(0.0, 1.0 - cfg.return_rate * dt)
            self._angle *= decay

        self._write(int(self._angle * _AXIS_MAX))

    def _write(self, value: int) -> None:
        if self._ui is not None:
            self._ui.write(ecodes.EV_ABS, ecodes.ABS_X, value)
            self._ui.syn()  # type: ignore[no-untyped-call]
