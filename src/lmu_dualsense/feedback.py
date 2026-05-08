"""Main feedback loop: polls game telemetry and drives DualSense trigger effects."""

import logging
import signal
import time
from collections.abc import Callable
from dataclasses import dataclass
from typing import Protocol

from lmu_dualsense.config import Config, TriggerConfig
from lmu_dualsense.controller.dualsense import DualSenseController
from lmu_dualsense.controller.effects import (
    RumbleEffect,
    TriggerEffect,
    compute_effects,
    compute_rumble,
)
from lmu_dualsense.steering import VirtualSteering
from lmu_dualsense.telemetry.acc_shm import AccSharedMemoryProvider, acc_shm_path
from lmu_dualsense.telemetry.base import TelemetryState
from lmu_dualsense.telemetry.recorder import Recorder
from lmu_dualsense.telemetry.shm import SharedMemoryProvider, TelemetryNotAvailable, _find_shm_path

logger = logging.getLogger(__name__)

_RETRY_DELAY = 5.0


@dataclass
class AppState:
    """Shared state written by the feedback loop and read by the GUI."""

    config: TriggerConfig
    telemetry: TelemetryState | None = None
    l2_effect: TriggerEffect | None = None
    r2_effect: TriggerEffect | None = None
    rumble_effect: RumbleEffect | None = None
    game: str = "Searching…"
    ctrl_ok: bool = False


class _Provider(Protocol):
    def open(self) -> None: ...
    def close(self) -> None: ...
    def read(self) -> TelemetryState | None: ...


def _detect_provider() -> tuple[_Provider, str]:
    """Return (provider, game_name) for whichever game's shm is present."""
    try:
        _find_shm_path()
        p: _Provider = SharedMemoryProvider()
        p.open()
        return p, "Le Mans Ultimate"
    except TelemetryNotAvailable:
        pass

    if acc_shm_path() is not None:
        p = AccSharedMemoryProvider()
        p.open()
        return p, "Assetto Corsa Competizione"

    raise TelemetryNotAvailable(
        "No supported game found. Start Le Mans Ultimate or Assetto Corsa Competizione "
        "and load into a session, then retry."
    )


def main() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )

    cfg = Config()
    interval = 1.0 / cfg.telemetry.poll_rate_hz

    stopped = False

    def _on_signal(*_: object) -> None:
        nonlocal stopped
        stopped = True
        logger.info("Shutting down…")

    signal.signal(signal.SIGINT, _on_signal)
    signal.signal(signal.SIGTERM, _on_signal)

    logger.info("DualSense feedback starting (%.0f Hz)", cfg.telemetry.poll_rate_hz)

    with DualSenseController() as ctrl:
        _run_loop(ctrl, cfg, interval, lambda: stopped)


def _run_loop(
    ctrl: DualSenseController,
    cfg: Config,
    interval: float,
    should_stop: Callable[[], bool],
    app_state: AppState | None = None,
    recorder: Recorder | None = None,
) -> None:
    provider: _Provider | None = None
    steering: VirtualSteering | None = None

    while not should_stop():
        # Open / close virtual steering device when the enabled flag changes
        if cfg.steering.enabled and steering is None:
            try:
                steering = VirtualSteering(cfg.steering)
                steering.open()
            except Exception as exc:
                logger.warning("Virtual steering unavailable: %s", exc)
                cfg.steering.enabled = False  # prevent retry loop
        elif not cfg.steering.enabled and steering is not None:
            steering.close()
            steering = None

        if provider is None:
            try:
                provider, game_name = _detect_provider()
                logger.info("Detected %s", game_name)
                if app_state is not None:
                    app_state.game = game_name
            except TelemetryNotAvailable as exc:
                if app_state is not None:
                    app_state.game = "Searching…"
                logger.warning("%s  Retrying in %.0f s…", exc, _RETRY_DELAY)
                time.sleep(_RETRY_DELAY)
                continue

        try:
            state = provider.read()
        except TelemetryNotAvailable as exc:
            logger.info("Session ended: %s", exc)
            provider.close()
            provider = None
            if app_state is not None:
                app_state.game = "Searching…"
            continue
        except Exception as exc:
            logger.warning("Telemetry read error (%s) — reopening shared memory", exc)
            provider.close()
            provider = None
            if app_state is not None:
                app_state.game = "Searching…"
            continue

        if app_state is not None:
            app_state.ctrl_ok = ctrl.connected

        if state is not None and ctrl.connected:
            left, right = compute_effects(state, cfg.triggers)
            ctrl.apply(left, right)

            rumble = compute_rumble(state, cfg.rumble)
            ctrl.set_rumble(rumble)

            if app_state is not None:
                app_state.telemetry = state
                app_state.l2_effect = left
                app_state.r2_effect = right
                app_state.rumble_effect = rumble

            if recorder is not None:
                recorder.record(state)

            if time.time() % 1.0 < interval:
                front_grip = min(state.wheel_grip[0], state.wheel_grip[1])
                abs_on = state.abs_active or (
                    state.brake > 0.1 and front_grip < cfg.triggers.abs_grip_threshold
                )
                logger.info(
                    "Brake: %.2f | ABS: %s | Front Grip: %.2f | Rear Grip: %.2f | Speed: %.0f km/h",
                    state.brake,
                    "Y" if abs_on else "N",
                    front_grip,
                    min(state.wheel_grip[2], state.wheel_grip[3]),
                    state.speed_ms * 3.6,
                )
        elif ctrl.connected:
            ctrl.reset_feedback()

        if steering is not None and ctrl.connected:
            speed = state.speed_ms if state is not None else 0.0
            steering.update(ctrl.gyro_yaw, speed)

        time.sleep(interval)

    if steering is not None:
        steering.close()
    if provider is not None:
        provider.close()
