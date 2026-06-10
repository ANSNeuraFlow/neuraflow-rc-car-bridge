"""Load evdev axis calibration and apply gamepad events."""

from __future__ import annotations

import sys
import threading
import time
from dataclasses import dataclass, field
from typing import Any, Callable

from config import (
    GAMEPAD_LIGHTS_BUTTON,
    GAMEPAD_LIGHTS_DEBOUNCE_S,
    GAMEPAD_MACRO_DEBOUNCE_S,
    GAMEPAD_NEUTRAL_BUTTON,
    GAMEPAD_NEUTRAL_DEBOUNCE_S,
)
from movement_timelines import event_code_to_binding
from gamepad_mapping import (
    DEFAULT_STICK_CALIB,
    DEFAULT_TRIGGER_CALIB,
    AxisCalib,
    normalize_stick_raw,
    normalize_trigger_raw,
)

LogFn = Callable[[str, str], None]
EnqueueFn = Callable[[str, dict[str, Any]], None]

STEER_CODE = "ABS_X"
LT_CODES = ("ABS_Z", "ABS_BRAKE")
RT_CODES = ("ABS_RZ", "ABS_GAS")
HAT_X_CODE = "ABS_HAT0X"
HAT_Y_CODE = "ABS_HAT0Y"

# Linux input.h axis codes
_LINUX_ABS = {
    "ABS_X": 0x00,
    "ABS_Z": 0x02,
    "ABS_RZ": 0x05,
}


@dataclass
class GamepadState:
    lock: threading.RLock = field(default_factory=threading.RLock)
    connected: bool = False
    name: str = ""
    stick_x: float = 0.0
    lt: float = 0.0
    rt: float = 0.0
    stick_calib: AxisCalib = field(default_factory=lambda: DEFAULT_STICK_CALIB)
    lt_calib: AxisCalib = field(default_factory=lambda: DEFAULT_TRIGGER_CALIB)
    rt_calib: AxisCalib = field(default_factory=lambda: DEFAULT_TRIGGER_CALIB)

    def reset_analog(self) -> None:
        self.stick_x = 0.0
        self.lt = 0.0
        self.rt = 0.0

    def disconnect(self) -> None:
        self.connected = False
        self.name = ""
        self.reset_analog()


def _linux_read_absinfo(device_path: str, axis_code: int) -> AxisCalib | None:
    if sys.platform != "linux":
        return None

    import fcntl
    import struct

    try:
        fd = open(device_path, "rb")
        try:
            # EVIOCGABS(axis): 6 x int32 (value, min, max, fuzz, flat, resolution)
            buf = fcntl.ioctl(fd, 0x80104540 + axis_code, bytes(24))
        finally:
            fd.close()
    except OSError:
        return None

    _value, minimum, maximum, _fuzz, flat, _resolution = struct.unpack("6i", buf)
    if maximum <= minimum:
        return None
    return AxisCalib(minimum=minimum, maximum=maximum, flat=max(flat, 0))


def load_axis_calibrations(gamepad: Any, log: LogFn) -> tuple[AxisCalib, AxisCalib, AxisCalib]:
    stick = DEFAULT_STICK_CALIB
    lt = DEFAULT_TRIGGER_CALIB
    rt = DEFAULT_TRIGGER_CALIB

    if sys.platform == "linux":
        device_path = getattr(gamepad, "_device_path", None) or getattr(
            gamepad, "_character_device_path", None
        )
        if device_path:
            stick_info = _linux_read_absinfo(device_path, _LINUX_ABS["ABS_X"])
            lt_info = _linux_read_absinfo(device_path, _LINUX_ABS["ABS_Z"])
            rt_info = _linux_read_absinfo(device_path, _LINUX_ABS["ABS_RZ"])
            if stick_info is not None:
                stick = stick_info
            if lt_info is not None:
                lt = lt_info
            if rt_info is not None:
                rt = rt_info
            log(
                "info",
                f"Gamepad calib stick=[{stick.minimum},{stick.maximum}] flat={stick.flat} "
                f"lt=[{lt.minimum},{lt.maximum}] rt=[{rt.minimum},{rt.maximum}]",
            )
        return stick, lt, rt

    log("info", "Gamepad calib: using default stick/trigger ranges")
    return stick, lt, rt


