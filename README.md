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
| `GAMEPAD_ENABLED`             | `1`         | Set `0` to disable gamepad polling at startup                         |
| `GAMEPAD_DEADZONE`            | `0.12`      | Stick/trigger deadzone (0.0–1.0)                                      |
| `GAMEPAD_POLL_HZ`             | `40`        | Gamepad poll rate                                                     |
| `GAMEPAD_SEND_MIN_INTERVAL_S` | `0.05`      | Min interval between serial `set_controls` from gamepad (~20 Hz)      |
| `GAMEPAD_LIGHTS_BUTTON`       | `BTN_NORTH` | evdev key code for cycle-lights (Xbox **Y**)                          |
| `GAMEPAD_LIGHTS_DEBOUNCE_S`   | `0.25`      | Min seconds between gamepad lights commands                           |

Select a serial port in the GUI and click **Connect**. The bridge waits for the firmware `ready` event, reads `get_device_info` / `get_state`, then accepts commands.

## Gamepad controls (Forza-style)

Plug in an Xbox or similar controller (first device wins). Enable via the **Enable gamepad** checkbox in the GUI (on by default).

| Input                  | Action                                                 |
| ---------------------- | ------------------------------------------------------ |
| **RT (right trigger)** | Forward throttle (`throttle_level` `0…+max`)           |
| **LT (left trigger)**  | Brake / above-CP (`throttle_level` `0…-max`)           |
| **RT + LT**            | Net throttle `RT − LT` (accelerate, brake, or neutral) |
| **Left stick X**       | Proportional steering                                  |
| **Y**                  | `cycle_lights` (advance lights mode)                   |

While sticks or triggers are beyond the deadzone, **keyboard throttle/steer inputs are ignored** so gamepad and keys do not fight. Keyboard still works for **L** (lights) and when the controller is at neutral. Gamepad **Y** works while driving.

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

| Key       | Action                                                                |
| --------- | --------------------------------------------------------------------- |
| **Up**    | `throttle_level += 1`                                                 |
| **Down**  | `throttle_level -= 1` (full signed range; `0 → -1` enters brake zone) |
| **Left**  | `steer_level -= 1`                                                    |
| **Right** | `steer_level += 1`                                                    |
| **B**     | Brake (`throttle_level: -1`; steer unchanged)                         |
| **L**     | `cycle_lights` (advance local mode label)                             |
| **Space** | Neutral throttle and steer (`0`, `0`)                                 |

Disconnect or close the app sends neutral before closing the serial port.

## WebSocket protocol

**Client → bridge (command):**

```json
{ "type": "command", "command": "set_controls", "params": { "throttle_level": 3, "steer_level": -5 } }
{ "type": "command", "command": "cycle_lights", "params": {} }
{ "type": "command", "command": "neutral", "params": {} }
{ "type": "command", "command": "brake", "params": {} }
{ "type": "command", "command": "throttle_step", "params": { "delta": 1 } }
{ "type": "command", "command": "steer_step", "params": { "delta": -1 } }
```

`throttle_step` / `steer_step` are bridge-only helpers (apply delta, clamp to firmware bounds).

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

## Nuxt integration (future)

When a web plugin is added:

```
PUBLIC_RC_CAR_BRIDGE_URL=ws://127.0.0.1:8801
```

## Development

One-shot CLI (no GUI) remains in `neuraflow-rc-car-remote-firmware/test-scripts/rc_car.py` for scripting and CRC smoke tests.
