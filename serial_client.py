"""Serial worker thread: connect/disconnect, command queue, status broadcast."""

from __future__ import annotations

import queue
import threading
import time
from typing import Any, Callable

import serial

import commands as rc_commands
from config import HEARTBEAT_INTERVAL_S, STATUS_BROADCAST_HZ
from movement_runner import handle_movement_command
from serial_protocol import SerialSession

_MOVEMENT_COMMANDS = frozenset({"run_movement", "cancel_movement"})

LogFn = Callable[[str, str], None]
EnqueueFn = Callable[[dict[str, Any]], None]


def _apply_device_info(runtime, info: dict[str, Any]) -> None:
    with runtime.lock:
        runtime.bounds.throttle_forward_max = int(
            info.get("throttle_forward_level_max", runtime.bounds.throttle_forward_max)
        )
        runtime.bounds.throttle_above_max = int(
            info.get("throttle_above_level_max", runtime.bounds.throttle_above_max)
        )
        runtime.bounds.steer_min = int(info.get("steer_level_min", runtime.bounds.steer_min))
        runtime.bounds.steer_max = int(info.get("steer_level_max", runtime.bounds.steer_max))
        runtime.ui.firmware = str(info.get("firmware", "—"))
        runtime.ui.protocol = int(info.get("protocol", 0))
        runtime.lights_mode = str(info.get("lights_assumed_mode", runtime.lights_mode))


def _apply_state(runtime, state: dict[str, Any]) -> None:
    with runtime.lock:
        runtime.throttle_level = int(state.get("throttle_level", 0))
        runtime.steer_level = int(state.get("steer_level", 0))


def _close_serial(ser: serial.Serial | None, session: SerialSession, log: LogFn) -> None:
    if ser is None:
        return
    try:
        session.send_command(ser, "set_controls", {"throttle_level": 0, "steer_level": 0}, log=log)
    except Exception as exc:
        log("warn", f"Neutral on disconnect failed: {exc}")
    try:
        ser.close()
    except Exception:
        pass


def _connect_serial(
    *,
    runtime,
    port: str,
    baud: int,
    session: SerialSession,
    log: LogFn,
) -> serial.Serial | None:
    session.reset_buffer()
    log("info", f"Opening serial {port} @ {baud}")

    ser = serial.Serial(port, baud, timeout=0.1)
    ser.dtr = True
    ser.rts = False

    log("info", "Waiting for ready event...")
    ready = session.wait_for_ready(ser, timeout_s=6.0, log=log)
    if ready:
        log("ok", f"RC car ready: {ready.get('data')}")
    else:
        log("warn", "No ready event (continuing)")

    info = session.send_command(ser, "get_device_info", {}, log=log)
    if info.get("status") != "ok":
        raise RuntimeError(f"get_device_info failed: {info}")
    _apply_device_info(runtime, info)
    log("ok", f"Device firmware {info.get('firmware')} protocol {info.get('protocol')}")

    state = session.send_command(ser, "get_state", {}, log=log)
    if state.get("status") == "ok":
        _apply_state(runtime, state)

    with runtime.lock:
        runtime.ui.serial_connected = True
        runtime.ui.serial_port = port

    return ser


def drain_movement_only_commands(
    *,
    inbound: queue.Queue,
    enqueue_outbound: EnqueueFn,
    log: LogFn,
) -> None:
    pending: list[dict[str, Any]] = []
    try:
        while True:
            pending.append(dict(inbound.get_nowait()))
    except queue.Empty:
        pass

    for item in pending:
        if item.get("type") != "command":
            inbound.put(item)
            continue
        name = str(item.get("command", ""))
        if name not in _MOVEMENT_COMMANDS:
            inbound.put(item)
            continue
        params = dict(item.get("params") or {})
        log("info", f"CMD {name} params={params}")
        try:
            ok, label = handle_movement_command(name, params)
            enqueue_outbound(
                {
                    "type": "command_ack",
                    "command": label,
                    "success": ok,
                    "timestamp": int(time.time() * 1000),
                }
            )
        except Exception as exc:
            log("error", f"CMD FAILED {name}: {exc}")
            enqueue_outbound(
                {
                    "type": "command_ack",
                    "command": name,
                    "success": False,
                    "error": str(exc),
                    "timestamp": int(time.time() * 1000),
                }
            )


