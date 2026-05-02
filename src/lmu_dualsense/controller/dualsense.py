"""
DualSense lifecycle wrapper.

Encapsulates pydualsense so the rest of the codebase stays decoupled from it.
Effect changes are applied only when the value actually changes, avoiding
redundant HID writes on every loop tick.
"""

import logging

from pydualsense import TriggerModes, pydualsense

from lmu_dualsense.controller.effects import TriggerEffect

logger = logging.getLogger(__name__)

_TRIGGER_OFF = TriggerEffect(mode=TriggerModes.Off, forces={})


class DualSenseController:
    """
    Manages a single DualSense connection.

    Supports use as a context manager::

        with DualSenseController() as ctrl:
            ctrl.apply(left_effect, right_effect)
    """

    def __init__(self) -> None:
        self._ds: pydualsense | None = None
        self._last_left: TriggerEffect | None = None
        self._last_right: TriggerEffect | None = None

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    def open(self) -> None:
        self._ds = pydualsense(verbose=False)
        self._ds.init()
        logger.info("DualSense connected")

    def close(self) -> None:
        if self._ds is None:
            return
        try:
            _apply_effect(self._ds.triggerL, _TRIGGER_OFF)
            _apply_effect(self._ds.triggerR, _TRIGGER_OFF)
            self._ds.close()
        except Exception:  # noqa: BLE001
            pass
        self._ds = None
        self._last_left = None
        self._last_right = None
        logger.info("DualSense disconnected")

    def __enter__(self) -> "DualSenseController":
        self.open()
        return self

    def __exit__(self, *_: object) -> None:
        self.close()

    # ------------------------------------------------------------------
    # State
    # ------------------------------------------------------------------

    @property
    def connected(self) -> bool:
        return self._ds is not None and bool(getattr(self._ds, "connected", False))

    @property
    def gyro_yaw(self) -> int:
        """Raw signed-int16 yaw rate from the DualSense IMU (0 when disconnected)."""
        if self._ds is None:
            return 0
        return int(self._ds.state.gyro.Yaw)

    # ------------------------------------------------------------------
    # Feedback
    # ------------------------------------------------------------------

    def apply(self, left: TriggerEffect, right: TriggerEffect) -> None:
        """Write trigger effects to the controller, skipping unchanged values."""
        if self._ds is None:
            return

        if left != self._last_left:
            _apply_effect(self._ds.triggerL, left)
            self._last_left = left

        if right != self._last_right:
            _apply_effect(self._ds.triggerR, right)
            self._last_right = right


def _apply_effect(trigger: object, effect: TriggerEffect) -> None:
    trigger.setMode(effect.mode)  # type: ignore[union-attr]
    for force_id, value in effect.forces.items():
        trigger.setForce(force_id, value)  # type: ignore[union-attr]
