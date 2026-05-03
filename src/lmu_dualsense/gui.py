"""Dear PyGui overlay: live telemetry display and real-time trigger config editor."""

import logging
import threading
from collections.abc import Callable

import dearpygui.dearpygui as dpg

from lmu_dualsense.config import Config, RumbleConfig, SteeringConfig
from lmu_dualsense.controller.dualsense import DualSenseController
from lmu_dualsense.feedback import AppState, _run_loop

logger = logging.getLogger(__name__)

_W = 420
_H = 920


def _slider_int(
    label: str, tag: str, default: int, lo: int, hi: int, cb: Callable[..., None]
) -> None:
    """Label row + full-width int slider."""
    dpg.add_text(label)
    dpg.add_slider_int(
        label=f"##{tag}", tag=tag,
        default_value=default, min_value=lo, max_value=hi,
        width=-1, callback=cb,
    )


def _slider_float(
    label: str, tag: str, default: float, lo: float, hi: float, cb: Callable[..., None],
    fmt: str = "%.2f",
) -> None:
    """Label row + full-width float slider."""
    dpg.add_text(label)
    dpg.add_slider_float(
        label=f"##{tag}", tag=tag,
        default_value=default, min_value=lo, max_value=hi,
        width=-1, format=fmt, callback=cb,
    )


