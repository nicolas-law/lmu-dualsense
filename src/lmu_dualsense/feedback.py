"""Main feedback loop: polls rF2 telemetry and drives DualSense trigger effects."""

import logging
import signal
import time
from collections.abc import Callable

from lmu_dualsense.config import Config
from lmu_dualsense.controller.dualsense import DualSenseController
from lmu_dualsense.controller.effects import compute_effects
from lmu_dualsense.telemetry.shm import SharedMemoryProvider, TelemetryNotAvailable

logger = logging.getLogger(__name__)

_RETRY_DELAY = 5.0   # seconds to wait before retrying a failed shm open


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

    logger.info("LMU DualSense feedback starting (%.0f Hz)", cfg.telemetry.poll_rate_hz)

    with DualSenseController() as ctrl:
        _run_loop(ctrl, cfg, interval, lambda: stopped)


def _run_loop(
    ctrl: DualSenseController,
    cfg: Config,
    interval: float,
    should_stop: Callable[[], bool],
) -> None:
    provider: SharedMemoryProvider | None = None

    while not should_stop():
        if provider is None:
            try:
                provider = SharedMemoryProvider()
                provider.open()
                logger.info("rF2 shared memory opened")
            except TelemetryNotAvailable as exc:
                logger.warning("%s  Retrying in %.0f s…", exc, _RETRY_DELAY)
                time.sleep(_RETRY_DELAY)
                continue

        try:
            state = provider.read()
        except Exception as exc:
            logger.warning("Telemetry read error (%s) — reopening shared memory", exc)
            provider.close()
            provider = None
            continue

        if state is not None and ctrl.connected:
            left, right = compute_effects(state, cfg.triggers)
            ctrl.apply(left, right)

        time.sleep(interval)

    if provider is not None:
        provider.close()
