"""
Reads ACC telemetry from the shared memory created by Assetto Corsa Competizione.

On Linux with Proton, Wine exposes Windows named file mappings in /dev/shm/.
ACC creates the mapping as "Local\\acpmf_physics"; Wine strips the namespace
prefix, so the file appears as /dev/shm/acpmf_physics.
"""

import ctypes
import math
import mmap
import os
from pathlib import Path

from lmu_dualsense.telemetry.base import TelemetryState
from lmu_dualsense.telemetry.acc_structs import _AccPhysics

_SHM_NAME = "acpmf_physics"

_SHM_CANDIDATES = [
    f"/dev/shm/{_SHM_NAME}",
    f"/dev/shm/wine_{_SHM_NAME}",
]

_BUFFER_SIZE = ctypes.sizeof(_AccPhysics)

# ACC exposes slip ratio (0 = no slip). Normalise to the same 0→1 "grip loss"
# scale used by the LMU provider so the existing effect thresholds apply.
_SLIP_SCALE = 3.0   # slip ratio above this → treat as full slide (1.0)


class AccTelemetryNotAvailable(Exception):
    """Raised when the ACC shared memory cannot be located."""


def acc_shm_path() -> Path | None:
    """Return the ACC physics shm path if present, else None (no exception)."""
    for candidate in _SHM_CANDIDATES:
        p = Path(candidate)
        if p.exists():
            return p

    shm_dir = Path("/dev/shm")
    for entry in shm_dir.iterdir():
        if _SHM_NAME in entry.name:
            return entry

    return None


class AccSharedMemoryProvider:
    """
    Maps the ACC physics shared memory page and deserialises state on demand.

    Same lifecycle interface as SharedMemoryProvider (LMU):

        with AccSharedMemoryProvider() as p:
            state = p.read()   # None when game is not in a session

    Or explicit open/close.
    """

    def __init__(self) -> None:
        self._mm: mmap.mmap | None = None
        self._fd: int | None = None

    def open(self) -> None:
        path = acc_shm_path()
        if path is None:
            raise AccTelemetryNotAvailable(
                "ACC shared memory not found in /dev/shm/. "
                "Make sure Assetto Corsa Competizione is running in an active session."
            )
        self._fd = os.open(str(path), os.O_RDONLY)
        file_size = os.path.getsize(path)
        map_size = min(file_size, _BUFFER_SIZE)
        self._mm = mmap.mmap(self._fd, map_size, access=mmap.ACCESS_READ)

    def close(self) -> None:
        if self._mm is not None:
            self._mm.close()
            self._mm = None
        if self._fd is not None:
            os.close(self._fd)
            self._fd = None

    def __enter__(self) -> "AccSharedMemoryProvider":
        self.open()
        return self

    def __exit__(self, *_: object) -> None:
        self.close()

    def read(self) -> TelemetryState | None:
        """
        Deserialise the current physics state.

        Returns None when the game is not in a session (packetId stays at 0).
        Raises RuntimeError if called before open().
        """
        if self._mm is None:
            raise RuntimeError("AccSharedMemoryProvider.open() has not been called")

        self._mm.seek(0)
        raw = self._mm.read(_BUFFER_SIZE)

        try:
            phys = _AccPhysics.from_buffer_copy(raw)
        except ValueError:
            return None

        if phys.packetId == 0:
            return None

        return _extract(phys)


def _extract(p: _AccPhysics) -> TelemetryState:
    v = p.velocity
    speed = math.sqrt(v[0] * v[0] + v[1] * v[1] + v[2] * v[2])

    # Normalise slip ratio to 0→1 grip-loss scale used by the effect layer.
    def _slip_to_grip(slip: float) -> float:
        return min(slip / _SLIP_SCALE, 1.0)

    return TelemetryState(
        throttle=float(p.gas),
        brake=float(p.brake),
        speed_ms=speed,
        engine_rpm=float(p.rpms),
        engine_max_rpm=float(p.currentMaxRpm),
        wheel_grip=(
            _slip_to_grip(p.wheelSlip[0]),
            _slip_to_grip(p.wheelSlip[1]),
            _slip_to_grip(p.wheelSlip[2]),
            _slip_to_grip(p.wheelSlip[3]),
        ),
        abs_active=bool(p.absInAction),
    )