def _apply_calibrations(state: GamepadState, gamepad: Any, log: LogFn) -> None:
    stick, lt, rt = load_axis_calibrations(gamepad, log)
    with state.lock:
        state.stick_calib = stick
        state.lt_calib = lt
        state.rt_calib = rt
        state.reset_analog()


def _apply_absolute(state: GamepadState, code: str, raw: int) -> None:
    if code == STEER_CODE:
        state.stick_x = normalize_stick_raw(raw, state.stick_calib)
    elif code in LT_CODES:
        state.lt = normalize_trigger_raw(raw, state.lt_calib)
    elif code in RT_CODES:
        state.rt = normalize_trigger_raw(raw, state.rt_calib)


def _hat_to_dpad(code: str, raw: int) -> str | None:
    if code == HAT_X_CODE and raw != 0:
        return "DPAD_LEFT" if raw < 0 else "DPAD_RIGHT"
    if code == HAT_Y_CODE and raw != 0:
        return "DPAD_UP" if raw < 0 else "DPAD_DOWN"
    return None


def _try_trigger_movement(binding_code: str, *, now: float, last_fire_wall: float) -> float:
    from backend import get_movement_bindings, trigger_movement

    if (now - last_fire_wall) < GAMEPAD_MACRO_DEBOUNCE_S:
        return last_fire_wall

    bindings = get_movement_bindings()
    movement_id = bindings.gamepad.get(binding_code)
    if not movement_id:
        return last_fire_wall

    if trigger_movement(movement_id):
        return now
    return last_fire_wall


def _should_fire_lights(
    *,
    pressed: bool,
    was_down: bool,
    last_fire_wall: float,
    now: float,
    debounce_s: float,
) -> tuple[bool, bool, float]:
    is_down = pressed
    if is_down and not was_down and (now - last_fire_wall) >= debounce_s:
        return True, is_down, now
    return False, is_down, last_fire_wall


def _refresh_connection(
    state: GamepadState,
    log: LogFn,
    *,
    was_connected: bool,
    calib_loaded: bool,
) -> tuple[bool, bool]:
    from inputs import devices

    gamepads = devices.gamepads
    if not gamepads:
        with state.lock:
            if state.connected:
                state.disconnect()
        if was_connected:
            log("info", "Gamepad disconnected")
        return False, False

    gamepad = gamepads[0]
    name = str(gamepad.name or "gamepad")
    newly_connected = False
    with state.lock:
        newly_connected = not state.connected
        state.connected = True
        state.name = name

    if newly_connected and not was_connected:
        log("ok", f"Gamepad connected: {name}")

    need_calib = newly_connected or not calib_loaded
    if need_calib:
        _apply_calibrations(state, gamepad, log)
        calib_loaded = True

    return True, calib_loaded


