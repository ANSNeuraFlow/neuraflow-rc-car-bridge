# NeuraFlow RC Car Bridge

Local Python bridge between the NeuraFlow web app (future) and the neuraflow-rc-car-remote-firmware ESP32 firmware. It speaks **JSON + CRC16 over USB serial** to the car and **JSON over WebSocket** to browser clients.

## Requirements

- Python 3.12+
- USB serial connection to ESP32 dev board (`/dev/ttyUSB*` / `/dev/ttyACM*` on Linux, `COM*` on Windows)

## Install

```bash
cd neuraflow-rc-car-bridge
python -m venv .venv
source .venv/bin/activate   # Windows: .venv\Scripts\activate
pip install -r requirements.txt
```

## Run

```bash
python main.py
# or
./run.sh
```

A desktop GUI opens (same visual language as `neuraflow-mavlink-bridge`). The WebSocket server listens on `ws://127.0.0.1:8801` by default.

## Configuration

Environment variables (optional):

| Variable                      | Default     | Description                                                           |
| ----------------------------- | ----------- | --------------------------------------------------------------------- |
| `SERIAL_PORT`                 | *(empty)*   | e.g. `/dev/ttyUSB0` or `COM5`; GUI picker overrides at runtime        |
| `SERIAL_BAUD`                 | `115200`    | UART baud rate                                                        |
| `WS_HOST`                     | `127.0.0.1` | WebSocket bind host                                                   |
| `WS_PORT`                     | `8801`      | WebSocket port (8801 avoids collision with mavlink bridge on 8800)    |
| `MAX_FORWARD_LEVEL`           | *(empty)*   | Cap positive `throttle_level` for bench safety (empty = firmware max) |
| `HARDWARE_DEADBAND_ENABLED`   | `1`         | Set `0` to disable RC receiver deadband remapping                     |
| `THROTTLE_FORWARD_MIN`        | `23`        | First forward protocol level that moves the car                       |
| `THROTTLE_REVERSE_MIN`        | `29`        | Magnitude of first reverse/brake-zone level that moves the car        |
| `STEER_LEFT_MIN`              | `30`        | Magnitude of first left steer level that turns the wheels             |
| `STEER_RIGHT_MIN`             | `30`        | Magnitude of first right steer level that turns the wheels            |
| `GAMEPAD_ENABLED`             | `1`         | Set `0` to disable gamepad polling at startup                         |
| `GAMEPAD_DEADZONE`            | `0.12`      | Stick/trigger deadzone (0.0–1.0)                                      |
| `GAMEPAD_POLL_HZ`             | `40`        | Gamepad poll rate                                                     |
| `GAMEPAD_SEND_MIN_INTERVAL_S` | `0.05`      | Min interval between serial `set_controls` from gamepad (~20 Hz)      |
| `GAMEPAD_STEER_SMOOTH_ALPHA`  | `0.35`      | Stick smoothing (0 = frozen, 1 = raw; higher = more responsive)     |
| `GAMEPAD_STEER_SEND_STEP`     | `2`         | Min steer level change before sending (reduces jitter)                |
| `GAMEPAD_LIGHTS_BUTTON`       | `BTN_NORTH` | evdev key code for cycle-lights (Xbox **Y**)                          |
| `GAMEPAD_LIGHTS_DEBOUNCE_S`   | `0.25`      | Min seconds between gamepad lights commands                           |
| `GAMEPAD_NEUTRAL_BUTTON`      | `BTN_EAST`  | evdev key code for center actuators / neutral (Xbox **B**)            |
| `GAMEPAD_NEUTRAL_DEBOUNCE_S`  | `0.25`      | Min seconds between gamepad neutral commands                          |
| `GAMEPAD_MACRO_DEBOUNCE_S`    | `0.25`      | Min seconds between gamepad D-pad movement triggers                   |
| `MOVEMENTS_CONFIG`            | `movements.yaml` (next to app) | YAML/JSON file defining movement timelines and bindings      |

Select a serial port in the GUI and click **Connect**. The bridge waits for the firmware `ready` event, reads `get_device_info` / `get_state`, then accepts commands.