def drain_inbound_cmds(
    *,
    inbound: queue.Queue,
    runtime,
    session: SerialSession,
    ser: serial.Serial,
    enqueue_outbound: EnqueueFn,
    log: LogFn,
) -> None:
    try:
        while True:
            item = dict(inbound.get_nowait())
            if item.get("type") != "command":
                continue
            cmd_name = item.get("command")
            if cmd_name is None:
                continue
            name = str(cmd_name)
            params = dict(item.get("params") or {})
            log("info", f"CMD {name} params={params}")
            try:
                if name in _MOVEMENT_COMMANDS:
                    ok, label = handle_movement_command(name, params)
                    enqueue_outbound(
                        {
                            "type": "command_ack",
                            "command": label,
                            "success": ok,
                            "timestamp": int(time.time() * 1000),
                        }
                    )
                    continue

                ok, label = rc_commands.apply_frontend_command(
                    runtime=runtime,
                    command=name,
                    params=params,
                    session=session,
                    ser=ser,
                    log=log,
                )
                enqueue_outbound(
                    {
                        "type": "command_ack",
                        "command": label,
                        "success": ok,
                        "timestamp": int(time.time() * 1000),
                    }
                )
            except Exception as exc:
                log("error", f"CMD FAILED {name}: {exc}")
                enqueue_outbound(
                    {
                        "type": "command_ack",
                        "command": name,
                        "success": False,
                        "error": str(exc),
                        "timestamp": int(time.time() * 1000),
                    }
                )
    except queue.Empty:
        return


def maybe_publish_status(
    *,
    runtime,
    enqueue_outbound: EnqueueFn,
    prev: dict[str, Any] | None,
    force: bool = False,
) -> dict[str, Any]:
    snap = runtime.status_snapshot()
    if force or prev is None or snap != prev:
        enqueue_outbound({"type": "status", **snap, "timestamp": int(time.time() * 1000)})
    return snap


def serial_worker_loop(
    *,
    runtime,
    inbound_commands: queue.Queue,
    enqueue_outbound: EnqueueFn,
    log: LogFn,
    stop_event: threading.Event,
) -> None:
    session = SerialSession()
    ser: serial.Serial | None = None
    prev_status: dict[str, Any] | None = None
    last_status_publish = 0.0
    last_heartbeat = 0.0
    status_interval = 1.0 / max(STATUS_BROADCAST_HZ, 0.1)

    while not stop_event.is_set():
        with runtime.lock:
            want_connect = runtime.connect_requested
            want_disconnect = runtime.disconnect_requested
            port = runtime.serial_port
            baud = runtime.serial_baud

        if want_disconnect and ser is not None:
            log("info", "Disconnecting serial")
            _close_serial(ser, session, log)
            ser = None
            session.reset_buffer()
            with runtime.lock:
                runtime.ui.serial_connected = False
                runtime.disconnect_requested = False
            prev_status = maybe_publish_status(
                runtime=runtime,
                enqueue_outbound=enqueue_outbound,
                prev=prev_status,
                force=True,
            )

        if want_connect and ser is None and port:
            with runtime.lock:
                runtime.connect_requested = False
            try:
                ser = _connect_serial(runtime=runtime, port=port, baud=baud, session=session, log=log)
                prev_status = maybe_publish_status(
                    runtime=runtime,
                    enqueue_outbound=enqueue_outbound,
                    prev=prev_status,
                    force=True,
                )
                last_heartbeat = time.monotonic()
            except Exception as exc:
                log("error", f"Serial connect failed: {exc}")
                ser = None
                with runtime.lock:
                    runtime.ui.serial_connected = False
                prev_status = maybe_publish_status(
                    runtime=runtime,
                    enqueue_outbound=enqueue_outbound,
                    prev=prev_status,
                    force=True,
                )

        if ser is None:
            drain_movement_only_commands(
                inbound=inbound_commands,
                enqueue_outbound=enqueue_outbound,
                log=log,
            )
            stop_event.wait(0.05)
            continue

        drain_inbound_cmds(
            inbound=inbound_commands,
            runtime=runtime,
            session=session,
            ser=ser,
            enqueue_outbound=enqueue_outbound,
            log=log,
        )

        session.read_lines(ser, timeout_s=0.02, accept_events=True, accept_responses=False, log=None)

        now = time.monotonic()
        if now - last_status_publish >= status_interval:
            prev_status = maybe_publish_status(
                runtime=runtime,
                enqueue_outbound=enqueue_outbound,
                prev=prev_status,
            )
            last_status_publish = now

        if now - last_heartbeat >= HEARTBEAT_INTERVAL_S:
            try:
                session.send_command(ser, "heartbeat", {}, timeout_s=3.0, log=None)
            except Exception as exc:
                log("warn", f"Heartbeat failed: {exc}")
            last_heartbeat = now

        stop_event.wait(0.01)

    if ser is not None:
        _close_serial(ser, session, log)
        with runtime.lock:
            runtime.ui.serial_connected = False
