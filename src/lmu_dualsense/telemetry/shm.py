"""
Reads rF2 telemetry from the shared memory created by LMU_SharedMemoryMapPlugin64.dll.

On Linux with Proton, Wine exposes Windows named shared memory in /dev/shm/.
The exact filename depends on the Wine version; several candidates are tried,
and /dev/shm/ is also scanned for any entry whose name contains the plugin id.

Plugin install (see README): copy LMU_SharedMemoryMapPlugin64.dll into
<Steam library>/steamapps/common/Le Mans Ultimate/Plugins/
"""

import ctypes
import math
import mmap
import os
from pathlib import Path

from lmu_dualsense.telemetry.base import TelemetryState
from lmu_dualsense.telemetry.structs import _TelemetryBuffer, _VehicleTelemetry

# Buffer name used by LMU_SharedMemoryMapPlugin / rF2SharedMemoryMapPlugin.
# "rFactor2" (not "rF2") — verified against CrewChief V4 source.
_PLUGIN_ID = "rFactor2SMMP_Telemetry"

_SHM_CANDIDATES = [
    f"/dev/shm/${_PLUGIN_ID}$",
    f"/dev/shm//${_PLUGIN_ID}$",
    f"/dev/shm/wine_${_PLUGIN_ID}$",
    f"/dev/shm/Wine_Sharedmem_${_PLUGIN_ID}$",
]

_BUFFER_SIZE = ctypes.sizeof(_TelemetryBuffer)

# Graphics buffer: slot ID of the vehicle currently on screen.
# Layout: 8-byte version block, then rF2GraphicsInfo.
# mID (long, 4 bytes) is at offset 128 within rF2GraphicsInfo:
#   mCamPos(24) + mCamOri[3](72) + mHWND(8, 64-bit ptr) + 3×ambient double(24) = 128.
_GRAPHICS_ID = "rFactor2SMMP_Graphics"
_GRAPHICS_ID_OFFSET = 136  # 8 (version block) + 128 (into rF2GraphicsInfo)
_GRAPHICS_CANDIDATES = [
    f"/dev/shm/${_GRAPHICS_ID}$",
    f"/dev/shm//${_GRAPHICS_ID}$",
    f"/dev/shm/wine_${_GRAPHICS_ID}$",
    f"/dev/shm/Wine_Sharedmem_${_GRAPHICS_ID}$",
]


def _read_player_slot_id() -> int:
    """Return the slot ID of the vehicle currently on screen, or -1 if unavailable."""
    for candidate in _GRAPHICS_CANDIDATES:
        p = Path(candidate)
        if not p.exists():
            continue
        try:
            with open(p, "rb") as f:
                f.seek(_GRAPHICS_ID_OFFSET)
                data = f.read(4)
                if len(data) == 4:
                    return int.from_bytes(data, "little", signed=True)
        except OSError:
            pass
    shm_dir = Path("/dev/shm")
    for entry in shm_dir.iterdir():
        if _GRAPHICS_ID in entry.name:
            try:
                with open(entry, "rb") as f:
                    f.seek(_GRAPHICS_ID_OFFSET)
                    data = f.read(4)
                    if len(data) == 4:
                        return int.from_bytes(data, "little", signed=True)
            except OSError:
                pass
    return -1


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
        "rF2 shared memory not found in /dev/shm/. "
        "Install LMU_SharedMemoryMapPlugin64.dll into the game's Plugins/ folder "
        "and make sure Le Mans Ultimate is running in an active session."
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

        # Use the actual file size instead of the structure size
        # to avoid ValueError if the buffer is smaller than _BUFFER_SIZE
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

        # Use from_buffer_copy to avoid alignment issues with mmap directly
        try:
            buf = _TelemetryBuffer.from_buffer_copy(raw)
        except ValueError:
            # If raw is too small, we can't read the buffer
            return None

        # Skip frame if the plugin is mid-write (version counters differ)
        if buf.mVersionUpdateBegin != buf.mVersionUpdateEnd:
            return None

        if buf.mNumVehicles == 0:
            return None

        slot_id = _read_player_slot_id()
        num = min(buf.mNumVehicles, len(buf.mVehicles))
        for i in range(num):
            if slot_id < 0 or buf.mVehicles[i].mID == slot_id:
                return _extract(buf.mVehicles[i])

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
