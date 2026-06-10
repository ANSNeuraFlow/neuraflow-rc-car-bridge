"""Thread-safe shared runtime state between serial worker, GUI, and WebSocket server."""

from __future__ import annotations

import threading
import time
from dataclasses import dataclass, field
from typing import Any

from config import GAMEPAD_ENABLED_DEFAULT


@dataclass
class DeviceBounds:
    throttle_forward_max: int = 66
    throttle_above_max: int = 65
    steer_min: int = -98
    steer_max: int = 143


@dataclass
class BridgeUiState:
    serial_connected: bool = False
    serial_port: str = ""
    ws_running: bool = False
    ws_clients: int = 0
    firmware: str = "—"
    protocol: int = 0
    commands_sent_total: int = 0
    gamepad_connected: bool = False
    gamepad_name: str = ""
    gamepad_active: bool = False
    gamepad_enabled: bool = True


@dataclass
class SharedRuntime:
    lock: threading.RLock = field(default_factory=threading.RLock)
    serial_port: str = ""
    serial_baud: int = 115200
    ws_host: str = ""
    ws_port: int = 8801
    max_forward_level: int | None = None
    throttle_level: int = 0
    steer_level: int = 0
    lights_mode: str = "steady"
    bounds: DeviceBounds = field(default_factory=DeviceBounds)
    ui: BridgeUiState = field(default_factory=lambda: BridgeUiState(gamepad_enabled=GAMEPAD_ENABLED_DEFAULT))
    uptime_start: float = field(default_factory=time.time)
    connect_requested: bool = False
    disconnect_requested: bool = False

    def gui_snapshot(self) -> dict[str, Any]:
        with self.lock:
            return {
                "serial_port": self.serial_port,
                "serial_baud": self.serial_baud,
                "ws_host": self.ws_host,
                "ws_port": self.ws_port,
                "max_forward_level": self.max_forward_level,
                "throttle_level": self.throttle_level,
                "steer_level": self.steer_level,
                "lights_mode": self.lights_mode,
                "bounds": {
                    "throttle_forward_max": self.bounds.throttle_forward_max,
                    "throttle_above_max": self.bounds.throttle_above_max,
                    "steer_min": self.bounds.steer_min,
                    "steer_max": self.bounds.steer_max,
                },
                "ui": {
                    "serial_connected": self.ui.serial_connected,
                    "serial_port": self.ui.serial_port,
                    "ws_running": self.ui.ws_running,
                    "ws_clients": self.ui.ws_clients,
                    "firmware": self.ui.firmware,
                    "protocol": self.ui.protocol,
                    "commands_sent_total": self.ui.commands_sent_total,
                    "gamepad_connected": self.ui.gamepad_connected,
                    "gamepad_name": self.ui.gamepad_name,
                    "gamepad_active": self.ui.gamepad_active,
                    "gamepad_enabled": self.ui.gamepad_enabled,
                },
            }

    def status_snapshot(self) -> dict[str, Any]:
        with self.lock:
            return {
                "serialConnected": bool(self.ui.serial_connected),
                "throttleLevel": int(self.throttle_level),
                "steerLevel": int(self.steer_level),
                "lightsMode": str(self.lights_mode),
                "protocol": int(self.ui.protocol),
                "firmware": str(self.ui.firmware),
                "gamepadConnected": bool(self.ui.gamepad_connected),
            }