### Hardware deadband vs gamepad deadzone

`GAMEPAD_DEADZONE` filters noisy stick/trigger input **before** integer level mapping (input-side). The `THROTTLE_*_MIN` and `STEER_*_MIN` variables compensate for the RC receiver’s physical deadband **after** mapping: low raw levels are expanded so the first movement happens at the configured protocol level. Tune with keyboard ↑/↓/←/→ while watching the THROTTLE/STEER stat cards, then set env vars without code changes. Set `HARDWARE_DEADBAND_ENABLED=0` to restore linear 1:1 level mapping.

## Gamepad controls (Forza-style)

Plug in an Xbox or similar controller (first device wins). Enable via the **Enable gamepad** checkbox in the GUI (on by default).

| Input                  | Action                                                 |
| ---------------------- | ------------------------------------------------------ |
| **RT (right trigger)** | Forward throttle (`throttle_level` `0…+max`)           |
| **LT (left trigger)**  | Brake / above-CP (`throttle_level` `0…-max`)           |
| **RT + LT**            | Net throttle `RT − LT` (accelerate, brake, or neutral) |
| **Left stick X**       | Proportional steering                                  |
| **Y**                  | `cycle_lights` (advance lights mode)                   |
| **B**                  | `neutral` (center throttle and steer, like **Space**)  |

While sticks or triggers are beyond the deadzone, **keyboard throttle/steer inputs are ignored** so gamepad and keys do not fight. Keyboard still works for **L** (lights) and when the controller is at neutral. Gamepad **Y** and **B** work while driving.

