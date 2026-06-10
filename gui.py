"""CustomTkinter GUI for NeuraFlow RC Car Bridge."""

from __future__ import annotations

import queue
import time

import customtkinter as ctk
from serial.tools import list_ports

from backend import enqueue_command, log_queue, request_connect, request_disconnect, runtime
from config import (
    ACCENT,
    ACCENT_DIM,
    BTN_RADIUS,
    BTN_SECONDARY_BORDER,
    BTN_SECONDARY_FG,
    BTN_SECONDARY_HOVER,
    CARD_BG,
    ERROR,
    FONT_FAMILY,
    LOG_INNER_BG,
    ON_SURFACE,
    ON_SURFACE_DIM,
    PANEL,
    SERIAL_BAUD,
    SERIAL_PORT,
    SUCCESS,
    SURFACE,
    WARNING,
    WS_HOST,
    WS_PORT,
)

_F = FONT_FAMILY


class StatusPill(ctk.CTkFrame):
    def __init__(self, master, label: str, **kwargs):
        super().__init__(
            master,
            fg_color=CARD_BG,
            corner_radius=20,
            border_width=1,
            border_color=BTN_SECONDARY_BORDER,
            **kwargs,
        )
        self._dot = ctk.CTkLabel(self, text="●", font=ctk.CTkFont(_F, 10), text_color=ON_SURFACE_DIM, width=14)
        self._dot.pack(side="left", padx=(10, 2), pady=6)
        ctk.CTkLabel(self, text=label, font=ctk.CTkFont(_F, 11), text_color=ON_SURFACE).pack(side="left")
        self._val = ctk.CTkLabel(self, text="—", font=ctk.CTkFont(_F, 11), text_color=ON_SURFACE_DIM)
        self._val.pack(side="left", padx=(4, 12))

    def set_ok(self, text: str = "ok") -> None:
        self._dot.configure(text_color=SUCCESS)
        self._val.configure(text=text, text_color=SUCCESS)

    def set_warn(self, text: str = "...") -> None:
        self._dot.configure(text_color=WARNING)
        self._val.configure(text=text, text_color=WARNING)

    def set_error(self, text: str = "error") -> None:
        self._dot.configure(text_color=ERROR)
        self._val.configure(text=text, text_color=ERROR)

    def set_idle(self, text: str = "—") -> None:
        self._dot.configure(text_color=ON_SURFACE_DIM)
        self._val.configure(text=text, text_color=ON_SURFACE_DIM)


class StatCard(ctk.CTkFrame):
    def __init__(self, master, label: str, unit: str = "", **kwargs):
        super().__init__(
            master,
            fg_color=CARD_BG,
            corner_radius=12,
            border_width=1,
            border_color=BTN_SECONDARY_BORDER,
            **kwargs,
        )
        self._var = ctk.StringVar(value="—")
        ctk.CTkLabel(self, text=label, font=ctk.CTkFont(_F, 10, "bold"), text_color=ON_SURFACE_DIM).pack(
            pady=(8, 1)
        )
        ctk.CTkLabel(self, textvariable=self._var, font=ctk.CTkFont(_F, 20, "bold"), text_color=ON_SURFACE).pack()
        if unit:
            ctk.CTkLabel(self, text=unit, font=ctk.CTkFont(_F, 9), text_color=ON_SURFACE_DIM).pack(pady=(0, 6))
        else:
            ctk.CTkLabel(self, text="", height=6).pack()

    def set(self, value: str | float | int | None) -> None:
        self._var.set("—" if value is None else str(value))


