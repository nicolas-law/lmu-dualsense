from dataclasses import dataclass, field


@dataclass
class SteeringConfig:
    enabled: bool = False
    # Sensitivity: how quickly the steering angle accumulates per rad/s of gyro input.
    # Higher = more responsive. Lerped from low-speed to high-speed value.
    sens_low_speed: float = 2.0    # at 0 km/h (easy to turn)
    sens_high_speed: float = 0.5   # at max_speed_ms (precise at high speed)
    max_speed_ms: float = 55.0     # ~200 km/h — where high-speed sens is fully applied
    dead_zone_rads: float = 0.03   # gyro noise floor (rad/s); below this → center return
    return_rate: float = 4.0       # fraction of steering angle removed per second when still


@dataclass
class TelemetryConfig:
    # Tried in order; first existing path wins.
    # Buffer name is "rFactor2SMMP_Telemetry" — verified against CrewChief V4.
    shm_names: list[str] = field(
        default_factory=lambda: [
            "$rFactor2SMMP_Telemetry$",
            "/$rFactor2SMMP_Telemetry$",
            "wine_$rFactor2SMMP_Telemetry$",
            "$rF2SMMP_Telemetry$",
            "/$rF2SMMP_Telemetry$",
            "wine_$rF2SMMP_Telemetry$",
        ]
    )
    poll_rate_hz: int = 100


@dataclass
class TriggerConfig:
    # Right trigger (throttle)
    throttle_base_resistance: int = 5    # 0-255, idle feel
    throttle_max_resistance: int = 70    # 0-255, at full throttle
    # mGripFract: 1.0 = full grip, ~0.0 = full slide.
    # Thresholds below are grip values; effects fire when grip DROPS below them.
    wheelspin_grip_threshold: float = 0.50  # rear grip below this → wheelspin pulse

    # Left trigger (brake)
    brake_max_resistance: int = 255      # 0-255, resistance at full brake (100% brake)
    # Two-zone brake feel:
    #   easy zone  (0 → threshold): low/no resistance — brake freely
    #   hard zone  (threshold → 1): resistance ramps up — prevents over-braking
    brake_threshold: float = 0.50        # bite point where resistance kicks in
    brake_easy_resistance: int = 0       # resistance in easy zone (0 = natural spring feel)
    abs_grip_threshold: float = 0.50    # front grip below this during braking → ABS pulse


@dataclass
class RumbleConfig:
    enabled: bool = True
    # Per-side grip rumble: FL+RL → left motor, FR+RR → right motor.
    # Fires during front lock-up (braking) and rear wheelspin (acceleration).
    grip_max_intensity: int = 180        # 0-255, intensity at full slide (grip = 0.0)
    grip_threshold: float = 0.60        # grip below this → rumble starts (1.0 = full grip)
    # Very subtle RPM drone so the car feels alive at idle/high revs.
    engine_max_intensity: int = 20       # 0-255, keep low so grip signals dominate


@dataclass
class Config:
    telemetry: TelemetryConfig = field(default_factory=TelemetryConfig)
    triggers: TriggerConfig = field(default_factory=TriggerConfig)
    rumble: RumbleConfig = field(default_factory=RumbleConfig)
    steering: SteeringConfig = field(default_factory=SteeringConfig)
