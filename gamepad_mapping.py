"""Forza-style gamepad axis → protocol integer level mapping."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class AxisCalib:
    minimum: int = -32768
    maximum: int = 32767
    flat: int = 0

    @property
    def center(self) -> float:
        return (self.minimum + self.maximum) / 2.0

    @property
    def half_range(self) -> float:
        span = self.maximum - self.minimum
        return span / 2.0 if span > 0 else 1.0


DEFAULT_STICK_CALIB = AxisCalib(minimum=-32768, maximum=32767, flat=128)
DEFAULT_TRIGGER_CALIB = AxisCalib(minimum=0, maximum=255, flat=0)


def apply_deadzone(value: float, deadzone: float = 0.12) -> float:
    if abs(value) < deadzone:
        return 0.0
    sign = 1.0 if value > 0 else -1.0
    scaled = (abs(value) - deadzone) / (1.0 - deadzone)
    return sign * min(max(scaled, 0.0), 1.0)


def normalize_stick_raw(raw: int, calib: AxisCalib = DEFAULT_STICK_CALIB) -> float:
    """Map evdev/XInput stick absolute value to -1..+1 using axis calibration."""

    center = calib.center
    half = calib.half_range
    if half <= 0:
        return 0.0
    if calib.flat and abs(raw - center) <= calib.flat:
        return 0.0
    return max(-1.0, min(1.0, (raw - center) / half))


def normalize_trigger_raw(raw: int, calib: AxisCalib = DEFAULT_TRIGGER_CALIB) -> float:
    """Map evdev/XInput trigger absolute value to 0..+1 (released → pressed)."""

    span = calib.maximum - calib.minimum
    if span <= 0:
        return 0.0
    if calib.flat and raw <= calib.minimum + calib.flat:
        return 0.0
    return max(0.0, min(1.0, (raw - calib.minimum) / span))


def smooth_value(current: float, target: float, alpha: float) -> float:
    """Exponential moving average toward target."""

    alpha = max(0.0, min(1.0, alpha))
    return alpha * target + (1.0 - alpha) * current


def should_send_steer_level(new_steer: int, last_steer: int | None, *, min_step: int) -> bool:
    """Reduce serial chatter unless returning to center or a large enough step."""

    if last_steer is None:
        return True
    if new_steer == 0 and last_steer != 0:
        return True
    if new_steer != 0 and last_steer == 0:
        return True
    return abs(new_steer - last_steer) >= max(1, min_step)


def normalize_trigger(axis_value: float, rest: float = -1.0) -> float:
    """Map trigger axis to 0.0 (released) … 1.0 (full press). Legacy float path."""

    if rest < 0:
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

    assert normalize_stick_raw(0, DEFAULT_STICK_CALIB) == 0.0
    assert abs(normalize_stick_raw(32767, DEFAULT_STICK_CALIB) - 1.0) < 0.01
    assert abs(normalize_stick_raw(-32768, DEFAULT_STICK_CALIB) + 1.0) < 0.01
    assert normalize_stick_raw(100, DEFAULT_STICK_CALIB) == 0.0  # within flat=128

    assert normalize_trigger_raw(0, DEFAULT_TRIGGER_CALIB) == 0.0
    assert normalize_trigger_raw(255, DEFAULT_TRIGGER_CALIB) == 1.0

    assert smooth_value(0.0, 1.0, 0.25) == 0.25
    assert smooth_value(0.25, 1.0, 0.25) == 0.4375

    assert should_send_steer_level(10, 10, min_step=2) is False
    assert should_send_steer_level(13, 10, min_step=2) is True
    assert should_send_steer_level(0, 10, min_step=2) is True

    assert normalize_trigger(-1.0) == 0.0
    assert normalize_trigger(1.0) == 1.0

    assert forza_throttle_level(1.0, 0.0, forward_max=66, above_max=65) == 66
    assert forza_steer_level(1.0, steer_min=-98, steer_max=143) == 143
    assert forza_steer_level(0.05, steer_min=-98, steer_max=143) == 0

    print("gamepad_mapping self-tests ok")


if __name__ == "__main__":
    _run_self_tests()