class LogPanel(ctk.CTkFrame):
    def __init__(self, master, **kwargs):
        super().__init__(
            master,
            fg_color=CARD_BG,
            corner_radius=12,
            border_width=1,
            border_color=BTN_SECONDARY_BORDER,
            **kwargs,
        )
        header = ctk.CTkFrame(self, fg_color="transparent")
        header.pack(fill="x", padx=14, pady=(12, 6))
        ctk.CTkLabel(header, text="SYSTEM LOG", font=ctk.CTkFont(_F, 11, "bold"), text_color=ON_SURFACE_DIM).pack(
            side="left"
        )
        ctk.CTkButton(
            header,
            text="Clear",
            width=68,
            height=28,
            font=ctk.CTkFont(_F, 10),
            fg_color=BTN_SECONDARY_FG,
            hover_color=BTN_SECONDARY_HOVER,
            text_color=ON_SURFACE,
            corner_radius=BTN_RADIUS,
            border_width=1,
            border_color=BTN_SECONDARY_BORDER,
            command=self._clear,
        ).pack(side="right")
        self._text = ctk.CTkTextbox(
            self,
            font=ctk.CTkFont(_F, 11),
            fg_color=LOG_INNER_BG,
            text_color=ON_SURFACE,
            corner_radius=8,
            wrap="word",
            activate_scrollbars=True,
        )
        self._text.pack(fill="both", expand=True, padx=10, pady=(0, 10))
        self._text.configure(state="disabled")
        tb = self._text._textbox
        tb.tag_configure("ok", foreground=SUCCESS)
        tb.tag_configure("warn", foreground=WARNING)
        tb.tag_configure("error", foreground=ERROR)
        tb.tag_configure("info", foreground=ON_SURFACE)
        tb.tag_configure("dim", foreground=ON_SURFACE_DIM)

    def add(self, level: str, message: str) -> None:
        self._text.configure(state="normal")
        tb = self._text._textbox
        if message.startswith("[") and "]" in message:
            end = message.index("]") + 1
            tb.insert("end", message[:end], "dim")
            tb.insert("end", message[end:] + "\n", level)
        else:
            tb.insert("end", message + "\n", level)
        tb.see("end")
        self._text.configure(state="disabled")

    def _clear(self) -> None:
        self._text.configure(state="normal")
        self._text.delete("1.0", "end")
        self._text.configure(state="disabled")


