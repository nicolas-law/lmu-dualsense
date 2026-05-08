"""
Telemetry recorder: persists TelemetryState samples to SQLite.

Recording rate: 25 Hz (every 4th frame at 100 Hz poll rate).
Session boundaries are detected when the track name changes.
Lap boundaries are detected when lap_number increments.
"""

import logging
import sqlite3
import threading
from datetime import UTC, datetime
from pathlib import Path

from lmu_dualsense.telemetry.base import TelemetryState

logger = logging.getLogger(__name__)

_DB_DIR = Path.home() / ".local" / "share" / "sim-dualsense"
_RECORD_EVERY = 4  # keep every Nth sample (100 Hz / 4 = 25 Hz)

_SCHEMA = """
PRAGMA journal_mode=WAL;

CREATE TABLE IF NOT EXISTS sessions (
    id          INTEGER PRIMARY KEY,
    track       TEXT    NOT NULL,
    vehicle     TEXT    NOT NULL DEFAULT '',
    started_at  TEXT    NOT NULL,
    ended_at    TEXT
);

CREATE TABLE IF NOT EXISTS laps (
    id          INTEGER PRIMARY KEY,
    session_id  INTEGER NOT NULL REFERENCES sessions(id),
    lap_number  INTEGER NOT NULL,
    lap_time_s  REAL,
    started_at  TEXT    NOT NULL
);

CREATE TABLE IF NOT EXISTS samples (
    id          INTEGER PRIMARY KEY,
    lap_id      INTEGER NOT NULL REFERENCES laps(id),
    lap_elapsed REAL    NOT NULL,
    speed_ms    REAL,
    throttle    REAL,
    brake       REAL,
    steering    REAL,
    gear        INTEGER,
    rpm         REAL,
    grip_fl     REAL, grip_fr REAL, grip_rl REAL, grip_rr REAL,
    wear_fl     REAL, wear_fr REAL, wear_rl REAL, wear_rr REAL,
    fuel        REAL,
    pos_x       REAL,
    pos_z       REAL
);

CREATE INDEX IF NOT EXISTS idx_samples_lap ON samples(lap_id);
CREATE INDEX IF NOT EXISTS idx_laps_session ON laps(session_id);
"""


def db_path() -> Path:
    return _DB_DIR / "telemetry.db"


class Recorder:
    """
    Thread-safe telemetry recorder.

    Call record() from the feedback loop; the dashboard reads the same DB file.
    """

    def __init__(self, path: Path | None = None) -> None:
        self._path = path or db_path()
        self._conn: sqlite3.Connection | None = None
        self._lock = threading.Lock()
        self._tick = 0
        self._session_id: int | None = None
        self._lap_id: int | None = None
        self._current_track: str = ""
        self._current_lap: int = -1
        self._last_lap_elapsed: float = 0.0  # last recorded value before lap boundary

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    def open(self) -> None:
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(str(self._path), check_same_thread=False)
        self._conn.executescript(_SCHEMA)
        self._conn.commit()
        logger.info("Telemetry recorder opened: %s", self._path)

    def close(self) -> None:
        with self._lock:
            if self._conn is not None:
                self._conn.commit()
                self._conn.close()
                self._conn = None
        logger.info("Telemetry recorder closed")

    def __enter__(self) -> "Recorder":
        self.open()
        return self

    def __exit__(self, *_: object) -> None:
        self.close()

    # ------------------------------------------------------------------
    # Recording
    # ------------------------------------------------------------------

    def record(self, state: TelemetryState) -> None:
        """Called from the feedback loop at 100 Hz; downsampled internally."""
        if self._conn is None:
            return
        if not state.track_name:
            return  # no active session in sim

        self._tick += 1

        with self._lock:
            self._ensure_session(state)
            self._ensure_lap(state)

            if self._tick % _RECORD_EVERY == 0 and self._lap_id is not None:
                self._insert_sample(state)

            self._last_lap_elapsed = state.lap_elapsed

    def _ensure_session(self, state: TelemetryState) -> None:
        if state.track_name == self._current_track and self._session_id is not None:
            return
        # Close the old session if one was open
        if self._session_id is not None:
            self._close_session()
        # Open a new session
        self._current_track = state.track_name
        self._current_lap = -1
        self._lap_id = None
        now = _now()
        assert self._conn is not None
        cur = self._conn.execute(
            "INSERT INTO sessions (track, vehicle, session_type, started_at) VALUES (?, ?, ?, ?)",
            (state.track_name, state.vehicle_name, state.session_type, now),
        )
        self._session_id = cur.lastrowid
        self._conn.commit()
        logger.info("New session: %s  (id=%s)", state.track_name, self._session_id)

    def _ensure_lap(self, state: TelemetryState) -> None:
        if state.lap_number == self._current_lap:
            return
        assert self._conn is not None
        # Close the previous lap with its actual time
        if self._lap_id is not None and self._current_lap >= 0:
            lap_time = self._last_lap_elapsed if self._last_lap_elapsed > 0 else None
            self._conn.execute(
                "UPDATE laps SET lap_time_s = ? WHERE id = ?",
                (lap_time, self._lap_id),
            )
        self._current_lap = state.lap_number
        now = _now()
        cur = self._conn.execute(
            "INSERT INTO laps (session_id, lap_number, started_at) VALUES (?, ?, ?)",
            (self._session_id, state.lap_number, now),
        )
        self._lap_id = cur.lastrowid
        self._conn.commit()

    def _insert_sample(self, state: TelemetryState) -> None:
        assert self._conn is not None
        self._conn.execute(
            """INSERT INTO samples (
                lap_id, lap_elapsed,
                speed_ms, throttle, brake, steering, gear, rpm,
                grip_fl, grip_fr, grip_rl, grip_rr,
                wear_fl, wear_fr, wear_rl, wear_rr,
                fuel, pos_x, pos_z
            ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (
                self._lap_id,
                state.lap_elapsed,
                state.speed_ms,
                state.throttle,
                state.brake,
                state.steering,
                state.gear,
                state.engine_rpm,
                state.wheel_grip[0], state.wheel_grip[1],
                state.wheel_grip[2], state.wheel_grip[3],
                state.tire_wear[0], state.tire_wear[1],
                state.tire_wear[2], state.tire_wear[3],
                state.fuel,
                state.pos_x,
                state.pos_z,
            ),
        )
        # Batch commits every 25 samples (~1 s) to reduce write pressure
        if self._tick % (25 * _RECORD_EVERY) == 0:
            self._conn.commit()

    def _close_session(self) -> None:
        assert self._conn is not None
        self._conn.execute(
            "UPDATE sessions SET ended_at = ? WHERE id = ?",
            (_now(), self._session_id),
        )
        self._conn.commit()
        self._session_id = None
        self._lap_id = None


def _now() -> str:
    return datetime.now(UTC).isoformat()
