"""Forza-style gamepad axis → protocol integer level mapping."""

from __future__ import annotations


def apply_deadzone(value: float, deadzone: float = 0.12) -> float:
    if abs(value) < deadzone:
        return 0.0
    sign = 1.0 if value > 0 else -1.0
    scaled = (abs(value) - deadzone) / (1.0 - deadzone)
    return sign * min(max(scaled, 0.0), 1.0)


def normalize_stick_abs(state: int) -> float:
    """Map evdev/XInput stick absolute value to -1..+1."""

    if -32768 <= state <= 32767 and abs(state) > 255:
        return max(-1.0, min(1.0, state / 32768.0))
    return max(-1.0, min(1.0, (state - 128) / 128.0))


def normalize_trigger_abs(state: int) -> float:
    """Map evdev/XInput trigger absolute value to 0..+1 (released → pressed)."""

    if abs(state) > 255:
        return min(max(state / 32767.0, 0.0), 1.0)
    return min(max(state / 255.0, 0.0), 1.0)


def normalize_trigger(axis_value: float, rest: float = -1.0) -> float:
    """Map trigger axis to 0.0 (released) … 1.0 (full press)."""

    if rest < 0:
        # Xbox-style SDL: rests at -1, pressed toward +1
        return min(max((axis_value - rest) / (1.0 - rest), 0.0), 1.0)
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


def _run_self_tests() -> None:
    assert apply_deadzone(0.05) == 0.0
    assert apply_deadzone(0.5, deadzone=0.12) > 0

    assert normalize_stick_abs(128) == 0.0
    assert abs(normalize_stick_abs(32767) - 1.0) < 0.01
    assert abs(normalize_stick_abs(-32768) + 1.0) < 0.01
    assert normalize_stick_abs(0) == -1.0
    assert normalize_stick_abs(255) > 0.99

    assert normalize_trigger_abs(0) == 0.0
    assert normalize_trigger_abs(255) == 1.0
    assert abs(normalize_trigger_abs(32767) - 1.0) < 0.01

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
