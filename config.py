"""Branding, layout tokens, and default bridge configuration."""

from __future__ import annotations

import os

SERIAL_PORT = os.environ.get("SERIAL_PORT", "").strip()
SERIAL_BAUD = int(os.environ.get("SERIAL_BAUD", "115200"))
WS_HOST = os.environ.get("WS_HOST", "127.0.0.1")
WS_PORT = int(os.environ.get("WS_PORT", "8801"))

_max_forward_raw = os.environ.get("MAX_FORWARD_LEVEL", "").strip()
MAX_FORWARD_LEVEL: int | None = int(_max_forward_raw) if _max_forward_raw else None

STATUS_BROADCAST_HZ = 5.0
HEARTBEAT_INTERVAL_S = 30.0

GAMEPAD_ENABLED_DEFAULT = os.environ.get("GAMEPAD_ENABLED", "1").strip().lower() not in (
    "0",
    "false",
    "no",
)
GAMEPAD_POLL_HZ = float(os.environ.get("GAMEPAD_POLL_HZ", "40"))
GAMEPAD_DEADZONE = float(os.environ.get("GAMEPAD_DEADZONE", "0.12"))
GAMEPAD_SEND_MIN_INTERVAL_S = float(os.environ.get("GAMEPAD_SEND_MIN_INTERVAL_S", "0.05"))
GAMEPAD_STEER_SMOOTH_ALPHA = float(os.environ.get("GAMEPAD_STEER_SMOOTH_ALPHA", "0.35"))
GAMEPAD_STEER_SEND_STEP = int(os.environ.get("GAMEPAD_STEER_SEND_STEP", "2"))
GAMEPAD_LIGHTS_BUTTON = os.environ.get("GAMEPAD_LIGHTS_BUTTON", "BTN_NORTH").strip()
GAMEPAD_LIGHTS_DEBOUNCE_S = float(os.environ.get("GAMEPAD_LIGHTS_DEBOUNCE_S", "0.25"))

LIGHTS_MODES = ("off", "steady", "slow_blink", "fast_blink")

# Visual design (neuraflow-local-bridge / mavlink-bridge)

SURFACE = "#0b0d11"
SURFACE_CONTAINER = "#14181d"
SURFACE_INVERTED = "#e7e7e7"
ON_SURFACE = "#ffffff"
ON_SURFACE_DIM = "#b3b3b3"
ON_SURFACE_INVERTED = "#000000"
ACCENT = "#3b82f6"
ACCENT_DIM = "#234e94"
SUCCESS = "#84cc16"
WARNING = "#ff6a00"
ERROR = "#dc2626"
BORDER_SUBTLE = "#2a3138"

BG = SURFACE
PANEL = SURFACE
CARD_BG = SURFACE_CONTAINER
TEXT = ON_SURFACE
TEXT_DIM = ON_SURFACE_DIM
BORDER = BORDER_SUBTLE

BTN_RADIUS = 4
BTN_SECONDARY_FG = SURFACE_CONTAINER
BTN_SECONDARY_HOVER = "#181d24"
BTN_INVERSE_FG = SURFACE_INVERTED
BTN_INVERSE_HOVER = "#d9d9d9"
BTN_SECONDARY_BORDER = BORDER_SUBTLE

FONT_FAMILY = "Roboto"
LOG_INNER_BG = "#080a0f"
