"""Backend threads: serial worker + WebSocket asyncio server."""

from __future__ import annotations

import asyncio
import queue
import threading
from datetime import datetime
from typing import Any

from config import MAX_FORWARD_LEVEL, SERIAL_BAUD, SERIAL_PORT, WS_HOST, WS_PORT
from gamepad_worker import gamepad_worker_loop
from serial_client import serial_worker_loop
from state import SharedRuntime
from ws_server import websocket_main

log_queue: queue.Queue[tuple[str, str]] = queue.Queue()
inbound_commands: queue.Queue[dict[str, Any]] = queue.Queue()
outbound_messages: queue.Queue[dict[str, Any]] = queue.Queue()
stop_event = threading.Event()

runtime = SharedRuntime(
    serial_port=SERIAL_PORT,
    serial_baud=SERIAL_BAUD,
    ws_host=WS_HOST,
    ws_port=WS_PORT,
    max_forward_level=MAX_FORWARD_LEVEL,
)


def log(level: str, msg: str) -> None:
    ts = datetime.now().strftime("%H:%M:%S")
    log_queue.put((level, f"[{ts}] {msg}"))


def enqueue_outbound(pkt: dict[str, Any]) -> None:
    outbound_messages.put(pkt)


def request_connect(port: str, baud: int | None = None) -> None:
    with runtime.lock:
        runtime.serial_port = port.strip()
        if baud is not None:
            runtime.serial_baud = int(baud)
        runtime.connect_requested = True
        runtime.disconnect_requested = False


def request_disconnect() -> None:
    with runtime.lock:
        runtime.disconnect_requested = True
        runtime.connect_requested = False


def enqueue_command(command: str, params: dict[str, Any] | None = None) -> None:
    inbound_commands.put({"type": "command", "command": command, "params": params or {}})


def start_backend() -> None:
    stop_event.clear()

    serial_thread = threading.Thread(
        target=serial_worker_loop,
        kwargs={
            "runtime": runtime,
            "inbound_commands": inbound_commands,
            "enqueue_outbound": enqueue_outbound,
            "log": log,
            "stop_event": stop_event,
        },
        daemon=True,
        name="serial-worker",
    )

    def ws_runner() -> None:
        asyncio.run(
            websocket_main(
                runtime=runtime,
                ws_host=runtime.ws_host,
                ws_port=runtime.ws_port,
                inbound_commands=inbound_commands,
                outbound_messages=outbound_messages,
                stop_event=stop_event,
                log=log,
            )
        )

    ws_thread = threading.Thread(target=ws_runner, daemon=True, name="ws-server")

    gamepad_thread = threading.Thread(
        target=gamepad_worker_loop,
        kwargs={
            "runtime": runtime,
            "enqueue_command": enqueue_command,
            "log": log,
            "stop_event": stop_event,
        },
        daemon=True,
        name="gamepad-worker",
    )

    serial_thread.start()
    ws_thread.start()
    gamepad_thread.start()
    log("info", "RC car bridge backend started")


def stop_backend() -> None:
    request_disconnect()
    stop_event.set()