def inputs_listener_loop(
    *,
    runtime,
    state: GamepadState,
    enqueue_command: EnqueueFn,
    log: LogFn,
    stop_event: threading.Event,
) -> None:
    from inputs import get_gamepad

    lights_was_down = False
    last_lights_wall = 0.0
    neutral_was_down = False
    last_neutral_wall = 0.0
    last_macro_wall = 0.0
    last_hat_x = 0
    last_hat_y = 0
    button_was_down: dict[str, bool] = {}
    was_connected = False
    calib_loaded = False
    permission_warned = False

    while not stop_event.is_set():
        try:
            was_connected, calib_loaded = _refresh_connection(
                state,
                log,
                was_connected=was_connected,
                calib_loaded=calib_loaded,
            )
            if not was_connected:
                calib_loaded = False
                stop_event.wait(1.0)
                continue

            events = get_gamepad()
        except PermissionError:
            if not permission_warned:
                log(
                    "error",
                    "Gamepad permission denied — add user to 'input' group and re-login",
                )
                permission_warned = True
            with state.lock:
                state.disconnect()
            was_connected = False
            calib_loaded = False
            stop_event.wait(1.0)
            continue
        except OSError as exc:
            log("warn", f"Gamepad read failed: {exc}")
            with state.lock:
                state.disconnect()
            was_connected = False
            calib_loaded = False
            stop_event.wait(1.0)
            continue
        except Exception as exc:
            log("warn", f"Gamepad listener error: {exc}")
            with state.lock:
                state.disconnect()
            was_connected = False
            calib_loaded = False
            stop_event.wait(1.0)
            continue

        permission_warned = False

        for event in events:
            if event.ev_type == "Absolute":
                raw = int(event.state)
                if event.code in (HAT_X_CODE, HAT_Y_CODE):
                    prev = last_hat_x if event.code == HAT_X_CODE else last_hat_y
                    if event.code == HAT_X_CODE:
                        last_hat_x = raw
                    else:
                        last_hat_y = raw
                    if raw != 0 and raw != prev:
                        dpad = _hat_to_dpad(event.code, raw)
                        if dpad is not None:
                            now = time.monotonic()
                            last_macro_wall = _try_trigger_movement(
                                dpad,
                                now=now,
                                last_fire_wall=last_macro_wall,
                            )
                    continue

                with state.lock:
                    _apply_absolute(state, event.code, raw)
                continue

            if event.ev_type != "Key":
                continue

            now = time.monotonic()

            binding_code = event_code_to_binding(event.code)
            if binding_code is not None and event.code != GAMEPAD_NEUTRAL_BUTTON:
                was_down = button_was_down.get(event.code, False)
                fire, button_was_down[event.code], _ = _should_fire_lights(
                    pressed=bool(event.state),
                    was_down=was_down,
                    last_fire_wall=last_macro_wall,
                    now=now,
                    debounce_s=GAMEPAD_MACRO_DEBOUNCE_S,
                )
                if fire:
                    prev_wall = last_macro_wall
                    last_macro_wall = _try_trigger_movement(
                        binding_code,
                        now=now,
                        last_fire_wall=last_macro_wall,
                    )
                    if last_macro_wall != prev_wall:
                        continue

            if event.code == GAMEPAD_NEUTRAL_BUTTON:
                fire, neutral_was_down, last_neutral_wall = _should_fire_lights(
                    pressed=bool(event.state),
                    was_down=neutral_was_down,
                    last_fire_wall=last_neutral_wall,
                    now=now,
                    debounce_s=GAMEPAD_NEUTRAL_DEBOUNCE_S,
                )
                if fire:
                    with runtime.lock:
                        serial_ok = runtime.ui.serial_connected
                    if serial_ok:
                        from movement_runner import notify_manual_control

                        notify_manual_control("gamepad")
                        enqueue_command("neutral", {})
                continue

            if event.code != GAMEPAD_LIGHTS_BUTTON:
                continue

            fire, lights_was_down, last_lights_wall = _should_fire_lights(
                pressed=bool(event.state),
                was_down=lights_was_down,
                last_fire_wall=last_lights_wall,
                now=now,
                debounce_s=GAMEPAD_LIGHTS_DEBOUNCE_S,
            )
            if not fire:
                continue

            with runtime.lock:
                serial_ok = runtime.ui.serial_connected
            if serial_ok:
                enqueue_command("cycle_lights", {})


def _run_self_tests() -> None:
    fire, down, _ = _should_fire_lights(
        pressed=True,
        was_down=False,
        last_fire_wall=0.0,
        now=1.0,
        debounce_s=0.25,
    )
    assert fire is True
    assert down is True
    print("gamepad_backend self-tests ok")


if __name__ == "__main__":
    _run_self_tests()
