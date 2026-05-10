"""
MCP server for sim-dualsense.

Exposes live telemetry and recorded session data to Claude so it can
coach you during and after a race — analyse braking, compare laps,
spot where time is being lost, and track stint degradation.

Run as:  python -m lmu_dualsense.mcp_server
Or via the registered script:  sim-dualsense-mcp
"""

from __future__ import annotations

import ctypes
import math
import mmap
import os
import sqlite3
from collections.abc import Generator
from contextlib import contextmanager
from pathlib import Path

from mcp.server.fastmcp import FastMCP

from lmu_dualsense.telemetry.scoring import read_player_info
from lmu_dualsense.telemetry.structs import _TelemetryBuffer

mcp = FastMCP("sim-dualsense")

_DB = Path.home() / ".local" / "share" / "sim-dualsense" / "telemetry.db"
_SHM_CANDIDATES = [
    "/dev/shm/$rFactor2SMMP_Telemetry$",
    "/dev/shm//$rFactor2SMMP_Telemetry$",
    "/dev/shm/wine_$rFactor2SMMP_Telemetry$",
]
_BUF_SIZE = ctypes.sizeof(_TelemetryBuffer)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


@contextmanager
def _db() -> Generator[sqlite3.Connection, None, None]:
    conn = sqlite3.connect(str(_DB), check_same_thread=False)
    conn.row_factory = sqlite3.Row
    try:
        yield conn
    finally:
        conn.close()


def _shm_path() -> str | None:
    for c in _SHM_CANDIDATES:
        if os.path.exists(c):
            return c
    shm = Path("/dev/shm")
    for entry in shm.iterdir():
        if "rFactor2SMMP_Telemetry" in entry.name:
            return str(entry)
    return None


def _read_telemetry_raw() -> dict | None:
    """Single snapshot read from shared memory — no liveness check (instant)."""
    path = _shm_path()
    if path is None:
        return None
    try:
        fd = os.open(path, os.O_RDONLY)
        size = min(os.path.getsize(path), _BUF_SIZE)
        mm = mmap.mmap(fd, size, access=mmap.ACCESS_READ)
        mm.seek(0)
        raw = mm.read(size)
        mm.close()
        os.close(fd)

        buf = _TelemetryBuffer.from_buffer_copy(raw)
        stale = buf.mVersionUpdateBegin == buf.mVersionUpdateEnd
        if buf.mNumVehicles == 0:
            return {"status": "no_session", "stale": stale}

        player_slot, session_type = read_player_info()
        n = min(buf.mNumVehicles, len(buf.mVehicles))
        vehicle = None
        for i in range(n):
            if player_slot < 0 or buf.mVehicles[i].mID == player_slot:
                vehicle = buf.mVehicles[i]
                break
        if vehicle is None:
            vehicle = buf.mVehicles[0]

        lv = vehicle.mLocalVel
        speed = math.sqrt(lv.x ** 2 + lv.y ** 2 + lv.z ** 2)
        return {
            "status": "live",
            "stale": stale,
            "track": bytes(vehicle.mTrackName).rstrip(b"\x00").decode("utf-8", errors="replace"),
            "vehicle": bytes(vehicle.mVehicleName).rstrip(b"\x00").decode("utf-8", errors="replace"),
            "session_type": session_type,
            "lap": int(vehicle.mLapNumber),
            "lap_elapsed_s": round(max(0.0, float(vehicle.mElapsedTime) - float(vehicle.mLapStartET)), 2),
            "speed_kmh": round(speed * 3.6, 1),
            "throttle": round(float(vehicle.mFilteredThrottle), 3),
            "brake": round(float(vehicle.mFilteredBrake), 3),
            "gear": int(vehicle.mGear),
            "rpm": round(float(vehicle.mEngineRPM)),
            "rpm_max": round(float(vehicle.mEngineMaxRPM)),
            "fuel": round(float(vehicle.mFuel), 2),
            "grip": {
                "fl": round(float(vehicle.mWheels[0].mGripFract), 3),
                "fr": round(float(vehicle.mWheels[1].mGripFract), 3),
                "rl": round(float(vehicle.mWheels[2].mGripFract), 3),
                "rr": round(float(vehicle.mWheels[3].mGripFract), 3),
            },
        }
    except Exception as exc:
        return {"status": "error", "message": str(exc)}


