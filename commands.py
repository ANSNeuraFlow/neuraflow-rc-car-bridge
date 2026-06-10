"""Translate GUI / WebSocket commands into serial protocol actions."""

from __future__ import annotations

from typing import Any

from config import LIGHTS_MODES
from serial_protocol import SerialSession


def _clamp_throttle(runtime, level: int) -> int:
    with runtime.lock:
        bounds = runtime.bounds
        max_fwd = bounds.throttle_forward_max
        if runtime.max_forward_level is not None:
            max_fwd = min(max_fwd, int(runtime.max_forward_level))
        min_level = -bounds.throttle_above_max
    return max(min_level, min(max_fwd, int(level)))


def _clamp_steer(runtime, level: int) -> int:
    with runtime.lock:
        bounds = runtime.bounds
    return max(bounds.steer_min, min(bounds.steer_max, int(level)))


def _advance_lights_mode(runtime) -> str:
    with runtime.lock:
        current = runtime.lights_mode
        try:
            idx = LIGHTS_MODES.index(current)
        except ValueError:
            idx = 0
        runtime.lights_mode = LIGHTS_MODES[(idx + 1) % len(LIGHTS_MODES)]
        return runtime.lights_mode


def apply_frontend_command(
    *,
    runtime,
    command: str,
    params: dict[str, Any],
    session: SerialSession,
    ser: object,
    log,
) -> tuple[bool, str]:
    """Returns (success, command_label_for_ack)."""

    name = str(command)

    if name == "set_controls":
        data: dict[str, int] = {}
        if "throttle_level" in params:
            data["throttle_level"] = _clamp_throttle(runtime, int(params["throttle_level"]))
        if "steer_level" in params:
            data["steer_level"] = _clamp_steer(runtime, int(params["steer_level"]))
        if not data:
            return False, name

        resp = session.send_command(ser, "set_controls", data, log=log)
        ok = resp.get("status") == "ok"
        if ok:
            with runtime.lock:
                if "throttle_level" in data:
                    runtime.throttle_level = data["throttle_level"]
                if "steer_level" in data:
                    runtime.steer_level = data["steer_level"]
                runtime.ui.commands_sent_total += 1
        return ok, name

    if name == "throttle_step":
        delta = int(params.get("delta", 0))
        with runtime.lock:
            new_level = _clamp_throttle(runtime, runtime.throttle_level + delta)
        return apply_frontend_command(
            runtime=runtime,
            command="set_controls",
            params={"throttle_level": new_level},
            session=session,
            ser=ser,
            log=log,
        )

    if name == "steer_step":
        delta = int(params.get("delta", 0))
        with runtime.lock:
            new_level = _clamp_steer(runtime, runtime.steer_level + delta)
        return apply_frontend_command(
            runtime=runtime,
            command="set_controls",
            params={"steer_level": new_level},
            session=session,
            ser=ser,
            log=log,
        )

    if name == "neutral":
        return apply_frontend_command(
            runtime=runtime,
            command="set_controls",
            params={"throttle_level": 0, "steer_level": 0},
            session=session,
            ser=ser,
            log=log,
        )

    if name == "brake":
        level = int(params.get("throttle_level", -1))
        return apply_frontend_command(
            runtime=runtime,
            command="set_controls",
            params={"throttle_level": level},
            session=session,
            ser=ser,
            log=log,
        )

    if name == "cycle_lights":
        resp = session.send_command(ser, "cycle_lights", {}, log=log)
        ok = resp.get("status") == "ok"
        if ok:
            mode = _advance_lights_mode(runtime)
            log("info", f"Lights mode → {mode}")
            with runtime.lock:
                runtime.ui.commands_sent_total += 1
        return ok, name

    log("warn", f"Unknown command: {name}")
    return False, name
