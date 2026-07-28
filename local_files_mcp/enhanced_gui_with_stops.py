from __future__ import annotations

import json
import tkinter as tk
from tkinter import messagebox, simpledialog, ttk
from tkinter.scrolledtext import ScrolledText

from .config import load_config, save_config
from .enhanced_gui import APP_TITLE
from .enhanced_gui_plus import EnhancedGUIPlus
from .screen import screen_get_latest_frame, screen_list_windows

SCREEN_PHRASE = "ENABLE SCREEN TOOLS"


class EnhancedGUIWithStops(EnhancedGUIPlus):
    """Extension layer for dashboard stop controls and screen-tool settings."""

    def _build_vars(self) -> None:
        super()._build_vars()
        screen = self.cfg.setdefault("integrations", {}).setdefault("screen", {})
        self.screen_enabled_var = tk.BooleanVar(value=bool(screen.get("enabled", False)))
        self.screen_privacy_var = tk.BooleanVar(value=bool(screen.get("privacy_acknowledged", False)))
        self.screen_full_var = tk.BooleanVar(value=bool(screen.get("allow_full_screen", False)))
        self.screen_active_var = tk.BooleanVar(value=bool(screen.get("allow_active_window", True)))
        self.screen_window_var = tk.BooleanVar(value=bool(screen.get("allow_window_capture", True)))
        self.screen_save_var = tk.BooleanVar(value=bool(screen.get("save_captures", True)))
        self.screen_latest_only_var = tk.BooleanVar(value=bool(screen.get("retention_latest_only", True)))
        self.screen_max_width_var = tk.StringVar(value=str(screen.get("max_width", 1920)))
        self.screen_jpeg_quality_var = tk.StringVar(value=str(screen.get("jpeg_quality", 85)))

    def _build_ui(self) -> None:
        super()._build_ui()
        self._add_dashboard_stop_actions()
        self._add_screen_settings_tab()

    def _sync_vars(self) -> None:
        super()._sync_vars()
        screen = self.cfg.setdefault("integrations", {}).setdefault("screen", {})
        if hasattr(self, "screen_enabled_var"):
            self.screen_enabled_var.set(bool(screen.get("enabled", False)))
            self.screen_privacy_var.set(bool(screen.get("privacy_acknowledged", False)))
            self.screen_full_var.set(bool(screen.get("allow_full_screen", False)))
            self.screen_active_var.set(bool(screen.get("allow_active_window", True)))
            self.screen_window_var.set(bool(screen.get("allow_window_capture", True)))
            self.screen_save_var.set(bool(screen.get("save_captures", True)))
            self.screen_latest_only_var.set(bool(screen.get("retention_latest_only", True)))
            self.screen_max_width_var.set(str(screen.get("max_width", 1920)))
            self.screen_jpeg_quality_var.set(str(screen.get("jpeg_quality", 85)))

    def _find_common_actions_frame(self) -> ttk.LabelFrame | None:
        if not hasattr(self, "tab_dash"):
            return None
        for child in self.tab_dash.winfo_children():
            if isinstance(child, ttk.LabelFrame):
                try:
                    if str(child.cget("text")) == "Common actions":
                        return child
                except Exception:
                    continue
        return None

    def _next_grid_row(self, frame: ttk.LabelFrame) -> int:
        rows: list[int] = []
        for child in frame.winfo_children():
            try:
                info = child.grid_info()
                if "row" in info:
                    rows.append(int(info["row"]))
            except Exception:
                continue
        return (max(rows) + 1) if rows else 0

    def _existing_button_labels(self, frame: ttk.LabelFrame) -> set[str]:
        labels: set[str] = set()
        for child in frame.winfo_children():
            if isinstance(child, ttk.Button):
                try:
                    labels.add(str(child.cget("text")))
                except Exception:
                    pass
        return labels

    def _add_dashboard_stop_actions(self) -> None:
        frame = self._find_common_actions_frame()
        if frame is None:
            return

        existing = self._existing_button_labels(frame)
        row = self._next_grid_row(frame)

        if "Stop Server" not in existing:
            ttk.Button(frame, text="Stop Server", command=self.stop_server).grid(
                row=row,
                column=0,
                sticky="ew",
                padx=10,
                pady=5,
            )
            row += 1

        if "Stop Tunnel" not in existing:
            ttk.Button(frame, text="Stop Tunnel", command=self.stop_ngrok_tunnel).grid(
                row=row,
                column=0,
                sticky="ew",
                padx=10,
                pady=5,
            )

    def _notebook(self) -> ttk.Notebook | None:
        for child in self.winfo_children():
            if isinstance(child, ttk.Notebook):
                return child
        return None

    def _add_screen_settings_tab(self) -> None:
        notebook = self._notebook()
        if notebook is None:
            return

        self.tab_screen = ttk.Frame(notebook)
        self.tab_screen.columnconfigure(0, weight=1)
        self.tab_screen.rowconfigure(3, weight=1)
        notebook.add(self.tab_screen, text="Screen Tools")

        intro = ttk.LabelFrame(self.tab_screen, text="Screen privacy gate")
        intro.grid(row=0, column=0, sticky="ew", padx=12, pady=12)
        intro.columnconfigure(0, weight=1)
        ttk.Label(
            intro,
            text=(
                "Screen tools let ChatGPT list visible windows and capture one screenshot at a time. "
                "They are disabled by default and require an explicit privacy acknowledgement. "
                "No continuous streaming is enabled. Full-screen capture is separately gated."
            ),
            wraplength=1050,
            justify="left",
        ).grid(row=0, column=0, sticky="w", padx=12, pady=10)

        controls = ttk.LabelFrame(self.tab_screen, text="Enablement")
        controls.grid(row=1, column=0, sticky="ew", padx=12, pady=8)
        controls.columnconfigure(1, weight=1)
        checks = [
            ("Enable screen tools", self.screen_enabled_var),
            ("I acknowledge screenshots/window titles may contain sensitive information", self.screen_privacy_var),
            ("Allow active-window capture", self.screen_active_var),
            ("Allow specific-window capture", self.screen_window_var),
            ("Allow full-screen capture", self.screen_full_var),
            ("Save captures locally", self.screen_save_var),
            ("Keep only latest capture", self.screen_latest_only_var),
        ]
        for row, (label, var) in enumerate(checks):
            ttk.Checkbutton(controls, text=label, variable=var).grid(row=row, column=0, sticky="w", padx=12, pady=4)

        ttk.Label(controls, text="Max image width").grid(row=0, column=1, sticky="w", padx=12, pady=4)
        ttk.Entry(controls, textvariable=self.screen_max_width_var, width=12).grid(row=0, column=2, sticky="w", padx=12, pady=4)
        ttk.Label(controls, text="JPEG quality").grid(row=1, column=1, sticky="w", padx=12, pady=4)
        ttk.Entry(controls, textvariable=self.screen_jpeg_quality_var, width=12).grid(row=1, column=2, sticky="w", padx=12, pady=4)

        actions = ttk.LabelFrame(self.tab_screen, text="Actions")
        actions.grid(row=2, column=0, sticky="ew", padx=12, pady=8)
        buttons = [
            ("Save Screen Settings", self.save_screen_settings),
            ("Disable Screen Tools", self.disable_screen_tools),
            ("Test List Windows", self.test_screen_list_windows),
            ("Show Latest Capture Metadata", self.show_latest_screen_capture),
            ("Refresh Status", self.refresh_screen_status),
        ]
        for col, (label, cmd) in enumerate(buttons):
            ttk.Button(actions, text=label, command=cmd).grid(row=0, column=col, sticky="ew", padx=6, pady=8)

        status = ttk.LabelFrame(self.tab_screen, text="Status / diagnostics")
        status.grid(row=3, column=0, sticky="nsew", padx=12, pady=8)
        status.columnconfigure(0, weight=1)
        status.rowconfigure(0, weight=1)
        self.screen_status_text = ScrolledText(status, wrap="word", height=14)
        self.screen_status_text.grid(row=0, column=0, sticky="nsew", padx=8, pady=8)
        self.refresh_screen_status()

    def _write_screen_status(self, value: str | dict | list) -> None:
        if not hasattr(self, "screen_status_text"):
            return
        rendered = json.dumps(value, indent=2, sort_keys=True) if isinstance(value, (dict, list)) else str(value)
        self.screen_status_text.insert("end", rendered + "\n\n")
        self.screen_status_text.see("end")

    def _screen_config_from_vars(self) -> dict[str, object]:
        return {
            "enabled": bool(self.screen_enabled_var.get()),
            "privacy_acknowledged": bool(self.screen_privacy_var.get()),
            "allow_full_screen": bool(self.screen_full_var.get()),
            "allow_active_window": bool(self.screen_active_var.get()),
            "allow_window_capture": bool(self.screen_window_var.get()),
            "save_captures": bool(self.screen_save_var.get()),
            "retention_latest_only": bool(self.screen_latest_only_var.get()),
            "max_width": max(320, min(int(self.screen_max_width_var.get().strip() or "1920"), 7680)),
            "jpeg_quality": max(1, min(int(self.screen_jpeg_quality_var.get().strip() or "85"), 95)),
        }

    def save_screen_settings(self) -> None:
        try:
            new_screen = self._screen_config_from_vars()
            if new_screen.get("enabled") or new_screen.get("privacy_acknowledged"):
                phrase = simpledialog.askstring(
                    "Confirm Screen Tools",
                    f"Type exactly: {SCREEN_PHRASE}\n\n"
                    "Screen tools can expose visible windows, document titles, chats, browser pages, terminals, and secrets. "
                    "Use active-window/specific-window capture when possible. Full-screen capture should stay off unless needed.",
                    parent=self,
                )
                if phrase != SCREEN_PHRASE:
                    messagebox.showwarning(APP_TITLE, "Screen tools were not enabled.")
                    return
                new_screen["privacy_acknowledged"] = True

            self.cfg = load_config()
            self.cfg.setdefault("integrations", {})["screen"] = new_screen
            save_config(self.cfg)
            self.refresh_all()
            self.refresh_screen_status()
            messagebox.showinfo(APP_TITLE, "Screen settings saved. Restart the MCP server and refresh ChatGPT actions for tool exposure changes.")
        except Exception as exc:
            messagebox.showerror(APP_TITLE, f"Could not save screen settings: {exc}")

    def disable_screen_tools(self) -> None:
        self.cfg = load_config()
        screen = self.cfg.setdefault("integrations", {}).setdefault("screen", {})
        screen.update({
            "enabled": False,
            "privacy_acknowledged": False,
            "allow_full_screen": False,
            "allow_active_window": True,
            "allow_window_capture": True,
        })
        save_config(self.cfg)
        self.refresh_all()
        self.refresh_screen_status()
        messagebox.showinfo(APP_TITLE, "Screen tools disabled. Restart the MCP server and refresh ChatGPT actions if needed.")

    def refresh_screen_status(self) -> None:
        if not hasattr(self, "screen_status_text"):
            return
        self.screen_status_text.delete("1.0", "end")
        cfg = load_config()
        screen = cfg.setdefault("integrations", {}).setdefault("screen", {})
        self._write_screen_status({
            "screen_settings": screen,
            "safe_first_test": "screen_list_windows",
            "restart_required_after_changes": True,
            "notes": [
                "Full-screen capture requires allow_full_screen=true.",
                "Active-window and specific-window capture still require enabled=true and privacy_acknowledged=true.",
                "Captures are saved under ~/.local-files-mcp/screenshots by default.",
            ],
        })

    def test_screen_list_windows(self) -> None:
        try:
            result = screen_list_windows(load_config())
            self._write_screen_status(result)
            if not result.get("ok"):
                messagebox.showwarning(APP_TITLE, result.get("error", "screen_list_windows failed"))
        except Exception as exc:
            messagebox.showerror(APP_TITLE, f"screen_list_windows test failed: {exc}")

    def show_latest_screen_capture(self) -> None:
        try:
            result = screen_get_latest_frame(load_config())
            self._write_screen_status(result)
            if not result.get("ok"):
                messagebox.showinfo(APP_TITLE, result.get("error", "No latest screen capture metadata."))
        except Exception as exc:
            messagebox.showerror(APP_TITLE, f"Could not load latest capture metadata: {exc}")


def main() -> None:
    app = EnhancedGUIWithStops()
    app.mainloop()


if __name__ == "__main__":
    main()