def _build_ui(app_state: AppState, rcfg: "RumbleConfig", scfg: "SteeringConfig") -> None:
    cfg = app_state.config

    with dpg.window(tag="main", no_close=True):

        # ── Status ───────────────────────────────────────────────────────────
        dpg.add_text("Game: Searching...", tag="t_game")
        dpg.add_text("Controller: -",     tag="t_ctrl")

        dpg.add_separator()
        dpg.add_spacer(height=2)

        # ── Live telemetry ───────────────────────────────────────────────────
        dpg.add_text("TELEMETRY", color=(150, 150, 150))
        dpg.add_spacer(height=4)

        with dpg.group(horizontal=True):
            dpg.add_text("Brake   ")
            dpg.add_progress_bar(tag="pb_brake",    default_value=0.0, width=-90)
            dpg.add_text("0.00", tag="t_brake_val")

        with dpg.group(horizontal=True):
            dpg.add_text("Throttle")
            dpg.add_progress_bar(tag="pb_throttle", default_value=0.0, width=-90)
            dpg.add_text("0.00", tag="t_throttle_val")

        dpg.add_spacer(height=4)

        with dpg.group(horizontal=True):
            dpg.add_text("Speed: - km/h    ", tag="t_speed")
            dpg.add_text("ABS: ")
            dpg.add_text("-", tag="t_abs")

        dpg.add_text("Grip front: - / -", tag="t_grip_f")
        dpg.add_text("Grip rear:  - / -", tag="t_grip_r")
        dpg.add_spacer(height=4)

        with dpg.group(horizontal=True):
            dpg.add_text("L2: ")
            dpg.add_text("-", tag="t_l2")
            dpg.add_text("    R2: ")
            dpg.add_text("-", tag="t_r2")

        with dpg.group(horizontal=True):
            dpg.add_text("Rumble L: ")
            dpg.add_text("-", tag="t_rum_l")
            dpg.add_text("    R: ")
            dpg.add_text("-", tag="t_rum_r")

        dpg.add_spacer(height=2)
        dpg.add_separator()
        dpg.add_spacer(height=2)

        # ── Brake trigger (L2) ───────────────────────────────────────────────
        dpg.add_text("BRAKE TRIGGER  L2", color=(150, 150, 150))
        dpg.add_spacer(height=4)

        _slider_float(
            "Bite Point  (brake % where resistance goes from light to hard)",
            "s_brake_threshold", cfg.brake_threshold, 0.0, 1.0,
            lambda s, v: setattr(cfg, "brake_threshold", v),
        )
        dpg.add_spacer(height=4)
        _slider_int(
            "Easy Zone Resistance  (0 = natural spring, raise for feel below bite point)",
            "s_brake_easy", cfg.brake_easy_resistance, 0, 255,
            lambda s, v: setattr(cfg, "brake_easy_resistance", v),
        )
        dpg.add_spacer(height=4)
        _slider_int(
            "Max Resistance  (feel at 100% brake)",
            "s_brake_max", cfg.brake_max_resistance, 0, 255,
            lambda s, v: setattr(cfg, "brake_max_resistance", v),
        )
        dpg.add_spacer(height=4)
        _slider_float(
            "ABS Pulse Threshold  (grip loss that triggers ABS pulse)",
            "s_abs_thresh", cfg.abs_grip_threshold, 0.0, 1.0,
            lambda s, v: setattr(cfg, "abs_grip_threshold", v),
        )

        dpg.add_spacer(height=2)
        dpg.add_separator()
        dpg.add_spacer(height=2)

        # ── Throttle trigger (R2) ────────────────────────────────────────────
        dpg.add_text("THROTTLE TRIGGER  R2", color=(150, 150, 150))
        dpg.add_spacer(height=4)

        _slider_int(
            "Base Resistance  (idle feel when off throttle)",
            "s_thr_base", cfg.throttle_base_resistance, 0, 255,
            lambda s, v: setattr(cfg, "throttle_base_resistance", v),
        )
        dpg.add_spacer(height=4)
        _slider_int(
            "Max Resistance  (feel at full throttle)",
            "s_thr_max", cfg.throttle_max_resistance, 0, 255,
            lambda s, v: setattr(cfg, "throttle_max_resistance", v),
        )
        dpg.add_spacer(height=4)
        _slider_float(
            "Wheelspin Threshold  (grip loss that triggers wheelspin pulse)",
            "s_spin_thresh", cfg.wheelspin_grip_threshold, 0.0, 1.0,
            lambda s, v: setattr(cfg, "wheelspin_grip_threshold", v),
        )

        dpg.add_spacer(height=2)
        dpg.add_separator()
        dpg.add_spacer(height=2)

        # ── Grip rumble motors ───────────────────────────────────────────────
        dpg.add_text("GRIP RUMBLE MOTORS", color=(150, 150, 150))
        dpg.add_spacer(height=4)

        dpg.add_checkbox(
            label="Enable grip rumble",
            tag="cb_rumble_enabled",
            default_value=rcfg.enabled,
            callback=lambda s, v: setattr(rcfg, "enabled", v),
        )
        dpg.add_spacer(height=6)

        _slider_int(
            "Max Grip Intensity  (0-255, rumble at full slide)",
            "s_rum_grip_max", rcfg.grip_max_intensity, 0, 255,
            lambda s, v: setattr(rcfg, "grip_max_intensity", v),
        )
        dpg.add_spacer(height=4)
        _slider_float(
            "Grip Threshold  (slip below this → no rumble)",
            "s_rum_grip_thresh", rcfg.grip_threshold, 0.0, 0.5,
            lambda s, v: setattr(rcfg, "grip_threshold", v),
        )
        dpg.add_spacer(height=4)
        _slider_int(
            "Engine Drone Max  (0-255, background RPM feel — keep low)",
            "s_rum_engine_max", rcfg.engine_max_intensity, 0, 80,
            lambda s, v: setattr(rcfg, "engine_max_intensity", v),
        )

        dpg.add_spacer(height=2)
        dpg.add_separator()
        dpg.add_spacer(height=2)

        # ── Gyro steering ────────────────────────────────────────────────────
        dpg.add_text("GYRO STEERING", color=(150, 150, 150))
        dpg.add_spacer(height=4)
        dpg.add_text(
            "Creates a virtual joystick  lmu-dualsense-steering  in the game controller list.",
            color=(110, 110, 110),
        )
        dpg.add_text(
            "Bind its X axis as steering in-game, then enable here.",
            color=(110, 110, 110),
        )
        dpg.add_spacer(height=6)

        dpg.add_checkbox(
            label="Enable gyro steering",
            tag="cb_steer_enabled",
            default_value=scfg.enabled,
            callback=lambda s, v: setattr(scfg, "enabled", v),
        )
        dpg.add_spacer(height=6)

        _slider_float(
            "Sensitivity at low speed  (0 km/h)",
            "s_steer_sens_lo", scfg.sens_low_speed, 0.1, 6.0,
            lambda s, v: setattr(scfg, "sens_low_speed", v),
            fmt="%.1f",
        )
        dpg.add_spacer(height=4)
        _slider_float(
            "Sensitivity at high speed  (~200 km/h)",
            "s_steer_sens_hi", scfg.sens_high_speed, 0.1, 6.0,
            lambda s, v: setattr(scfg, "sens_high_speed", v),
            fmt="%.1f",
        )
        dpg.add_spacer(height=4)
        _slider_float(
            "Center return rate  (how fast it self-centres when still)",
            "s_steer_return", scfg.return_rate, 0.0, 10.0,
            lambda s, v: setattr(scfg, "return_rate", v),
            fmt="%.1f",
        )


