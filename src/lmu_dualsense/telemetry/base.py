from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class TelemetryState:
    """Snapshot of vehicle fields relevant to haptic feedback."""

    throttle: float        # 0.0–1.0, driver input (filtered)
    brake: float           # 0.0–1.0, driver input (filtered)
    speed_ms: float        # m/s, total velocity magnitude
    engine_rpm: float
    engine_max_rpm: float
    # Per-wheel sliding fraction: 0.0 = full grip, →1.0 = full slide.
    # Order matches rF2 convention: FL=0, FR=1, RL=2, RR=3.
    wheel_grip: tuple[float, float, float, float]