class App(ctk.CTk):
    def __init__(self) -> None:
        super().__init__()
        ctk.set_appearance_mode("dark")
        ctk.set_default_color_theme("dark-blue")
        self.title("NeuraFlow RC Car Bridge")
        self.geometry("1024x700")
        self.minsize(860, 580)
        self.configure(fg_color=SURFACE)
        self._connected = False
        self._build_ui()
        self._bind_keys()
        self.focus_set()
        self._tick()

        if SERIAL_PORT:
            self._port_combo.set(SERIAL_PORT)
            self.after(500, self._toggle_connect)

    def _build_ui(self) -> None:
        header = ctk.CTkFrame(self, fg_color=PANEL, corner_radius=0, height=58)
        header.pack(fill="x")
        header.pack_propagate(False)
        inner = ctk.CTkFrame(header, fg_color="transparent")
        inner.pack(fill="both", expand=True, padx=20)
        ctk.CTkLabel(inner, text="NeuraFlow", font=ctk.CTkFont(_F, 17, "bold"), text_color=ON_SURFACE).pack(
            side="left", pady=16
        )
        ctk.CTkLabel(inner, text=" RC Car Bridge", font=ctk.CTkFont(_F, 17), text_color=ON_SURFACE_DIM).pack(
            side="left", pady=16
        )
        self._mode_badge = ctk.CTkLabel(
            inner, text="DISCONNECTED", font=ctk.CTkFont(_F, 12, "bold"), text_color=ON_SURFACE_DIM
        )
        self._mode_badge.pack(side="right", pady=16)

        main = ctk.CTkFrame(self, fg_color="transparent")
        main.pack(fill="both", expand=True, padx=16, pady=12)
        left = ctk.CTkFrame(main, fg_color="transparent", width=300)
        left.pack(side="left", fill="y", padx=(0, 12))
        left.pack_propagate(False)
        right = ctk.CTkFrame(main, fg_color="transparent")
        right.pack(side="left", fill="both", expand=True)

        ctk.CTkLabel(left, text="STATUS", font=ctk.CTkFont(_F, 10, "bold"), text_color=ON_SURFACE_DIM).pack(
            anchor="w", pady=(4, 6)
        )
        self._serial_pill = StatusPill(left, "Serial / RC car")
        self._serial_pill.pack(fill="x", pady=(0, 4))
        self._ws_pill = StatusPill(left, "WebSocket")
        self._ws_pill.pack(fill="x", pady=(0, 4))
        self._client_pill = StatusPill(left, "Frontend client")
        self._client_pill.pack(fill="x", pady=(0, 4))
        self._gamepad_pill = StatusPill(left, "Gamepad")
        self._gamepad_pill.pack(fill="x", pady=(0, 14))

        ctk.CTkLabel(left, text="STATISTICS", font=ctk.CTkFont(_F, 10, "bold"), text_color=ON_SURFACE_DIM).pack(
            anchor="w", pady=(0, 6)
        )
        stats = ctk.CTkFrame(left, fg_color="transparent")
        stats.pack(fill="x", pady=(0, 14))
        self._stat_uptime = StatCard(stats, "UPTIME", "")
        self._stat_uptime.pack(fill="x", pady=(0, 5))
        self._stat_cmds = StatCard(stats, "COMMANDS", "")
        self._stat_cmds.pack(fill="x", pady=(0, 0))

        serial_cfg = ctk.CTkFrame(left, fg_color=CARD_BG, corner_radius=12, border_width=1, border_color=BTN_SECONDARY_BORDER)
        serial_cfg.pack(fill="x", pady=(0, 10))
        ctk.CTkLabel(
            serial_cfg, text="SERIAL", font=ctk.CTkFont(_F, 10, "bold"), text_color=ON_SURFACE_DIM
        ).pack(anchor="w", padx=14, pady=(10, 6))

        port_row = ctk.CTkFrame(serial_cfg, fg_color="transparent")
        port_row.pack(fill="x", padx=10, pady=2)
        self._port_combo = ctk.CTkComboBox(
            port_row,
            values=self._list_ports(),
            font=ctk.CTkFont(_F, 11),
            fg_color=LOG_INNER_BG,
            border_color=BTN_SECONDARY_BORDER,
            button_color=BTN_SECONDARY_FG,
            dropdown_fg_color=CARD_BG,
            height=28,
        )
        self._port_combo.pack(side="left", fill="x", expand=True)
        ctk.CTkButton(
            port_row,
            text="↻",
            width=36,
            height=28,
            font=ctk.CTkFont(_F, 12),
            fg_color=BTN_SECONDARY_FG,
            hover_color=BTN_SECONDARY_HOVER,
            text_color=ON_SURFACE,
            corner_radius=BTN_RADIUS,
            border_width=1,
            border_color=BTN_SECONDARY_BORDER,
            command=self._refresh_ports,
        ).pack(side="left", padx=(6, 0))

        self._cfg_baud = self._cfg_row(serial_cfg, "Baud", str(SERIAL_BAUD))
        self._cfg_max_fwd = self._cfg_row(serial_cfg, "Max fwd", "")

        self._connect_btn = ctk.CTkButton(
            serial_cfg,
            text="Connect",
            height=32,
            font=ctk.CTkFont(_F, 11, "bold"),
            fg_color=ACCENT,
            hover_color=ACCENT_DIM,
            text_color=ON_SURFACE,
            corner_radius=BTN_RADIUS,
            command=self._toggle_connect,
        )
        self._connect_btn.pack(fill="x", padx=10, pady=(6, 6))

        self._gamepad_enabled_var = ctk.BooleanVar(value=runtime.ui.gamepad_enabled)
        ctk.CTkCheckBox(
            serial_cfg,
            text="Enable gamepad",
            variable=self._gamepad_enabled_var,
            font=ctk.CTkFont(_F, 11),
            text_color=ON_SURFACE,
            fg_color=ACCENT,
            hover_color=ACCENT_DIM,
            border_color=BTN_SECONDARY_BORDER,
            command=self._on_gamepad_toggle,
        ).pack(anchor="w", padx=14, pady=(0, 10))

        cfg = ctk.CTkFrame(left, fg_color=CARD_BG, corner_radius=12, border_width=1, border_color=BTN_SECONDARY_BORDER)
        cfg.pack(fill="x")
        ctk.CTkLabel(cfg, text="CONFIG", font=ctk.CTkFont(_F, 10, "bold"), text_color=ON_SURFACE_DIM).pack(
            anchor="w", padx=14, pady=(10, 6)
        )
        self._cfg_host = self._cfg_row(cfg, "WS host", runtime.ws_host)
        self._cfg_port = self._cfg_row(cfg, "WS port", str(runtime.ws_port))
        ctk.CTkLabel(cfg, text="WS port applies after restart", font=ctk.CTkFont(_F, 9), text_color=ON_SURFACE_DIM).pack(
            pady=(2, 10)
        )

        controls = ctk.CTkFrame(right, fg_color=CARD_BG, corner_radius=12, border_width=1, border_color=BTN_SECONDARY_BORDER)
        controls.pack(fill="x", pady=(0, 10))
        ctk.CTkLabel(
            controls, text="CONTROLS", font=ctk.CTkFont(_F, 11, "bold"), text_color=ON_SURFACE_DIM
        ).pack(anchor="w", padx=14, pady=(12, 4))
        ctk.CTkLabel(
            controls,
            text="RT/LT throttle · LS steer · Y lights · ↑↓←→ keys · B brake · L lights · Space neutral",
            font=ctk.CTkFont(_F, 10),
            text_color=ON_SURFACE_DIM,
        ).pack(anchor="w", padx=14, pady=(0, 8))

        grid = ctk.CTkFrame(controls, fg_color="transparent")
        grid.pack(fill="x", padx=10, pady=(0, 12))
        self._throttle_card = StatCard(grid, "THROTTLE", "level")
        self._throttle_card.grid(row=0, column=0, padx=4, pady=4, sticky="nsew")
        self._steer_card = StatCard(grid, "STEER", "level")
        self._steer_card.grid(row=0, column=1, padx=4, pady=4, sticky="nsew")
        self._lights_card = StatCard(grid, "LIGHTS", "")
        self._lights_card.grid(row=0, column=2, padx=4, pady=4, sticky="nsew")
        grid.grid_columnconfigure(0, weight=1)
        grid.grid_columnconfigure(1, weight=1)
        grid.grid_columnconfigure(2, weight=1)

        self._log_panel = LogPanel(right)
        self._log_panel.pack(fill="both", expand=True)

        footer = ctk.CTkFrame(self, fg_color=PANEL, corner_radius=0, height=46)
        footer.pack(fill="x", side="bottom")
        footer.pack_propagate(False)
        fin = ctk.CTkFrame(footer, fg_color="transparent")
        fin.pack(fill="both", expand=True, padx=16)
        self._footer_lbl = ctk.CTkLabel(
            fin,
            text=f"ws://{WS_HOST}:{WS_PORT}",
            font=ctk.CTkFont(_F, 11),
            text_color=ON_SURFACE_DIM,
        )
        self._footer_lbl.pack(side="left", pady=12)

    def _cfg_row(self, parent, label: str, default: str) -> ctk.CTkEntry:
        row = ctk.CTkFrame(parent, fg_color="transparent")
        row.pack(fill="x", padx=10, pady=2)
        ctk.CTkLabel(
            row, text=label, width=72, font=ctk.CTkFont(_F, 11), text_color=ON_SURFACE_DIM, anchor="w"
        ).pack(side="left")
        entry = ctk.CTkEntry(
            row,
            font=ctk.CTkFont(_F, 11),
            fg_color=LOG_INNER_BG,
            border_color=BTN_SECONDARY_BORDER,
            text_color=ON_SURFACE,
            height=28,
        )
        entry.insert(0, default)
        entry.pack(side="left", fill="x", expand=True)
        return entry

    def _list_ports(self) -> list[str]:
        ports = [p.device for p in list_ports.comports()]
        return ports or ["(no ports found)"]

    def _refresh_ports(self) -> None:
        ports = self._list_ports()
        self._port_combo.configure(values=ports)
        if ports:
            self._port_combo.set(ports[0])

    def _parse_max_forward(self) -> int | None:
        raw = self._cfg_max_fwd.get().strip()
        if not raw:
            return None
        try:
            return max(0, int(raw))
        except ValueError:
            return None

    def _parse_baud(self) -> int:
        try:
            return int(self._cfg_baud.get().strip())
        except ValueError:
            return SERIAL_BAUD

    def _toggle_connect(self) -> None:
        if self._connected:
            request_disconnect()
            self._connected = False
            self._connect_btn.configure(text="Connect")
            self._log_panel.add("info", "Disconnect requested")
            return

        port = self._port_combo.get().strip()
        if not port or port == "(no ports found)":
            self._log_panel.add("warn", "Select a serial port first")
            return

        with runtime.lock:
            runtime.max_forward_level = self._parse_max_forward()
            runtime.ws_host = self._cfg_host.get().strip() or runtime.ws_host
            try:
                runtime.ws_port = int(self._cfg_port.get().strip())
            except ValueError:
                pass

        request_connect(port, self._parse_baud())
        self._connected = True
        self._connect_btn.configure(text="Disconnect")
        self._log_panel.add("info", f"Connecting to {port}...")

    def _bind_keys(self) -> None:
        self.bind("<Up>", lambda _e: self._key_step("throttle_step", 1))
        self.bind("<Down>", lambda _e: self._key_step("throttle_step", -1))
        self.bind("<Left>", lambda _e: self._key_step("steer_step", -1))
        self.bind("<Right>", lambda _e: self._key_step("steer_step", 1))
        self.bind("<Key-b>", lambda _e: self._key_command("brake"))
        self.bind("<Key-B>", lambda _e: self._key_command("brake"))
        self.bind("<Key-l>", lambda _e: self._key_command("cycle_lights"))
        self.bind("<Key-L>", lambda _e: self._key_command("cycle_lights"))
        self.bind("<space>", lambda _e: self._key_command("neutral"))

    def _on_gamepad_toggle(self) -> None:
        with runtime.lock:
            runtime.ui.gamepad_enabled = bool(self._gamepad_enabled_var.get())

    def _keyboard_allowed(self) -> bool:
        if not runtime.ui.serial_connected:
            return False
        return not runtime.ui.gamepad_active

    def _key_step(self, command: str, delta: int) -> None:
        if not self._keyboard_allowed():
            return
        enqueue_command(command, {"delta": delta})

    def _key_command(self, command: str) -> None:
        if not self._keyboard_allowed():
            return
        enqueue_command(command, {})

    def _format_level(self, level: int) -> str:
        if level > 0:
            return f"+{level}"
        return str(level)

    def _tick(self) -> None:
        while not log_queue.empty():
            try:
                level, msg = log_queue.get_nowait()
                self._log_panel.add(level, msg)
            except queue.Empty:
                break

        snap = runtime.gui_snapshot()
        ui = snap["ui"]

        if ui["serial_connected"]:
            self._serial_pill.set_ok(ui["serial_port"] or "connected")
            self._mode_badge.configure(text="CONNECTED", text_color=SUCCESS)
            self._connected = True
            self._connect_btn.configure(text="Disconnect")
        else:
            self._serial_pill.set_warn("disconnected")
            self._mode_badge.configure(text="DISCONNECTED", text_color=ON_SURFACE_DIM)
            if self._connected and not ui["serial_connected"]:
                self._connected = False
                self._connect_btn.configure(text="Connect")

        if ui["ws_running"]:
            self._ws_pill.set_ok(f":{runtime.ws_port}")
        else:
            self._ws_pill.set_warn("starting...")

        if ui["ws_clients"] > 0:
            self._client_pill.set_ok(f"{ui['ws_clients']} client(s)")
        else:
            self._client_pill.set_idle("waiting")

        if not ui["gamepad_enabled"]:
            self._gamepad_pill.set_idle("disabled")
        elif ui["gamepad_connected"]:
            label = ui["gamepad_name"] or "connected"
            if ui["gamepad_active"]:
                self._gamepad_pill.set_ok(label[:24])
            else:
                self._gamepad_pill.set_warn(label[:24])
        else:
            self._gamepad_pill.set_idle("waiting")

        elapsed = int(time.time() - runtime.uptime_start)
        m, s = divmod(elapsed, 60)
        h, m = divmod(m, 60)
        self._stat_uptime.set(f"{h}:{m:02d}:{s:02d}" if h else f"{m}:{s:02d}")
        self._stat_cmds.set(str(ui["commands_sent_total"]))

        self._throttle_card.set(self._format_level(snap["throttle_level"]))
        self._steer_card.set(self._format_level(snap["steer_level"]))
        self._lights_card.set(snap["lights_mode"])

        port = self._port_combo.get().strip()
        self._footer_lbl.configure(
            text=f"{port or '—'} @ {self._parse_baud()} · ws://{runtime.ws_host}:{runtime.ws_port}"
        )

        self.after(200, self._tick)

    def destroy(self) -> None:
        request_disconnect()
        super().destroy()
