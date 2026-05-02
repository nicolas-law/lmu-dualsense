from dataclasses import dataclass, field


@dataclass
class TelemetryConfig:
    # Tried in order; first existing path wins.
    shm_names: list[str] = field(default_factory=lambda: [
        "$rF2SMMP_Telemetry$",
        "/$rF2SMMP_Telemetry$",
        "wine_$rF2SMMP_Telemetry$",
    ])
    poll_rate_hz: int = 100


@dataclass
class TriggerConfig:
    # Right trigger (throttle)
    throttle_base_resistance: int = 25     # 0-255, idle feel
    throttle_max_resistance: int = 70      # 0-255, at full throttle
    wheelspin_grip_threshold: float = 0.12  # mGripFract above this → wheelspin pulse

    # Left trigger (brake)
    brake_max_resistance: int = 220        # 0-255, at full brake
    abs_grip_threshold: float = 0.15       # mGripFract above this during braking → ABS pulse


@dataclass
class Config:
    telemetry: TelemetryConfig = field(default_factory=TelemetryConfig)
    triggers: TriggerConfig = field(default_factory=TriggerConfig)
