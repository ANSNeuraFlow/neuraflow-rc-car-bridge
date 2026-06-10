"""Headless gamepad input via the inputs library (evdev / XInput)."""

from __future__ import annotations

import threading
import time
from dataclasses import dataclass, field
from typing import Any, Callable

from config import GAMEPAD_LIGHTS_BUTTON, GAMEPAD_LIGHTS_DEBOUNCE_S
from gamepad_mapping import normalize_stick_abs, normalize_trigger_abs

LogFn = Callable[[str, str], None]
EnqueueFn = Callable[[str, dict[str, Any]], None]

STEER_CODE = "ABS_X"
LT_CODES = ("ABS_Z", "ABS_BRAKE")
RT_CODES = ("ABS_RZ", "ABS_GAS")


@dataclass
class GamepadState:
    lock: threading.RLock = field(default_factory=threading.RLock)
    connected: bool = False
    name: str = ""
    stick_x: float = 0.0
    lt: float = 0.0
    rt: float = 0.0

    def reset_analog(self) -> None:
        self.stick_x = 0.0
        self.lt = 0.0
        self.rt = 0.0

    def disconnect(self) -> None:
        self.connected = False
        self.name = ""
        self.reset_analog()


def _apply_absolute(state: GamepadState, code: str, raw: int) -> None:
    if code == STEER_CODE:
        state.stick_x = normalize_stick_abs(raw)
    elif code in LT_CODES:
        state.lt = normalize_trigger_abs(raw)
    elif code in RT_CODES:
        state.rt = normalize_trigger_abs(raw)


def _should_fire_lights(
    *,
    pressed: bool,
    was_down: bool,
    last_fire_wall: float,
    now: float,
    debounce_s: float,
) -> tuple[bool, bool, float]:
    """Return (fire, new_was_down, new_last_fire_wall)."""

    is_down = pressed
    if is_down and not was_down and (now - last_fire_wall) >= debounce_s:
        return True, is_down, now
    return False, is_down, last_fire_wall


def _refresh_connection(state: GamepadState, log: LogFn, *, was_connected: bool) -> bool:
    from inputs import devices

    gamepads = devices.gamepads
    if not gamepads:
        with state.lock:
            if state.connected:
                state.disconnect()
        if was_connected:
            log("info", "Gamepad disconnected")
        return False

    name = str(gamepads[0].name or "gamepad")
    with state.lock:
        newly_connected = not state.connected
        state.connected = True
        state.name = name
    if newly_connected and not was_connected:
        log("ok", f"Gamepad connected: {name}")
    return True


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
    was_connected = False
    permission_warned = False

    while not stop_event.is_set():
        try:
            was_connected = _refresh_connection(state, log, was_connected=was_connected)
            if not was_connected:
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
            stop_event.wait(1.0)
            continue
        except OSError as exc:
            log("warn", f"Gamepad read failed: {exc}")
            with state.lock:
                state.disconnect()
            was_connected = False
            stop_event.wait(1.0)
            continue
        except Exception as exc:
            log("warn", f"Gamepad listener error: {exc}")
            with state.lock:
                state.disconnect()
            was_connected = False
            stop_event.wait(1.0)
            continue

        permission_warned = False

        for event in events:
            if event.ev_type == "Absolute":
                with state.lock:
                    _apply_absolute(state, event.code, int(event.state))
                continue

            if event.ev_type != "Key" or event.code != GAMEPAD_LIGHTS_BUTTON:
                continue

            now = time.monotonic()
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
    fire, down, t = _should_fire_lights(
        pressed=True,
        was_down=False,
        last_fire_wall=0.0,
        now=1.0,
        debounce_s=0.25,
    )
    assert fire is True
    assert down is True

    fire, down, _ = _should_fire_lights(
        pressed=True,
        was_down=True,
        last_fire_wall=1.0,
        now=1.1,
        debounce_s=0.25,
    )
    assert fire is False

    fire, _, _ = _should_fire_lights(
        pressed=True,
        was_down=False,
        last_fire_wall=1.0,
        now=1.1,
        debounce_s=0.25,
    )
    assert fire is False

    print("gamepad_backend self-tests ok")


if __name__ == "__main__":
    _run_self_tests()
