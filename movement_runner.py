"""Background runner for movement timeline macros."""

from __future__ import annotations

import threading
from typing import Any, Callable

from movement_timelines import MovementCatalog, MovementDefinition, MovementStep, step_to_command

LogFn = Callable[[str, str], None]
EnqueueFn = Callable[[str, dict[str, Any]], None]


class MovementRunner:
    def __init__(
        self,
        *,
        runtime,
        enqueue_command: EnqueueFn,
        log: LogFn,
    ) -> None:
        self._runtime = runtime
        self._enqueue_command = enqueue_command
        self._log = log
        self._lock = threading.RLock()
        self._cancel = threading.Event()
        self._thread: threading.Thread | None = None
        self._catalog = MovementCatalog()
        self._generation = 0

    @property
    def catalog(self) -> MovementCatalog:
        with self._lock:
            return self._catalog

    def load_catalog(self, catalog: MovementCatalog) -> None:
        with self._lock:
            self._catalog = catalog

    def is_running(self) -> bool:
        with self._lock:
            return self._thread is not None and self._thread.is_alive()

    def active_movement_id(self) -> str:
        with self._runtime.lock:
            return self._runtime.ui.active_movement

    def trigger_movement(self, movement_id: str) -> bool:
        with self._lock:
            movement = self._catalog.movements.get(movement_id)
            if movement is None:
                self._log("warn", f"Unknown movement: {movement_id}")
                return False

            self._cancel_current_locked(reason="replaced")
            self._generation += 1
            generation = self._generation
            self._cancel = threading.Event()

            thread = threading.Thread(
                target=self._run_movement,
                args=(movement, generation),
                daemon=True,
                name=f"movement-{movement_id}",
            )
            self._thread = thread
            thread.start()
            return True

    def cancel_movement(self, *, reason: str = "cancelled") -> None:
        with self._lock:
            self._cancel_current_locked(reason=reason)

    def notify_manual_control(self, source: str) -> None:
        with self._lock:
            if not self.is_running_locked():
                return
            self._cancel_current_locked(reason=f"manual:{source}")

    def is_running_locked(self) -> bool:
        return self._thread is not None and self._thread.is_alive()

    def _cancel_current_locked(self, *, reason: str) -> None:
        thread = self._thread
        if thread is None or not thread.is_alive():
            self._clear_active_state()
            return

        self._cancel.set()
        with self._runtime.lock:
            active = self._runtime.ui.active_movement
        if active:
            self._log("info", f"Movement {active} {reason}")

    def _clear_active_state(self) -> None:
        with self._runtime.lock:
            self._runtime.ui.active_movement = ""
            self._runtime.ui.movement_running = False

    def _set_active_state(self, movement: MovementDefinition) -> None:
        with self._runtime.lock:
            self._runtime.ui.active_movement = movement.label
            self._runtime.ui.movement_running = True

    def _run_movement(self, movement: MovementDefinition, generation: int) -> None:
        cancel = self._cancel
        self._set_active_state(movement)
        self._log("info", f"Movement started: {movement.label}")

        try:
            for step in movement.steps:
                if cancel.is_set() or generation != self._generation:
                    return

                if step.kind == "wait":
                    if cancel.wait(step.wait_ms / 1000.0):
                        return
                    continue

                command = step_to_command(step, self._runtime)
                if command is None:
                    continue
                name, params = command
                if cancel.is_set() or generation != self._generation:
                    return
                self._enqueue_command(name, params)
        finally:
            with self._lock:
                if generation == self._generation:
                    self._clear_active_state()
                    if not cancel.is_set():
                        self._log("info", f"Movement finished: {movement.label}")


_runner: MovementRunner | None = None


def init_movement_runner(*, runtime, enqueue_command: EnqueueFn, log: LogFn) -> MovementRunner:
    global _runner
    _runner = MovementRunner(runtime=runtime, enqueue_command=enqueue_command, log=log)
    return _runner


def get_movement_runner() -> MovementRunner | None:
    return _runner


def trigger_movement(movement_id: str) -> bool:
    if _runner is None:
        return False
    return _runner.trigger_movement(movement_id)


def cancel_movement(*, reason: str = "cancelled") -> None:
    if _runner is not None:
        _runner.cancel_movement(reason=reason)


def notify_manual_control(source: str) -> None:
    if _runner is not None:
        _runner.notify_manual_control(source)


def handle_movement_command(command: str, params: dict[str, Any]) -> tuple[bool, str]:
    if command == "run_movement":
        movement_id = str(params.get("movement_id", "")).strip()
        if not movement_id:
            return False, command
        ok = trigger_movement(movement_id)
        return ok, command

    if command == "cancel_movement":
        cancel_movement(reason="requested")
        return True, command

    return False, command


def _run_self_tests() -> None:
    import time

    from movement_timelines import MovementBindings, MovementCatalog, MovementDefinition

    enqueued: list[tuple[str, dict[str, Any]]] = []
    logs: list[tuple[str, str]] = []

    class FakeRuntime:
        def __init__(self) -> None:
            from state import BridgeUiState, SharedRuntime

            self.lock = threading.RLock()
            self.ui = BridgeUiState()
            self.bounds = SharedRuntime().bounds
            self.max_forward_level = None

    runtime = FakeRuntime()

    runner = MovementRunner(
        runtime=runtime,
        enqueue_command=lambda cmd, params: enqueued.append((cmd, params)),
        log=lambda level, msg: logs.append((level, msg)),
    )
    runner.load_catalog(
        MovementCatalog(
            movements={
                "test": MovementDefinition(
                    movement_id="test",
                    label="Test",
                    steps=(
                        MovementStep(kind="set_controls", steer_level=10),
                        MovementStep(kind="wait", wait_ms=100),
                        MovementStep(kind="neutral"),
                    ),
                    bindings=MovementBindings(),
                )
            }
        )
    )

    assert runner.trigger_movement("test")
    time.sleep(0.25)
    assert ("set_controls", {"steer_level": 10}) in enqueued
    assert ("neutral", {}) in enqueued
    assert not runner.is_running()

    enqueued.clear()
    assert runner.trigger_movement("test")
    runner.notify_manual_control("keyboard")
    time.sleep(0.2)
    assert ("neutral", {}) not in enqueued

    print("movement_runner self-tests ok")


if __name__ == "__main__":
    _run_self_tests()
