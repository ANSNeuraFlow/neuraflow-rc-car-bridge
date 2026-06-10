"""CRC16-CCITT serial JSON protocol helpers for neuraflow-rc-car-remote-firmware."""

from __future__ import annotations

import json
import time
from typing import Any, Callable

import serial

LogFn = Callable[[str, str], None]


def crc16_ccitt(data: str, poly: int = 0x1021, init: int = 0xFFFF) -> int:
    crc = init
    for ch in data.encode("utf-8"):
        crc ^= ch << 8
        for _ in range(8):
            if crc & 0x8000:
                crc = (crc << 1) ^ poly
            else:
                crc <<= 1
            crc &= 0xFFFF
    return crc


def validate_crc(payload: dict[str, Any]) -> bool:
    if "crc" not in payload:
        return False

    crc_received = payload.pop("crc")
    json_str = json.dumps(payload, separators=(",", ":"), sort_keys=True)
    crc_calculated = crc16_ccitt(json_str)
    payload["crc"] = crc_received
    return crc_received == crc_calculated


def command_crc_body(cmd: str, data: dict[str, Any]) -> str:
    payload = {"cmd": cmd, "data": data}
    canonical = json.dumps(payload, separators=(",", ":"), sort_keys=True)
    return canonical[:-1]


def build_command(cmd: str, data: dict[str, Any]) -> str:
    body = command_crc_body(cmd, data)
    crc = crc16_ccitt(body)
    return body + f',"crc":{crc}' + "}"


class SerialSession:
    """Per-connection serial line reader with CRC-validated command/response exchange."""

    def __init__(self) -> None:
        self._recv_buffer = ""

    def reset_buffer(self) -> None:
        self._recv_buffer = ""

    def read_lines(
        self,
        ser: serial.Serial,
        timeout_s: float = 0.5,
        *,
        accept_events: bool = True,
        accept_responses: bool = True,
        log: LogFn | None = None,
    ) -> list[dict[str, Any]]:
        deadline = time.time() + timeout_s
        messages: list[dict[str, Any]] = []

        while time.time() < deadline:
            chunk = ser.read(ser.in_waiting or 1)
            if not chunk:
                time.sleep(0.01)
                continue

            self._recv_buffer += chunk.decode(errors="replace")

            while "\n" in self._recv_buffer:
                line, self._recv_buffer = self._recv_buffer.split("\n", 1)
                line = line.strip()
                if not line:
                    continue

                try:
                    payload: dict[str, Any] = json.loads(line)
                except json.JSONDecodeError:
                    if log:
                        log("warn", f"JSON parse error: {line[:80]}")
                    continue

                if not validate_crc(payload):
                    if log:
                        log("warn", f"CRC mismatch: {line[:80]}")
                    continue

                if payload.get("event") and accept_events:
                    messages.append(payload)
                elif payload.get("status") and accept_responses:
                    messages.append(payload)
                elif accept_events or accept_responses:
                    messages.append(payload)

        return messages

    def wait_for_ready(
        self,
        ser: serial.Serial,
        timeout_s: float = 6.0,
        log: LogFn | None = None,
    ) -> dict[str, Any] | None:
        deadline = time.time() + timeout_s

        while time.time() < deadline:
            for event in self.read_lines(
                ser, timeout_s=0.3, accept_events=True, accept_responses=False, log=log
            ):
                if event.get("event") == "ready":
                    return event
            time.sleep(0.05)

        return None

    def send_command(
        self,
        ser: serial.Serial,
        cmd: str,
        data: dict[str, Any],
        timeout_s: float = 5.0,
        log: LogFn | None = None,
    ) -> dict[str, Any]:
        msg = build_command(cmd, data)
        ser.write((msg + "\n").encode())
        ser.flush()
        if log:
            log("info", f"TX {msg}")

        deadline = time.time() + timeout_s
        last_line: str | None = None

        while time.time() < deadline:
            chunk = ser.read(ser.in_waiting or 1)
            if not chunk:
                time.sleep(0.01)
                continue

            self._recv_buffer += chunk.decode(errors="replace")

            while "\n" in self._recv_buffer:
                line, self._recv_buffer = self._recv_buffer.split("\n", 1)
                line = line.strip()
                if not line:
                    continue

                last_line = line

                try:
                    payload: dict[str, Any] = json.loads(line)
                except json.JSONDecodeError:
                    continue

                if payload.get("event"):
                    continue

                if not validate_crc(payload):
                    continue

                if payload.get("status"):
                    if log:
                        log("info", f"RX {line}")
                    return payload

        hint = f" Last line: {last_line!r}" if last_line else " No lines received."
        raise TimeoutError(f"No valid response for command {cmd}.{hint}")