def _refresh(app_state: AppState) -> None:
    tel = app_state.telemetry
    cfg = app_state.config

    # Status
    dpg.set_value("t_game", f"Game: {app_state.game}")
    if app_state.ctrl_ok:
        dpg.set_value("t_ctrl", "Controller: Connected")
        dpg.configure_item("t_ctrl", color=(100, 210, 100))
    else:
        dpg.set_value("t_ctrl", "Controller: not found")
        dpg.configure_item("t_ctrl", color=(210, 80, 80))

    if tel is None:
        return

    # Telemetry
    dpg.set_value("pb_brake",       tel.brake)
    dpg.set_value("t_brake_val",    f"{tel.brake:.2f}")
    dpg.set_value("pb_throttle",    tel.throttle)
    dpg.set_value("t_throttle_val", f"{tel.throttle:.2f}")
    dpg.set_value("t_speed",        f"Speed: {tel.speed_ms * 3.6:.0f} km/h    ")

    abs_on = tel.abs_active or (
        tel.brake > 0.1
        and min(tel.wheel_grip[0], tel.wheel_grip[1]) < cfg.abs_grip_threshold
    )
    if abs_on:
        dpg.set_value("t_abs", "YES")
        dpg.configure_item("t_abs", color=(255, 80, 80))
    else:
        dpg.set_value("t_abs", "no")
        dpg.configure_item("t_abs", color=(100, 210, 100))

    fl, fr, rl, rr = tel.wheel_grip
    dpg.set_value("t_grip_f", f"Grip front: FL {fl:.2f} / FR {fr:.2f}")
    dpg.set_value("t_grip_r", f"Grip rear:  RL {rl:.2f} / RR {rr:.2f}")

    l2, r2 = app_state.l2_effect, app_state.r2_effect
    dpg.set_value("t_l2", f"{l2.mode.name}  force={l2.forces.get(1, 0)}" if l2 else "-")
    dpg.set_value("t_r2", f"{r2.mode.name}  force={r2.forces.get(1, 0)}" if r2 else "-")

    rum = app_state.rumble_effect
    dpg.set_value("t_rum_l", str(rum.left) if rum else "-")
    dpg.set_value("t_rum_r", str(rum.right) if rum else "-")


def main() -> None:
    logging.basicConfig(
        level=logging.WARNING,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )

    cfg = Config()
    app_state = AppState(config=cfg.triggers)
    stopped = threading.Event()

    def _worker() -> None:
        with DualSenseController() as ctrl:
            _run_loop(
                ctrl=ctrl,
                cfg=cfg,
                interval=1.0 / cfg.telemetry.poll_rate_hz,
                should_stop=stopped.is_set,
                app_state=app_state,
            )

    threading.Thread(target=_worker, daemon=True).start()

    dpg.create_context()
    _build_ui(app_state, cfg.rumble, cfg.steering)
    dpg.create_viewport(
        title="DualSense Feedback",
        width=_W, height=_H,
        always_on_top=True,
        resizable=True,
        min_width=360, min_height=420,
    )
    dpg.set_primary_window("main", True)
    dpg.setup_dearpygui()
    dpg.show_viewport()

    while dpg.is_dearpygui_running():
        _refresh(app_state)
        dpg.render_dearpygui_frame()

    stopped.set()
    dpg.destroy_context()
