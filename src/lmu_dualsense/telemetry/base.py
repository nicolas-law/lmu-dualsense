from dataclasses import dataclass, field


@dataclass(frozen=True, slots=True)
class TelemetryState:
    """Snapshot of vehicle state for haptic feedback and telemetry recording."""

    throttle: float        # 0.0–1.0, driver input (filtered)
    brake: float           # 0.0–1.0, driver input (filtered)
    speed_ms: float        # m/s, total velocity magnitude
    engine_rpm: float
    engine_max_rpm: float
    # Per-wheel grip fraction (mGripFract): 1.0 = full grip, →0.0 = full slide.
    # Order matches rF2 convention: FL=0, FR=1, RL=2, RR=3.
    wheel_grip: tuple[float, float, float, float]
    # True when the game reports ABS is actively intervening this frame.
    # Games that expose this flag directly (e.g. ACC) set it; others leave it
    # False and the effect layer falls back to wheel_grip threshold detection.
    abs_active: bool = field(default=False)

    # Extended fields — populated by LMU provider; ACC leaves these at defaults.
    lap_number: int = field(default=0)
    lap_elapsed: float = field(default=0.0)       # seconds into current lap
    session_elapsed: float = field(default=0.0)   # seconds since session start
    track_name: str = field(default="")
    vehicle_name: str = field(default="")
    gear: int = field(default=0)                  # 0 = reverse, 1 = neutral, 2+ = gears
    fuel: float = field(default=0.0)
    steering: float = field(default=0.0)          # -1.0 left … +1.0 right
    # Per-wheel tire wear (0.0 = new, values increase as tire wears)
    tire_wear: tuple[float, float, float, float] = field(default=(0.0, 0.0, 0.0, 0.0))
    pos_x: float = field(default=0.0)             # world X (circuit layout plane)
    pos_z: float = field(default=0.0)             # world Z (circuit layout plane; Y is vertical)
