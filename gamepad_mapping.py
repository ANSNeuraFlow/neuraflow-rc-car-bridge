"""Forza-style gamepad axis → protocol integer level mapping."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class AxisMapping:
    steer: int = 0
    lt: int = 4
    rt: int = 5


XBOX_FORZA = AxisMapping()


def apply_deadzone(value: float, deadzone: float = 0.12) -> float:
    if abs(value) < deadzone:
        return 0.0
    sign = 1.0 if value > 0 else -1.0
    scaled = (abs(value) - deadzone) / (1.0 - deadzone)
    return sign * min(max(scaled, 0.0), 1.0)


def normalize_trigger(axis_value: float, rest: float = -1.0) -> float:
    """Map trigger axis to 0.0 (released) … 1.0 (full press)."""

    if rest < 0:
        # Xbox-style: rests at -1, pressed toward +1
        return min(max((axis_value - rest) / (1.0 - rest), 0.0), 1.0)
    # Some controllers rest at 0, pressed toward +1
    return min(max(axis_value, 0.0), 1.0)


def forza_throttle_level(
    rt: float,
    lt: float,
    *,
    forward_max: int,
    above_max: int,
    max_forward_cap: int | None = None,
    deadzone: float = 0.12,
) -> int:
    """Net throttle from RT − LT (Forza-style)."""

    net = rt - lt
    if abs(net) < deadzone:
        return 0

    fwd_cap = forward_max
    if max_forward_cap is not None:
        fwd_cap = min(fwd_cap, max_forward_cap)

    if net > 0:
        return min(round(net * fwd_cap), fwd_cap)
    return max(round(net * above_max), -above_max)


def forza_steer_level(
    stick_x: float,
    *,
    steer_min: int,
    steer_max: int,
    deadzone: float = 0.12,
) -> int:
    adjusted = apply_deadzone(stick_x, deadzone)
    if adjusted == 0.0:
        return 0
    if adjusted > 0:
        return min(round(adjusted * steer_max), steer_max)
    return max(round(adjusted * abs(steer_min)), steer_min)


def is_input_active(
    stick_x: float,
    rt: float,
    lt: float,
    *,
    deadzone: float = 0.12,
) -> bool:
    return (
        abs(apply_deadzone(stick_x, deadzone)) > 0
        or rt > deadzone
        or lt > deadzone
    )


def detect_trigger_axes(axis_values: list[float]) -> tuple[int, int] | None:
    """Find a pair of trigger-like axes resting near -1 (axes 2–5)."""

    candidates: list[tuple[int, float]] = []
    for idx in range(2, min(len(axis_values), 6)):
        val = axis_values[idx]
        if val < -0.5:
            candidates.append((idx, val))

    if len(candidates) >= 2:
        candidates.sort(key=lambda item: item[0])
        return candidates[0][0], candidates[1][0]
    return None


def resolve_axis_mapping(num_axes: int, axis_values: list[float]) -> AxisMapping:
    mapping = XBOX_FORZA
    if num_axes > mapping.rt:
        return mapping
    detected = detect_trigger_axes(axis_values)
    if detected is None:
        return AxisMapping(steer=0, lt=2, rt=3 if num_axes > 3 else 2)
    return AxisMapping(steer=0, lt=detected[0], rt=detected[1])


def _run_self_tests() -> None:
    assert apply_deadzone(0.05) == 0.0
    assert apply_deadzone(0.5, deadzone=0.12) > 0

    assert normalize_trigger(-1.0) == 0.0
    assert normalize_trigger(1.0) == 1.0

    assert forza_throttle_level(1.0, 0.0, forward_max=66, above_max=65) == 66
    assert forza_throttle_level(0.0, 1.0, forward_max=66, above_max=65) == -65
    assert forza_throttle_level(0.5, 0.5, forward_max=66, above_max=65) == 0
    assert forza_throttle_level(1.0, 0.0, forward_max=66, above_max=65, max_forward_cap=10) == 10

    assert forza_steer_level(1.0, steer_min=-98, steer_max=143) == 143
    assert forza_steer_level(-1.0, steer_min=-98, steer_max=143) == -98
    assert forza_steer_level(0.05, steer_min=-98, steer_max=143) == 0

    assert is_input_active(0.0, 0.0, 0.0) is False
    assert is_input_active(0.0, 0.5, 0.0) is True

    print("gamepad_mapping self-tests ok")


if __name__ == "__main__":
    _run_self_tests()
