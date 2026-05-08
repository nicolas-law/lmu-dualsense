"""
Reads player slot ID and session type from the rF2 scoring shared memory.

Uses fixed byte offsets into the raw buffer (verified with ctypes) rather than
mapping the full 75 KB structure — we only need a handful of values.

Verified offsets (pack=4, AMD64):
  sizeof(rF2ScoringInfo)  = 548
  sizeof(rF2VehicleScoring) = 584
  mIsPlayer within rF2VehicleScoring = 196
  mID      within rF2VehicleScoring = 0
"""

from pathlib import Path

_PLUGIN_ID = "rFactor2SMMP_Scoring"

_SHM_CANDIDATES = [
    f"/dev/shm/${_PLUGIN_ID}$",
    f"/dev/shm//${_PLUGIN_ID}$",
    f"/dev/shm/wine_${_PLUGIN_ID}$",
    f"/dev/shm/Wine_Sharedmem_${_PLUGIN_ID}$",
]

# Buffer layout: rF2MappedBufferVersionBlock (8) + mBytesUpdatedHint (4) = 12 byte header,
# then rF2ScoringInfo (548 bytes), then rF2VehicleScoring[128].
_HEADER          = 12
_SESSION_OFF     = _HEADER + 64    # mSession: c_int (4 bytes) — 0=testday, 1-4=practice,
                                   # 5-8=qualifying, 9=warmup, 10-13=race
_NUM_VEH_OFF     = _HEADER + 104   # mNumVehicles: c_int (4 bytes)
_VEHICLES_OFF    = _HEADER + 548   # rF2VehicleScoring[0] starts here (= 560)
_VEH_STRIDE      = 584             # sizeof(rF2VehicleScoring)
_VEH_ID_OFF      = 0               # mID: c_int (4 bytes) — slot ID
_VEH_IS_PLAYER   = 196             # mIsPlayer: c_bool (1 byte)
_VEH_CONTROL     = 197             # mControl: -1=nobody, 0=local player, 1=AI, 2=remote
_VEH_IN_GARAGE   = 507             # mInGarageStall: c_bool (1 byte)

_MAX_VEHICLES = 128


def session_type_name(session_int: int) -> str:
    if 1 <= session_int <= 4:
        return "practice"
    if 5 <= session_int <= 8:
        return "qualifying"
    if session_int == 9:
        return "warmup"
    if 10 <= session_int <= 13:
        return "race"
    return "unknown"


def _find_path() -> Path | None:
    for cand in _SHM_CANDIDATES:
        p = Path(cand)
        if p.exists():
            return p
    try:
        for entry in Path("/dev/shm").iterdir():
            if _PLUGIN_ID in entry.name:
                return entry
    except OSError:
        pass
    return None


def read_player_info() -> tuple[int, str]:
    """
    Return (player_slot_id, session_type_name).

    player_slot_id: mID of the player's car (-1 if not found).
    session_type_name: 'practice', 'qualifying', 'warmup', 'race', or 'unknown'.
    """
    path = _find_path()
    if path is None:
        return -1, "unknown"
    try:
        with open(path, "rb") as f:
            f.seek(_SESSION_OFF)
            raw = f.read(4)
            if len(raw) < 4:
                return -1, "unknown"
            session = int.from_bytes(raw, "little", signed=True)

            f.seek(_NUM_VEH_OFF)
            raw = f.read(4)
            if len(raw) < 4:
                return -1, session_type_name(session)
            n = min(max(int.from_bytes(raw, "little", signed=True), 0), _MAX_VEHICLES)

            for i in range(n):
                base = _VEHICLES_OFF + i * _VEH_STRIDE
                f.seek(base + _VEH_IS_PLAYER)
                flag = f.read(1)
                if flag and flag[0]:
                    f.seek(base + _VEH_ID_OFF)
                    id_raw = f.read(4)
                    if len(id_raw) == 4:
                        slot_id = int.from_bytes(id_raw, "little", signed=True)
                        return slot_id, session_type_name(session)

            return -1, session_type_name(session)
    except OSError:
        return -1, "unknown"
