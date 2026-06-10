"""Gamepad polling thread with Forza-style RT/LT + left-stick steering."""

from __future__ import annotations

import threading
import time
from typing import Any, Callable

from config import (
    GAMEPAD_DEADZONE,
    GAMEPAD_POLL_HZ,
    GAMEPAD_SEND_MIN_INTERVAL_S,
    GAMEPAD_STEER_SEND_STEP,
    GAMEPAD_STEER_SMOOTH_ALPHA,
)
from gamepad_backend import GamepadState, inputs_listener_loop
from gamepad_mapping import (
    forza_steer_level,
    forza_throttle_level,
    is_input_active,
    should_send_steer_level,
    smooth_value,
)

LogFn = Callable[[str, str], None]
EnqueueFn = Callable[[str, dict[str, Any]], None]


def _send_neutral(enqueue_command: EnqueueFn) -> None:
    enqueue_command("neutral", {})


def gamepad_worker_loop(
    *,
    runtime,
    enqueue_command: EnqueueFn,
    log: LogFn,
    stop_event: threading.Event,
) -> None:
    poll_interval = 1.0 / max(GAMEPAD_POLL_HZ, 1.0)
    state = GamepadState()

    listener = threading.Thread(
        target=inputs_listener_loop,
        kwargs={
            "runtime": runtime,
            "state": state,
            "enqueue_command": enqueue_command,
            "log": log,
            "stop_event": stop_event,
        },
        daemon=True,
        name="gamepad-inputs-listener",
    )
    listener.start()

    last_sent_throttle: int | None = None
    last_sent_steer: int | None = None
    last_send_wall = 0.0
    was_active = False
    prev_connected = False
    smooth_stick_x = 0.0

    def reset_send_state(send_neutral: bool) -> None:
        nonlocal last_sent_throttle, last_sent_steer, was_active, smooth_stick_x
        last_sent_throttle = None
        last_sent_steer = None
        smooth_stick_x = 0.0
        with runtime.lock:
            runtime.ui.gamepad_connected = False
            runtime.ui.gamepad_name = ""
            runtime.ui.gamepad_active = False
        if send_neutral and was_active:
            with runtime.lock:
                serial_ok = runtime.ui.serial_connected
            if serial_ok:
                _send_neutral(enqueue_command)
        was_active = False

    while not stop_event.is_set():
        with runtime.lock:
            enabled = runtime.ui.gamepad_enabled
            serial_ok = runtime.ui.serial_connected

        with state.lock:
            connected = state.connected
            stick_x = state.stick_x
            lt = state.lt
            rt = state.rt
            name = state.name

        with runtime.lock:
            runtime.ui.gamepad_connected = connected
            runtime.ui.gamepad_name = name if connected else ""

        if connected and not prev_connected:
            last_sent_throttle = None
            last_sent_steer = None
            smooth_stick_x = stick_x

        if prev_connected and not connected:
            reset_send_state(send_neutral=True)

        prev_connected = connected

        if not enabled or not connected:
            stop_event.wait(poll_interval)
            continue

        smooth_stick_x = smooth_value(smooth_stick_x, stick_x, GAMEPAD_STEER_SMOOTH_ALPHA)

        with runtime.lock:
            bounds = runtime.bounds
            max_fwd_cap = runtime.max_forward_level
            throttle = forza_throttle_level(
                rt,
                lt,
                forward_max=bounds.throttle_forward_max,
                above_max=bounds.throttle_above_max,
                max_forward_cap=max_fwd_cap,
                deadzone=GAMEPAD_DEADZONE,
            )
            steer = forza_steer_level(
                smooth_stick_x,
                steer_min=bounds.steer_min,
                steer_max=bounds.steer_max,
                deadzone=GAMEPAD_DEADZONE,
            )
            active = is_input_active(smooth_stick_x, rt, lt, deadzone=GAMEPAD_DEADZONE)
            runtime.ui.gamepad_active = active

        if serial_ok:
            now = time.monotonic()
            throttle_changed = throttle != last_sent_throttle
            steer_changed = should_send_steer_level(
                steer,
                last_sent_steer,
                min_step=GAMEPAD_STEER_SEND_STEP,
            )
            due = (now - last_send_wall) >= GAMEPAD_SEND_MIN_INTERVAL_S
            if (throttle_changed or steer_changed) and due:
                enqueue_command(
                    "set_controls",
                    {"throttle_level": throttle, "steer_level": steer},
                )
                last_sent_throttle = throttle
                last_sent_steer = steer
                last_send_wall = now

        was_active = active
        stop_event.wait(poll_interval)

    reset_send_state(send_neutral=True)
