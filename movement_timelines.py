"""Load and validate movement timeline definitions from YAML/JSON config."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Literal

StepKind = Literal[
    "wait",
    "set_controls",
    "neutral",
    "brake",
    "cycle_lights",
]

# Canonical gamepad binding IDs used in movements.yaml and the bindings index.
GAMEPAD_BINDING_ALIASES = {
    # D-pad
    "DPAD_UP": "DPAD_UP",
    "DPAD_DOWN": "DPAD_DOWN",
    "DPAD_LEFT": "DPAD_LEFT",
    "DPAD_RIGHT": "DPAD_RIGHT",
    "BTN_DPAD_UP": "DPAD_UP",
    "BTN_DPAD_DOWN": "DPAD_DOWN",
    "BTN_DPAD_LEFT": "DPAD_LEFT",
    "BTN_DPAD_RIGHT": "DPAD_RIGHT",
    "ABS_HAT0Y_-1": "DPAD_UP",
    "ABS_HAT0Y_1": "DPAD_DOWN",
    "ABS_HAT0X_-1": "DPAD_LEFT",
    "ABS_HAT0X_1": "DPAD_RIGHT",
    # Face buttons (Xbox labels + Linux evdev names)
    "A": "BTN_A",
    "B": "BTN_B",
    "X": "BTN_X",
    "Y": "BTN_Y",
    "BTN_A": "BTN_A",
    "BTN_B": "BTN_B",
    "BTN_X": "BTN_X",
    "BTN_Y": "BTN_Y",
    "BTN_SOUTH": "BTN_A",
    "BTN_EAST": "BTN_B",
    "BTN_WEST": "BTN_X",
    "BTN_NORTH": "BTN_Y",
    # Bumpers
    "LB": "BTN_TL",
    "RB": "BTN_TR",
    "BUMPER_LEFT": "BTN_TL",
    "BUMPER_RIGHT": "BTN_TR",
    "BTN_TL": "BTN_TL",
    "BTN_TR": "BTN_TR",
    "BTN_LEFT_SHOULDER": "BTN_TL",
    "BTN_RIGHT_SHOULDER": "BTN_TR",
}

# inputs/evdev Key event codes → canonical binding ID
EVENT_CODE_TO_BINDING = {
    "BTN_DPAD_UP": "DPAD_UP",
    "BTN_DPAD_DOWN": "DPAD_DOWN",
    "BTN_DPAD_LEFT": "DPAD_LEFT",
    "BTN_DPAD_RIGHT": "DPAD_RIGHT",
    "BTN_SOUTH": "BTN_A",
    "BTN_EAST": "BTN_B",
    "BTN_WEST": "BTN_X",
    "BTN_NORTH": "BTN_Y",
    "BTN_TL": "BTN_TL",
    "BTN_TR": "BTN_TR",
    "BTN_LEFT_SHOULDER": "BTN_TL",
    "BTN_RIGHT_SHOULDER": "BTN_TR",
}


@dataclass(frozen=True)
class MovementStep:
    kind: StepKind
    wait_ms: int = 0
    throttle_level: int | str | None = None
    steer_level: int | str | None = None
    brake_level: int = -1


@dataclass(frozen=True)
class MovementBindings:
    gui: bool = False
    keyboard: str = ""
    gamepad: str = ""


@dataclass(frozen=True)
class MovementDefinition:
    movement_id: str
    label: str
    steps: tuple[MovementStep, ...]
    bindings: MovementBindings


@dataclass
class MovementCatalog:
    movements: dict[str, MovementDefinition] = field(default_factory=dict)
    errors: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class BindingsIndex:
    keyboard: dict[str, str]
    gamepad: dict[str, str]
    gui: list[str]


def normalize_gamepad_binding(raw: str) -> str:
    key = str(raw).strip().upper()
    if key not in GAMEPAD_BINDING_ALIASES:
        supported = (
            "DPAD_UP/DOWN/LEFT/RIGHT, A/B/X/Y, LB/RB "
            "(or BTN_SOUTH/EAST/WEST/NORTH, BTN_TL/TR)"
        )
        raise ValueError(f"unsupported gamepad binding {raw!r}; use {supported}")
    return GAMEPAD_BINDING_ALIASES[key]


def event_code_to_binding(event_code: str) -> str | None:
    """Map a raw inputs Key event code to a canonical gamepad binding ID."""
    return EVENT_CODE_TO_BINDING.get(str(event_code).strip())


def resolve_level(value: Any, axis: Literal["throttle", "steer"], runtime) -> int:
    if isinstance(value, bool):
        raise ValueError(f"{axis} level cannot be boolean")
    if isinstance(value, int):
        return int(value)
    if isinstance(value, float) and value.is_integer():
        return int(value)

    alias = str(value).strip().lower()
    with runtime.lock:
        bounds = runtime.bounds
        max_fwd = bounds.throttle_forward_max
        max_fwd_cap = runtime.max_forward_level
        if max_fwd_cap is not None:
            max_fwd = min(max_fwd, int(max_fwd_cap))

    if axis == "steer":
        if alias in ("max_right", "right", "full_right"):
            return bounds.steer_max
        if alias in ("max_left", "left", "full_left"):
            return bounds.steer_min
        if alias in ("center", "neutral", "0"):
            return 0
        raise ValueError(f"unknown steer alias {value!r}")

    if alias in ("max_forward", "forward", "full_forward", "max"):
        return max_fwd
    if alias in ("max_reverse", "reverse", "full_reverse"):
        return -bounds.throttle_above_max
    if alias == "brake":
        return -1
    if alias in ("neutral", "center", "0"):
        return 0
    raise ValueError(f"unknown throttle alias {value!r}")


def _parse_step(raw: Any, movement_id: str, index: int) -> MovementStep:
    if isinstance(raw, str):
        name = raw.strip().lower()
        if name == "neutral":
            return MovementStep(kind="neutral")
        if name == "brake":
            return MovementStep(kind="brake")
        if name == "cycle_lights":
            return MovementStep(kind="cycle_lights")
        raise ValueError(f"unknown shorthand step {raw!r}")

    if not isinstance(raw, dict):
        raise ValueError(f"step must be a mapping or shorthand string, got {type(raw).__name__}")

    if len(raw) != 1:
        raise ValueError(f"step must have exactly one key, got {sorted(raw)}")

    key, value = next(iter(raw.items()))
    key = str(key).strip().lower()

    if key == "wait_ms":
        ms = int(value)
        if ms < 0:
            raise ValueError("wait_ms must be >= 0")
        return MovementStep(kind="wait", wait_ms=ms)

    if key == "steer":
        return MovementStep(kind="set_controls", steer_level=_raw_level(value))

    if key == "throttle":
        return MovementStep(kind="set_controls", throttle_level=_raw_level(value))

    if key == "set_controls":
        if not isinstance(value, dict):
            raise ValueError("set_controls step must be a mapping")
        throttle = value.get("throttle_level", value.get("throttle"))
        steer = value.get("steer_level", value.get("steer"))
        if throttle is None and steer is None:
            raise ValueError("set_controls requires throttle and/or steer")
        return MovementStep(
            kind="set_controls",
            throttle_level=_raw_level(throttle) if throttle is not None else None,
            steer_level=_raw_level(steer) if steer is not None else None,
        )

    if key == "neutral" and value:
        return MovementStep(kind="neutral")
    if key == "brake" and value:
        if isinstance(value, dict) and "throttle_level" in value:
            return MovementStep(kind="brake", brake_level=int(value["throttle_level"]))
        return MovementStep(kind="brake")
    if key == "cycle_lights" and value:
        return MovementStep(kind="cycle_lights")

    raise ValueError(f"unknown step key {key!r} in {movement_id}[{index}]")


def _raw_level(value: Any) -> int | str:
    if isinstance(value, int):
        return value
    if isinstance(value, float) and value.is_integer():
        return int(value)
    if isinstance(value, str):
        return value.strip()
    raise ValueError(f"level must be int or alias string, got {value!r}")


def _parse_bindings(raw: Any, movement_id: str) -> MovementBindings:
    if raw is None:
        return MovementBindings()
    if not isinstance(raw, dict):
        raise ValueError("bindings must be a mapping")

    gui = bool(raw.get("gui", False))
    keyboard = str(raw.get("keyboard", "")).strip()
    gamepad_raw = str(raw.get("gamepad", "")).strip()
    gamepad = normalize_gamepad_binding(gamepad_raw) if gamepad_raw else ""
    return MovementBindings(gui=gui, keyboard=keyboard, gamepad=gamepad)


def _parse_movement(movement_id: str, raw: Any) -> MovementDefinition:
    if not isinstance(raw, dict):
        raise ValueError("movement must be a mapping")

    label = str(raw.get("label", movement_id)).strip() or movement_id
    steps_raw = raw.get("steps")
    if not isinstance(steps_raw, list) or not steps_raw:
        raise ValueError("steps must be a non-empty list")

    steps = tuple(_parse_step(step, movement_id, i) for i, step in enumerate(steps_raw))
    bindings = _parse_bindings(raw.get("bindings"), movement_id)
    return MovementDefinition(
        movement_id=movement_id,
        label=label,
        steps=steps,
        bindings=bindings,
    )


def _load_raw_document(path: Path) -> Any:
    text = path.read_text(encoding="utf-8")
    suffix = path.suffix.lower()
    if suffix == ".json":
        return json.loads(text)
    if suffix in (".yaml", ".yml"):
        import yaml

        return yaml.safe_load(text)
    raise ValueError(f"unsupported movements config extension: {path.suffix}")


def load_movements(path: str | Path) -> MovementCatalog:
    catalog = MovementCatalog()
    config_path = Path(path)
    if not config_path.is_file():
        catalog.errors.append(f"movements config not found: {config_path}")
        return catalog

    try:
        document = _load_raw_document(config_path)
    except Exception as exc:
        catalog.errors.append(f"failed to load {config_path}: {exc}")
        return catalog

    if not isinstance(document, dict):
        catalog.errors.append("movements config root must be a mapping")
        return catalog

    movements_raw = document.get("movements")
    if movements_raw is None:
        return catalog
    if not isinstance(movements_raw, dict):
        catalog.errors.append("movements must be a mapping")
        return catalog

    for movement_id, raw in movements_raw.items():
        mid = str(movement_id).strip()
        if not mid:
            catalog.errors.append("movement id cannot be empty")
            continue
        try:
            catalog.movements[mid] = _parse_movement(mid, raw)
        except Exception as exc:
            catalog.errors.append(f"{mid}: {exc}")

    return catalog


def build_bindings_index(catalog: MovementCatalog) -> BindingsIndex:
    keyboard: dict[str, str] = {}
    gamepad: dict[str, str] = {}
    gui: list[str] = []

    for movement_id, movement in catalog.movements.items():
        bindings = movement.bindings
        if bindings.gui:
            gui.append(movement_id)
        if bindings.keyboard:
            if bindings.keyboard in keyboard:
                raise ValueError(
                    f"duplicate keyboard binding {bindings.keyboard!r} "
                    f"for {movement_id} and {keyboard[bindings.keyboard]}"
                )
            keyboard[bindings.keyboard] = movement_id
        if bindings.gamepad:
            if bindings.gamepad in gamepad:
                raise ValueError(
                    f"duplicate gamepad binding {bindings.gamepad!r} "
                    f"for {movement_id} and {gamepad[bindings.gamepad]}"
                )
            gamepad[bindings.gamepad] = movement_id

    return BindingsIndex(keyboard=keyboard, gamepad=gamepad, gui=gui)


def step_to_command(step: MovementStep, runtime) -> tuple[str, dict[str, Any]] | None:
    if step.kind == "wait":
        return None

    if step.kind == "neutral":
        return "neutral", {}

    if step.kind == "brake":
        params: dict[str, Any] = {}
        if step.brake_level != -1:
            params["throttle_level"] = step.brake_level
        return "brake", params

    if step.kind == "cycle_lights":
        return "cycle_lights", {}

    params = {}
    if step.throttle_level is not None:
        raw = step.throttle_level
        level = resolve_level(raw, "throttle", runtime) if isinstance(raw, str) else int(raw)
        params["throttle_level"] = level
    if step.steer_level is not None:
        raw = step.steer_level
        level = resolve_level(raw, "steer", runtime) if isinstance(raw, str) else int(raw)
        params["steer_level"] = level
    return "set_controls", params


def _run_self_tests() -> None:
    from tempfile import NamedTemporaryFile

    from state import SharedRuntime

    sample = {
        "movements": {
            "demo": {
                "label": "Demo",
                "steps": [
                    {"steer": "max_right"},
                    {"wait_ms": 50},
                    {"throttle": 1},
                    "neutral",
                ],
                "bindings": {
                    "gui": True,
                    "keyboard": "Key-1",
                    "gamepad": "DPAD_RIGHT",
                },
            }
        }
    }
    with NamedTemporaryFile("w", suffix=".json", delete=False, encoding="utf-8") as tmp:
        json.dump(sample, tmp)
        path = tmp.name

    catalog = load_movements(path)
    assert not catalog.errors, catalog.errors
    assert "demo" in catalog.movements
    movement = catalog.movements["demo"]
    assert movement.steps[0].kind == "set_controls"
    assert movement.steps[0].steer_level == "max_right"
    assert movement.steps[1].wait_ms == 50

    index = build_bindings_index(catalog)
    assert index.keyboard["Key-1"] == "demo"
    assert index.gamepad["DPAD_RIGHT"] == "demo"
    assert index.gui == ["demo"]

    runtime = SharedRuntime()
    cmd, params = step_to_command(movement.steps[0], runtime)
    assert cmd == "set_controls"
    assert params["steer_level"] == runtime.bounds.steer_max

    assert normalize_gamepad_binding("a") == "BTN_A"
    assert normalize_gamepad_binding("LB") == "BTN_TL"
    assert normalize_gamepad_binding("BTN_SOUTH") == "BTN_A"
    assert event_code_to_binding("BTN_EAST") == "BTN_B"
    assert event_code_to_binding("BTN_TR") == "BTN_TR"

    Path(path).unlink(missing_ok=True)
    print("movement_timelines self-tests ok")


if __name__ == "__main__":
    _run_self_tests()
