"""Async WebSocket server for the RC car bridge JSON protocol."""

from __future__ import annotations

import asyncio
import json
import queue
import threading
import time
from typing import Any, Callable

import websockets

LogFn = Callable[[str, str], None]


def _dump(obj: dict[str, Any]) -> str:
    return json.dumps(obj, separators=(",", ":"))


async def multicast(clients: set[Any], pkt: dict[str, Any]) -> None:
    if not clients:
        return
    blob = _dump(pkt)
    dead: list[Any] = []
    for ws in list(clients):
        try:
            await ws.send(blob)
        except Exception:
            dead.append(ws)
    for ws in dead:
        clients.discard(ws)


async def broadcast_loop(runtime, outbound: queue.Queue, clients: set[Any], stop_event: threading.Event) -> None:
    while not stop_event.is_set():
        drained: list[dict[str, Any]] = []
        try:
            while True:
                drained.append(outbound.get_nowait())
        except queue.Empty:
            pass

        for pkt in drained:
            await multicast(clients, pkt)

        await asyncio.sleep(0.02)


async def websocket_main(
    *,
    runtime,
    ws_host: str,
    ws_port: int,
    inbound_commands: queue.Queue,
    outbound_messages: queue.Queue,
    stop_event: threading.Event,
    log: LogFn,
) -> None:
    clients: set[Any] = set()
    runtime.ui.ws_running = True

    async def handler(ws: Any) -> None:
        clients.add(ws)
        with runtime.lock:
            runtime.ui.ws_clients = len(clients)
        await multicast(clients, {"type": "hello", "timestamp": int(time.time() * 1000)})
        try:
            async for raw_message in ws:
                try:
                    decoded = json.loads(raw_message)
                except json.JSONDecodeError:
                    continue
                if decoded.get("type") == "command":
                    inbound_commands.put(decoded)
        finally:
            clients.discard(ws)
            with runtime.lock:
                runtime.ui.ws_clients = len(clients)

    broadcaster_task = asyncio.create_task(
        broadcast_loop(runtime, outbound_messages, clients, stop_event)
    )

    try:
        async with websockets.serve(handler, ws_host, int(ws_port), ping_interval=20, ping_timeout=20):
            log("ok", f"WebSocket listening ws://{ws_host}:{ws_port}")
            while not stop_event.is_set():
                await asyncio.sleep(0.2)
    finally:
        broadcaster_task.cancel()
        try:
            await broadcaster_task
        except asyncio.CancelledError:
            pass
        runtime.ui.ws_running = False
        with runtime.lock:
            runtime.ui.ws_clients = 0
