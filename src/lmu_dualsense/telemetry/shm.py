"""
Reads rF2 telemetry from the shared memory created by rF2SharedMemoryMapPlugin.dll.

On Linux with Proton, Wine exposes Windows named shared memory in /dev/shm/.
The exact filename depends on the Wine version; several candidates are tried,
and /dev/shm/ is also scanned for any entry whose name contains the plugin id.

Plugin install: copy rF2SharedMemoryMapPlugin.dll into
<Steam library>/steamapps/common/Le Mans Ultimate/Bin64/Plugins/
"""

import ctypes
import math
import mmap
import os
from pathlib import Path

from lmu_dualsense.telemetry.base import TelemetryState
from lmu_dualsense.telemetry.structs import _TelemetryBuffer, _VehicleTelemetry

_PLUGIN_ID = "rF2SMMP_Telemetry"

_SHM_CANDIDATES = [
    f"/dev/shm/${_PLUGIN_ID}$",
    f"/dev/shm//${_PLUGIN_ID}$",
    f"/dev/shm/wine_${_PLUGIN_ID}$",
    f"/dev/shm/Wine_Sharedmem_${_PLUGIN_ID}$",
]

_BUFFER_SIZE = ctypes.sizeof(_TelemetryBuffer)


class TelemetryNotAvailable(Exception):
    """Raised when the rF2 shared memory cannot be located or has no vehicles."""


def _find_shm_path() -> Path:
    for candidate in _SHM_CANDIDATES:
        p = Path(candidate)
        if p.exists():
            return p

    shm_dir = Path("/dev/shm")
    for entry in shm_dir.iterdir():
        if _PLUGIN_ID in entry.name:
            return entry

    raise TelemetryNotAvailable(
        f"rF2 shared memory not found in /dev/shm/. "
        f"Install rF2SharedMemoryMapPlugin.dll into the game's Bin64/Plugins/ "
        f"folder and make sure Le Mans Ultimate is running."
    )


class SharedMemoryProvider:
    """
    Maps the rF2SMMP telemetry region and deserialises vehicle state on demand.

    Supports use as a context manager::

        with SharedMemoryProvider() as p:
            state = p.read()   # None when game has no active vehicles

    Or explicit lifecycle::

        p = SharedMemoryProvider()
        p.open()
        try:
            state = p.read()
        finally:
            p.close()
    """

    def __init__(self) -> None:
        self._mm: mmap.mmap | None = None
        self._fd: int | None = None

    def open(self) -> None:
        path = _find_shm_path()
        self._fd = os.open(str(path), os.O_RDONLY)
        self._mm = mmap.mmap(self._fd, _BUFFER_SIZE, access=mmap.ACCESS_READ)

    def close(self) -> None:
        if self._mm is not None:
            self._mm.close()
            self._mm = None
        if self._fd is not None:
            os.close(self._fd)
            self._fd = None

    def __enter__(self) -> "SharedMemoryProvider":
        self.open()
        return self

    def __exit__(self, *_: object) -> None:
        self.close()

    def read(self) -> TelemetryState | None:
        """
        Deserialise the current player vehicle state.

        Returns None when mNumVehicles == 0 (game not in session).
        Raises RuntimeError if called before open().
        """
        if self._mm is None:
            raise RuntimeError("SharedMemoryProvider.open() has not been called")

        self._mm.seek(0)
        raw = self._mm.read(_BUFFER_SIZE)
        buf = _TelemetryBuffer.from_buffer_copy(raw)

        if buf.mNumVehicles == 0:
            return None

        return _extract(buf.mVehicles[0])


def _extract(v: _VehicleTelemetry) -> TelemetryState:
    lv = v.mLocalVel
    speed = math.sqrt(lv.x * lv.x + lv.y * lv.y + lv.z * lv.z)
    return TelemetryState(
        throttle=float(v.mFilteredThrottle),
        brake=float(v.mFilteredBrake),
        speed_ms=speed,
        engine_rpm=float(v.mEngineRPM),
        engine_max_rpm=float(v.mEngineMaxRPM),
        wheel_grip=(
            float(v.mWheels[0].mGripFract),
            float(v.mWheels[1].mGripFract),
            float(v.mWheels[2].mGripFract),
            float(v.mWheels[3].mGripFract),
        ),
    )
