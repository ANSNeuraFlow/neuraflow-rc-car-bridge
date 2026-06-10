"""Map raw intent levels to protocol levels, skipping RC receiver hardware deadband."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol


class DeviceBoundsLike(Protocol):
    throttle_forward_max: int
    throttle_above_max: int
    steer_min: int
    steer_max: int


@dataclass(frozen=True)
class HardwareDeadband:
    enabled: bool = True
    throttle_forward_min: int = 23
    throttle_reverse_min: int = 29
    steer_left_min: int = 30
    steer_right_min: int = 30


def _expand_positive(raw: int, min_eff: int, max_eff: int) -> int:
    if raw <= 0:
        return 0
    if raw >= max_eff:
        return max_eff
    if raw >= min_eff:
        return raw
    if max_eff <= 1 or max_eff <= min_eff:
        return max_eff
    t = (raw - 1) / (max_eff - 1)
    return round(min_eff + t * (max_eff - min_eff))


def _expand_negative(raw: int, min_eff: int, max_eff: int) -> int:
    if raw >= 0:
        return raw
    mag = abs(raw)
    if mag >= max_eff:
        return -max_eff
    if mag >= min_eff:
        return -mag
    if max_eff <= 1 or max_eff <= min_eff:
        return -max_eff
    t = (mag - 1) / (max_eff - 1)
    return -round(min_eff + t * (max_eff - min_eff))


def _forward_max(bounds: DeviceBoundsLike, max_forward_cap: int | None) -> int:
    max_fwd = bounds.throttle_forward_max
    if max_forward_cap is not None:
        max_fwd = min(max_fwd, int(max_forward_cap))
    return max_fwd


def calibrate_throttle_level(
    raw: int,
    bounds: DeviceBoundsLike,
    deadband: HardwareDeadband,
    *,
    max_forward_cap: int | None = None,
) -> int:
    level = int(raw)
    if not deadband.enabled:
        max_fwd = _forward_max(bounds, max_forward_cap)
        return max(-bounds.throttle_above_max, min(max_fwd, level))

    if level == 0:
        return 0

    max_fwd = _forward_max(bounds, max_forward_cap)
    max_rev = bounds.throttle_above_max

    if level > 0:
        min_eff = min(deadband.throttle_forward_min, max_fwd)
        return min(_expand_positive(level, min_eff, max_fwd), max_fwd)

    return max(_expand_negative(level, deadband.throttle_reverse_min, max_rev), -max_rev)


def calibrate_steer_level(
    raw: int,
    bounds: DeviceBoundsLike,
    deadband: HardwareDeadband,
) -> int:
    level = int(raw)
    if not deadband.enabled:
        return max(bounds.steer_min, min(bounds.steer_max, level))

    if level == 0:
        return 0

    if level > 0:
        max_eff = bounds.steer_max
        min_eff = min(deadband.steer_right_min, max_eff)
        return min(_expand_positive(level, min_eff, max_eff), max_eff)

    max_eff = abs(bounds.steer_min)
    min_eff = min(deadband.steer_left_min, max_eff)
    return max(_expand_negative(level, min_eff, max_eff), bounds.steer_min)


def step_throttle_level(
    current: int,
    delta: int,
    bounds: DeviceBoundsLike,
    deadband: HardwareDeadband,
    *,
    max_forward_cap: int | None = None,
) -> int:
    if delta == 0:
        return current

    max_fwd = _forward_max(bounds, max_forward_cap)
    max_rev = bounds.throttle_above_max

    if not deadband.enabled:
        return max(-max_rev, min(max_fwd, current + delta))

    fwd_min = min(deadband.throttle_forward_min, max_fwd)
    rev_min = min(deadband.throttle_reverse_min, max_rev)

    if delta > 0:
        if current == 0:
            return fwd_min
        if current < 0:
            next_level = current + delta
            if next_level > -rev_min:
                return 0
            return max(next_level, -max_rev)
        return min(current + delta, max_fwd)

    if current > 0:
        next_level = current + delta
        if next_level < fwd_min:
            return 0
        return next_level

    if current == 0:
        return -rev_min

    return max(current + delta, -max_rev)


def step_steer_level(
    current: int,
    delta: int,
    bounds: DeviceBoundsLike,
    deadband: HardwareDeadband,
) -> int:
    if delta == 0:
        return current

    if not deadband.enabled:
        return max(bounds.steer_min, min(bounds.steer_max, current + delta))

    left_min = min(deadband.steer_left_min, abs(bounds.steer_min))
    right_min = min(deadband.steer_right_min, bounds.steer_max)

    if delta > 0:
        if current == 0:
            return right_min
        if current < 0:
            next_level = current + delta
            if next_level > -left_min:
                return 0
            return max(next_level, bounds.steer_min)
        return min(current + delta, bounds.steer_max)

    if current > 0:
        next_level = current + delta
        if next_level < right_min:
            return 0
        return next_level

    if current == 0:
        return -left_min

    return max(current + delta, bounds.steer_min)


def _run_self_tests() -> None:
    @dataclass
    class Bounds:
        throttle_forward_max: int = 66
        throttle_above_max: int = 65
        steer_min: int = -98
        steer_max: int = 143

    bounds = Bounds()
    db = HardwareDeadband()

    assert calibrate_throttle_level(0, bounds, db) == 0
    assert calibrate_throttle_level(1, bounds, db) == 23
    assert calibrate_throttle_level(66, bounds, db) == 66
    assert calibrate_throttle_level(24, bounds, db) == 24
    assert calibrate_throttle_level(-1, bounds, db) == -29
    assert calibrate_throttle_level(-65, bounds, db) == -65
    assert calibrate_throttle_level(-30, bounds, db) == -30

    assert calibrate_steer_level(0, bounds, db) == 0
    assert calibrate_steer_level(1, bounds, db) == 30
    assert calibrate_steer_level(143, bounds, db) == 143
    assert calibrate_steer_level(31, bounds, db) == 31
    assert calibrate_steer_level(-1, bounds, db) == -30
    assert calibrate_steer_level(-98, bounds, db) == -98

    disabled = HardwareDeadband(enabled=False)
    assert calibrate_throttle_level(5, bounds, disabled) == 5
    assert calibrate_steer_level(-5, bounds, disabled) == -5

    assert step_throttle_level(0, 1, bounds, db) == 23
    assert step_throttle_level(23, 1, bounds, db) == 24
    assert step_throttle_level(23, -1, bounds, db) == 0
    assert step_throttle_level(0, -1, bounds, db) == -29
    assert step_throttle_level(-29, -1, bounds, db) == -30
    assert step_throttle_level(-29, 1, bounds, db) == 0

    assert step_steer_level(0, 1, bounds, db) == 30
    assert step_steer_level(30, 1, bounds, db) == 31
    assert step_steer_level(30, -1, bounds, db) == 0
    assert step_steer_level(0, -1, bounds, db) == -30

    capped = calibrate_throttle_level(66, bounds, db, max_forward_cap=40)
    assert capped == 40

    print("level_calibration self-tests ok")


if __name__ == "__main__":
    _run_self_tests()