Linux + Windows supported via the [`inputs`](https://pypi.org/project/inputs/) library (evdev / XInput). macOS gamepad is not supported — use keyboard or WebSocket.

### Linux gamepad permissions

The bridge reads `/dev/input/event*` for gamepad events. Your user must be in the `input` group:

```bash
sudo usermod -aG input $USER
# log out and back in (or reboot)
```

Without this, the log shows a permission-denied error and the gamepad pill stays on **waiting**.

## Keyboard controls

Focus the bridge window, then:

| Key       | Action                                                                                      |
| --------- | ------------------------------------------------------------------------------------------- |
| **Up**    | Increase throttle (from neutral jumps to `THROTTLE_FORWARD_MIN`, default +23)               |
| **Down**  | Decrease throttle (from neutral jumps to `-THROTTLE_REVERSE_MIN`, default −29)              |
| **Left**  | Steer left (from center jumps to `-STEER_LEFT_MIN`, default −30)                            |
| **Right** | Steer right (from center jumps to `STEER_RIGHT_MIN`, default +30)                           |
| **B**     | Brake / reverse zone entry (raw `-1` remapped to `-THROTTLE_REVERSE_MIN`; steer unchanged)   |
| **L**     | `cycle_lights` (advance local mode label)                                                   |
| **Space** | Neutral throttle and steer (`0`, `0`)                                                       |

Disconnect or close the app sends neutral before closing the serial port.

## Movement timelines (macros)

Define reusable timed movement sequences in `movements.yaml` (see `movements.example.yaml`). Restart the bridge after editing steps or bindings.

**Example** — full right, brief throttle pulse, then coast:

```yaml
movements:
  turn_and_brief_throttle:
    label: "Turn & Brief Throttle"
    steps:
      - steer: max_right
      - wait_ms: 100
      - throttle: 1
      - wait_ms: 500
      - throttle: 0
    bindings:
      gui: true
      keyboard: "Key-1"
      gamepad: "DPAD_RIGHT"
```

**Step types**

| Step | Meaning |
|------|---------|
| `wait_ms: N` | Pause N milliseconds |
| `steer: X` | Set steer level only |
| `throttle: X` | Set throttle level only |
| `set_controls: {steer_level?, throttle_level?}` | Set one or both axes |
| `neutral` | Zero throttle and steer |
| `brake` | Brake / reverse zone entry |
| `cycle_lights` | Advance lights mode |

**Level values** — raw protocol integers (e.g. `throttle: 1`) or aliases:

- Steer: `max_right`, `max_left`, `center` / `neutral` / `0`
- Throttle: `max_forward`, `max_reverse`, `brake`, `neutral` / `0`

Aliases resolve using live firmware bounds from `get_device_info`.

**Bindings**

| Binding | Format |
|---------|--------|
| `gui: true` | Show a button in the MOVEMENTS panel |
| `keyboard` | Tk bind sequence, e.g. `Key-1`, `F5` |
| `gamepad` | `DPAD_UP/DOWN/LEFT/RIGHT`, face buttons `A`/`B`/`X`/`Y`, bumpers `LB`/`RB` (hat switch, digital D-pad, or evdev codes like `BTN_SOUTH`, `BTN_TL`) |

**Behavior**

- Only one macro runs at a time; triggering another replaces the current one.
- Keyboard throttle/steer or gamepad analog input **cancels** the active macro immediately (car stays at the last macro step until you drive manually).
- Macro triggers (GUI button, bound key, D-pad) work even while gamepad sticks/triggers are active.

## WebSocket protocol

**Client → bridge (command):**

```json
{ "type": "command", "command": "set_controls", "params": { "throttle_level": 3, "steer_level": -5 } }
{ "type": "command", "command": "cycle_lights", "params": {} }
{ "type": "command", "command": "neutral", "params": {} }
{ "type": "command", "command": "brake", "params": {} }
{ "type": "command", "command": "throttle_step", "params": { "delta": 1 } }
{ "type": "command", "command": "steer_step", "params": { "delta": -1 } }
{ "type": "command", "command": "run_movement", "params": { "movement_id": "turn_and_brief_throttle" } }
{ "type": "command", "command": "cancel_movement", "params": {} }
```

`throttle_step` / `steer_step` are bridge-only helpers (threshold-aware delta in protocol space; clamp to firmware bounds). `set_controls` accepts raw intent levels and applies hardware deadband remapping before serial output.

**Bridge → client (hello, on connect):**

```json
{
  "type": "hello",
  "movements": [{ "id": "circle_right", "label": "Circle Right" }],
  "timestamp": 1716220800000
}
```

`movements` lists GUI-bound macros from `movements.yaml` (`bindings.gui: true`).

**Bridge → client (movements, on reload):**

```json
{
  "type": "movements",
  "movements": [{ "id": "circle_right", "label": "Circle Right" }],
  "timestamp": 1716220800000
}
```

Sent when movements are reloaded (GUI ↻ button or startup) so web clients update macro buttons without reconnecting.

**Bridge → client (status):**

```json
{
  "type": "status",
  "serialConnected": true,
  "throttleLevel": 0,
  "steerLevel": 0,
  "lightsMode": "steady",
  "protocol": 2,
  "firmware": "1.1.0",
  "gamepadConnected": true,
  "activeMovement": "Circle Right",
  "movementRunning": false,
  "timestamp": 1716220800000
}
```

**Bridge → client (command ack):**

```json
{ "type": "command_ack", "command": "set_controls", "success": true, "timestamp": 1716220800000 }
```

## Windows notes

- Install the USB-UART driver for your ESP32 board (CP210x, CH340, etc.).
- Ports appear as `COM3`, `COM4`, … in the serial dropdown.
- Run from a terminal (`python main.py`) if the GUI does not start on first install.

## Firmware protocol

See [`neuraflow-rc-car-remote-firmware/docs/serial-protocol.md`](../neuraflow-rc-car-remote-firmware/docs/serial-protocol.md) for protocol command reference, level semantics, and host brake/reverse guidance.

## Nuxt integration (neuraflow-web)

The web app connects via `layers/remote/app/plugins/rc-car-bridge.client.ts`. Set in neuraflow-web `.env`:

```
PUBLIC_RC_CAR_BRIDGE_URL=ws://127.0.0.1:8801
```

Open `/remote/car` in neuraflow-web. The config screen shows bridge connection status; start a session once the WebSocket is connected. Connect the car serial port in this bridge GUI before driving.

## Development

One-shot CLI (no GUI) remains in `neuraflow-rc-car-remote-firmware/test-scripts/rc_car.py` for scripting and CRC smoke tests.