def _fmt_time(s: float | None) -> str:
    if s is None:
        return "–"
    m = int(s // 60)
    sec = s % 60
    return f"{m}:{sec:06.3f}"


# ---------------------------------------------------------------------------
# Live tools
# ---------------------------------------------------------------------------


@mcp.tool()
def live() -> dict:
    """
    Snapshot of the current car state from the game's shared memory.

    Returns speed, throttle, brake, grip per wheel, lap number, lap elapsed
    time, gear, RPM, fuel. If 'stale' is true the game is not in an active
    session (data is frozen from the last session).
    """
    result = _read_telemetry_raw()
    if result is None:
        return {"status": "searching", "message": "No game shared memory found"}
    return result


# ---------------------------------------------------------------------------
# Session / lap tools
# ---------------------------------------------------------------------------


@mcp.tool()
def sessions(limit: int = 10) -> list[dict]:
    """
    List the most recent recorded sessions.

    Each entry: id, track, vehicle, session_type, started_at, lap_count,
    best_lap_s (formatted), best_lap_raw (seconds).
    """
    with _db() as db:
        rows = db.execute(
            "SELECT id, track, vehicle, session_type, started_at FROM sessions ORDER BY id DESC LIMIT ?",
            (limit,),
        ).fetchall()
        result = []
        for r in rows:
            laps = db.execute(
                "SELECT COUNT(*) c, MIN(lap_time_s) best FROM laps WHERE session_id=? AND lap_time_s IS NOT NULL",
                (r["id"],),
            ).fetchone()
            result.append({
                "id": r["id"],
                "track": r["track"],
                "vehicle": r["vehicle"],
                "session_type": r["session_type"],
                "started_at": r["started_at"],
                "lap_count": laps["c"],
                "best_lap": _fmt_time(laps["best"]),
                "best_lap_s": round(laps["best"], 3) if laps["best"] else None,
            })
    return result


@mcp.tool()
def laps(session_id: int) -> dict:
    """
    List all laps in a session with times, delta to best, and validity.

    Useful for spotting inconsistencies or finding reference laps to compare.
    """
    with _db() as db:
        session = db.execute(
            "SELECT track, vehicle, session_type FROM sessions WHERE id=?", (session_id,)
        ).fetchone()
        if session is None:
            return {"error": f"Session {session_id} not found"}

        rows = db.execute(
            "SELECT id, lap_number, lap_time_s FROM laps WHERE session_id=? ORDER BY lap_number",
            (session_id,),
        ).fetchall()

        times = [r["lap_time_s"] for r in rows if r["lap_time_s"] is not None]
        best = min(times) if times else None
        avg = sum(times) / len(times) if times else None

        laps_out = []
        for r in rows:
            t = r["lap_time_s"]
            delta = round(t - best, 3) if (t and best) else None
            laps_out.append({
                "id": r["id"],
                "lap_number": r["lap_number"],
                "lap_time": _fmt_time(t),
                "lap_time_s": round(t, 3) if t else None,
                "delta_to_best_s": delta,
                "is_best": t == best if t else False,
            })

        return {
            "session_id": session_id,
            "track": session["track"],
            "vehicle": session["vehicle"],
            "session_type": session["session_type"],
            "lap_count": len(rows),
            "best_lap": _fmt_time(best),
            "best_lap_s": round(best, 3) if best else None,
            "avg_lap_s": round(avg, 3) if avg else None,
            "laps": laps_out,
        }


@mcp.tool()
def lap_analysis(lap_id: int) -> dict:
    """
    Deep analysis of a single recorded lap.

    Computes:
    - Speed stats (max, min, avg) and speed at key events
    - Braking events: where did you brake (lap time), peak brake pressure,
      speed at brake point, minimum speed reached, how long the brake zone lasted
    - Throttle events: where did you get back on throttle after each corner,
      speed at throttle pickup
    - Grip/slip events: timestamps where any wheel slipped below 0.7 grip
    - Tire wear at end of lap
    """
    with _db() as db:
        lap = db.execute(
            "SELECT l.lap_number, l.lap_time_s, s.track, s.session_type "
            "FROM laps l JOIN sessions s ON s.id=l.session_id WHERE l.id=?",
            (lap_id,),
        ).fetchone()
        if lap is None:
            return {"error": f"Lap {lap_id} not found"}

        rows = db.execute(
            "SELECT lap_elapsed, speed_ms, throttle, brake, grip_fl, grip_fr, grip_rl, grip_rr, "
            "wear_fl, wear_fr, wear_rl, wear_rr, gear "
            "FROM samples WHERE lap_id=? ORDER BY lap_elapsed",
            (lap_id,),
        ).fetchall()

    if not rows:
        return {"error": "No samples for this lap"}

    speeds = [r["speed_ms"] * 3.6 for r in rows]

    # Braking events: detect zones where brake > 0.1
    brake_events = []
    in_brake = False
    b_start_t = b_start_speed = b_peak = 0.0
    for i, r in enumerate(rows):
        if not in_brake and r["brake"] > 0.1:
            in_brake = True
            b_start_t = r["lap_elapsed"]
            b_start_speed = speeds[i]
            b_peak = r["brake"]
        elif in_brake:
            b_peak = max(b_peak, r["brake"])
            if r["brake"] < 0.05:
                # End of brake zone
                min_speed = min(speeds[max(0, i - 15):i + 1])
                brake_events.append({
                    "brake_point_s": round(b_start_t, 2),
                    "entry_speed_kmh": round(b_start_speed, 1),
                    "peak_brake": round(b_peak, 2),
                    "min_speed_kmh": round(min_speed, 1),
                    "duration_s": round(r["lap_elapsed"] - b_start_t, 2),
                })
                in_brake = False

    # Throttle pickup events: first full-throttle after a brake zone
    throttle_events = []
    post_brake = False
    for i, r in enumerate(rows):
        if r["brake"] > 0.1:
            post_brake = True
        elif post_brake and r["throttle"] > 0.8:
            throttle_events.append({
                "pickup_s": round(r["lap_elapsed"], 2),
                "speed_kmh": round(speeds[i], 1),
            })
            post_brake = False

    # Slip events: any wheel below 0.5 grip
    slip_events = []
    in_slip = False
    for r in rows:
        min_grip = min(r["grip_fl"], r["grip_fr"], r["grip_rl"], r["grip_rr"])
        if not in_slip and min_grip < 0.5:
            in_slip = True
            slip_events.append({
                "t_s": round(r["lap_elapsed"], 2),
                "min_grip": round(min_grip, 3),
                "speed_kmh": round(r["speed_ms"] * 3.6, 1),
                "brake": round(r["brake"], 2),
                "throttle": round(r["throttle"], 2),
            })
        elif in_slip and min_grip >= 0.5:
            in_slip = False

    last = rows[-1]
    return {
        "lap_id": lap_id,
        "lap_number": lap["lap_number"],
        "lap_time": _fmt_time(lap["lap_time_s"]),
        "track": lap["track"],
        "session_type": lap["session_type"],
        "sample_count": len(rows),
        "speed": {
            "max_kmh": round(max(speeds), 1),
            "min_kmh": round(min(speeds), 1),
            "avg_kmh": round(sum(speeds) / len(speeds), 1),
        },
        "braking": {
            "event_count": len(brake_events),
            "events": brake_events,
        },
        "throttle_pickups": throttle_events,
        "slip_events": slip_events[:20],  # cap at 20 to keep response manageable
        "tire_wear_end": {
            "fl": round(last["wear_fl"] * 100, 1),
            "fr": round(last["wear_fr"] * 100, 1),
            "rl": round(last["wear_rl"] * 100, 1),
            "rr": round(last["wear_rr"] * 100, 1),
        },
    }


@mcp.tool()
def lap_comparison(lap_a_id: int, lap_b_id: int) -> dict:
    """
    Compare two laps to find where time is gained or lost.

    Splits both laps into 10% buckets by elapsed time and compares:
    avg speed, peak brake pressure, avg grip. Highlights the biggest
    deltas so you can see exactly where one lap is faster.

    Use laps() to find the IDs of the laps you want to compare.
    """
    def _load(lap_id: int) -> tuple[dict, list]:
        with _db() as db:
            meta = db.execute(
                "SELECT l.lap_number, l.lap_time_s, s.track FROM laps l "
                "JOIN sessions s ON s.id=l.session_id WHERE l.id=?",
                (lap_id,),
            ).fetchone()
            rows = db.execute(
                "SELECT lap_elapsed, speed_ms, brake, throttle, grip_fl, grip_fr, grip_rl, grip_rr "
                "FROM samples WHERE lap_id=? ORDER BY lap_elapsed",
                (lap_id,),
            ).fetchall()
        return dict(meta) if meta else {}, list(rows)

    meta_a, rows_a = _load(lap_a_id)
    meta_b, rows_b = _load(lap_b_id)
    if not meta_a:
        return {"error": f"Lap {lap_a_id} not found"}
    if not meta_b:
        return {"error": f"Lap {lap_b_id} not found"}

    def _bucket(rows: list, n: int = 10) -> list[dict]:
        if not rows:
            return []
        total = rows[-1]["lap_elapsed"] or 1.0
        buckets = [{"speed": [], "brake": [], "grip": []} for _ in range(n)]
        for r in rows:
            idx = min(int(r["lap_elapsed"] / total * n), n - 1)
            buckets[idx]["speed"].append(r["speed_ms"] * 3.6)
            buckets[idx]["brake"].append(r["brake"])
            g = min(r["grip_fl"], r["grip_fr"], r["grip_rl"], r["grip_rr"])
            buckets[idx]["grip"].append(g)
        return [
            {
                "pct": f"{i * 10}–{(i + 1) * 10}%",
                "avg_speed": round(sum(b["speed"]) / len(b["speed"]), 1) if b["speed"] else 0,
                "peak_brake": round(max(b["brake"]), 2) if b["brake"] else 0,
                "avg_grip": round(sum(b["grip"]) / len(b["grip"]), 3) if b["grip"] else 0,
            }
            for i, b in enumerate(buckets)
        ]

    ba = _bucket(rows_a)
    bb = _bucket(rows_b)
    deltas = []
    for a, b in zip(ba, bb, strict=False):
        deltas.append({
            "pct": a["pct"],
            "speed_delta_kmh": round(b["avg_speed"] - a["avg_speed"], 1),
            "brake_delta": round(b["peak_brake"] - a["peak_brake"], 2),
            "grip_delta": round(b["avg_grip"] - a["avg_grip"], 3),
        })

    time_a = meta_a.get("lap_time_s")
    time_b = meta_b.get("lap_time_s")
    return {
        "lap_a": {"id": lap_a_id, "lap_number": meta_a.get("lap_number"), "time": _fmt_time(time_a)},
        "lap_b": {"id": lap_b_id, "lap_number": meta_b.get("lap_number"), "time": _fmt_time(time_b)},
        "delta_s": round(time_b - time_a, 3) if (time_a and time_b) else None,
        "note": "positive speed/grip delta = lap B is better in that sector",
        "sector_deltas": deltas,
    }


@mcp.tool()
def stint_analysis(session_id: int) -> dict:
    """
    Analyse performance trends across an entire stint/session.

    Shows per-lap: time, speed, grip average (proxy for tyre condition),
    ABS/wheelspin events (how often you pushed limits), and brake pressure.
    Useful for spotting tyre degradation, fatigue, or setup issues.
    """
    with _db() as db:
        session = db.execute(
            "SELECT track, vehicle, session_type FROM sessions WHERE id=?", (session_id,)
        ).fetchone()
        if session is None:
            return {"error": f"Session {session_id} not found"}

        lap_rows = db.execute(
            "SELECT id, lap_number, lap_time_s FROM laps WHERE session_id=? ORDER BY lap_number",
            (session_id,),
        ).fetchall()

        stints = []
        for lap in lap_rows:
            stats = db.execute(
                """SELECT
                    AVG(speed_ms) * 3.6        AS avg_speed,
                    MAX(speed_ms) * 3.6        AS max_speed,
                    MAX(brake)                 AS peak_brake,
                    AVG((grip_fl + grip_fr + grip_rl + grip_rr) / 4.0) AS avg_grip,
                    SUM(CASE WHEN grip_fl < 0.5 OR grip_fr < 0.5
                             OR grip_rl < 0.5 OR grip_rr < 0.5 THEN 1 ELSE 0 END) AS slip_frames
                FROM samples WHERE lap_id=?""",
                (lap["id"],),
            ).fetchone()
            stints.append({
                "lap_number": lap["lap_number"],
                "lap_time": _fmt_time(lap["lap_time_s"]),
                "lap_time_s": round(lap["lap_time_s"], 3) if lap["lap_time_s"] else None,
                "avg_speed_kmh": round(stats["avg_speed"], 1) if stats["avg_speed"] else None,
                "max_speed_kmh": round(stats["max_speed"], 1) if stats["max_speed"] else None,
                "peak_brake": round(stats["peak_brake"], 2) if stats["peak_brake"] else None,
                "avg_grip": round(stats["avg_grip"], 3) if stats["avg_grip"] else None,
                "slip_frames": stats["slip_frames"] or 0,
            })

    times = [s["lap_time_s"] for s in stints if s["lap_time_s"]]
    trend = None
    if len(times) >= 3:
        # Simple linear trend: positive = getting slower
        mid = len(times) // 2
        first_half = sum(times[:mid]) / mid
        second_half = sum(times[mid:]) / (len(times) - mid)
        trend_s = round(second_half - first_half, 3)
        trend = f"+{trend_s}s" if trend_s > 0 else f"{trend_s}s"

    return {
        "session_id": session_id,
        "track": session["track"],
        "vehicle": session["vehicle"],
        "session_type": session["session_type"],
        "lap_count": len(stints),
        "best_lap": _fmt_time(min(times)) if times else "–",
        "lap_time_trend": trend,
        "note": "lap_time_trend: positive = getting slower over the stint",
        "laps": stints,
    }


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def main() -> None:
    mcp.run()


if __name__ == "__main__":
    main()
