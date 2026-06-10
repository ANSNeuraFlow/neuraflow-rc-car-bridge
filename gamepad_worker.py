"""Gamepad polling thread with Forza-style RT/LT + left-stick steering."""

from __future__ import annotations

import os
import threading
import time
from typing import Any, Callable

from config import (
    GAMEPAD_DEADZONE,
    GAMEPAD_ENABLED_DEFAULT,
    GAMEPAD_POLL_HZ,
    GAMEPAD_SEND_MIN_INTERVAL_S,
)
from gamepad_mapping import (
    AxisMapping,
    forza_steer_level,
    forza_throttle_level,
    is_input_active,
    normalize_trigger,
    resolve_axis_mapping,
)

LogFn = Callable[[str, str], None]
EnqueueFn = Callable[[str, dict[str, Any]], None]


def _init_pygame():
    os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
    import pygame

    if not pygame.get_init():
        pygame.init()
    if not pygame.joystick.get_init():
        pygame.joystick.init()
    return pygame


def _read_axes(joystick: Any) -> list[float]:
    return [float(joystick.get_axis(i)) for i in range(joystick.get_numaxes())]


def _open_first_joystick(pygame: Any, log: LogFn) -> tuple[Any | None, AxisMapping | None]:
    count = pygame.joystick.get_count()
    if count <= 0:
        return None, None

    stick = pygame.joystick.Joystick(0)
    stick.init()
    axes = _read_axes(stick)
    mapping = resolve_axis_mapping(stick.get_numaxes(), axes)
    log("ok", f"Gamepad connected: {stick.get_name()}")
    return stick, mapping


def _close_joystick(pygame: Any, stick: Any | None) -> None:
    if stick is not None:
        try:
            stick.quit()
        except Exception:
            pass
    pygame.joystick.quit()
    pygame.joystick.init()


def _send_neutral(enqueue_command: EnqueueFn) -> None:
    enqueue_command("neutral", {})


def gamepad_worker_loop(
    *,
    runtime,
    enqueue_command: EnqueueFn,
    log: LogFn,
    stop_event: threading.Event,
) -> None:
    pygame = _init_pygame()
    poll_interval = 1.0 / max(GAMEPAD_POLL_HZ, 1.0)

    stick: Any | None = None
    mapping: AxisMapping | None = None
    last_sent_throttle: int | None = None
    last_sent_steer: int | None = None
    last_send_wall = 0.0
    was_active = False

    def clear_stick_state(send_neutral: bool) -> None:
        nonlocal stick, mapping, last_sent_throttle, last_sent_steer, was_active
        if stick is not None:
            _close_joystick(pygame, stick)
        stick = None
        mapping = None
        last_sent_throttle = None
        last_sent_steer = None
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
        for event in pygame.event.get():
            if event.type == pygame.JOYDEVICEADDED and stick is None:
                try:
                    stick, mapping = _open_first_joystick(pygame, log)
                    if stick is not None:
                        with runtime.lock:
                            runtime.ui.gamepad_connected = True
                            runtime.ui.gamepad_name = stick.get_name()
                except Exception as exc:
                    log("warn", f"Gamepad open failed: {exc}")
            elif event.type == pygame.JOYDEVICEREMOVED:
                log("info", "Gamepad disconnected")
                clear_stick_state(send_neutral=True)

        with runtime.lock:
            enabled = runtime.ui.gamepad_enabled
            serial_ok = runtime.ui.serial_connected

        if stick is None and pygame.joystick.get_count() > 0:
            try:
                stick, mapping = _open_first_joystick(pygame, log)
                if stick is not None:
                    with runtime.lock:
                        runtime.ui.gamepad_connected = True
                        runtime.ui.gamepad_name = stick.get_name()
            except Exception as exc:
                log("warn", f"Gamepad open failed: {exc}")

        if stick is None or mapping is None or not enabled:
            stop_event.wait(poll_interval)
            continue

        axes = _read_axes(stick)
        steer_raw = axes[mapping.steer] if mapping.steer < len(axes) else 0.0
        lt_raw = axes[mapping.lt] if mapping.lt < len(axes) else -1.0
        rt_raw = axes[mapping.rt] if mapping.rt < len(axes) else -1.0

        lt = normalize_trigger(lt_raw)
        rt = normalize_trigger(rt_raw)

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
                steer_raw,
                steer_min=bounds.steer_min,
                steer_max=bounds.steer_max,
                deadzone=GAMEPAD_DEADZONE,
            )
            active = is_input_active(steer_raw, rt, lt, deadzone=GAMEPAD_DEADZONE)
            runtime.ui.gamepad_active = active

        if serial_ok:
            now = time.monotonic()
            changed = throttle != last_sent_throttle or steer != last_sent_steer
            due = (now - last_send_wall) >= GAMEPAD_SEND_MIN_INTERVAL_S
            if changed and due:
                enqueue_command(
                    "set_controls",
                    {"throttle_level": throttle, "steer_level": steer},
                )
                last_sent_throttle = throttle
                last_sent_steer = steer
                last_send_wall = now

        was_active = active
        stop_event.wait(poll_interval)

    clear_stick_state(send_neutral=True)
    try:
        pygame.quit()
    except Exception:
        pass
