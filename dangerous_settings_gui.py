from __future__ import annotations

import tkinter as tk
from tkinter import ttk, messagebox, simpledialog

from local_files_mcp.config import load_config, save_config, set_dangerous_mode

APP_TITLE = "Local Files MCP - Dangerous Settings"
CONFIRM_PHRASE = "ENABLE DANGEROUS MODE"


class DangerousSettingsGUI(tk.Tk):
    def __init__(self) -> None:
        super().__init__()
        self.title(APP_TITLE)
        self.geometry("760x560")
        self.minsize(680, 500)
        self.cfg = load_config()
        self._build_vars()
        self._build_ui()
        self.refresh_status()

    def _build_vars(self) -> None:
        dm = self.cfg.setdefault("dangerous_mode", {})
        self.enabled_var = tk.BooleanVar(value=bool(dm.get("enabled", False)))
        self.auto_approve_var = tk.BooleanVar(value=bool(dm.get("auto_approve_prepared_writes", False)))
        self.direct_write_var = tk.BooleanVar(value=bool(dm.get("expose_direct_write_file", False)))
        self.allow_create_var = tk.BooleanVar(value=bool(dm.get("allow_create", True)))
        self.allow_overwrite_var = tk.BooleanVar(value=bool(dm.get("allow_overwrite", True)))
        self.allow_delete_var = tk.BooleanVar(value=bool(dm.get("allow_delete", False)))
        self.allow_move_var = tk.BooleanVar(value=bool(dm.get("allow_move", False)))
        self.allow_shell_var = tk.BooleanVar(value=bool(dm.get("allow_shell", False)))

    def _build_ui(self) -> None:
        self.columnconfigure(0, weight=1)
        self.rowconfigure(3, weight=1)

        warning = ttk.LabelFrame(self, text="Warning")
        warning.grid(row=0, column=0, sticky="ew", padx=12, pady=12)
        ttk.Label(
            warning,
            text=(
                "Dangerous Mode controls LOCAL MCP write approval only. "
                "It does not disable ChatGPT's own action confirmation prompts.\n\n"
                "Full Access controls which paths are reachable. Dangerous Mode controls whether this MCP requires local GUI approval before writing. "
                "With a writable whole-disk root, these settings are powerful."
            ),
            wraplength=700,
            justify="left",
        ).grid(row=0, column=0, sticky="w", padx=12, pady=10)

        controls = ttk.LabelFrame(self, text="Dangerous Settings")
        controls.grid(row=1, column=0, sticky="ew", padx=12, pady=8)
        for i, (label, var) in enumerate([
            ("Enable Dangerous Mode", self.enabled_var),
            ("Auto-approve prepared writes", self.auto_approve_var),
            ("Expose direct write_file tool", self.direct_write_var),
            ("Allow create new files", self.allow_create_var),
            ("Allow overwrite existing files", self.allow_overwrite_var),
            ("Allow delete files (server support may still be disabled)", self.allow_delete_var),
            ("Allow move/rename files (server support may still be disabled)", self.allow_move_var),
            ("Allow shell commands (server support should remain disabled)", self.allow_shell_var),
        ]):
            ttk.Checkbutton(controls, text=label, variable=var).grid(row=i, column=0, sticky="w", padx=12, pady=4)

        buttons = ttk.Frame(self)
        buttons.grid(row=2, column=0, sticky="ew", padx=12, pady=8)
        ttk.Button(buttons, text="Save Dangerous Settings", command=self.save).grid(row=0, column=0, padx=5)
        ttk.Button(buttons, text="Disable Dangerous Mode", command=self.disable).grid(row=0, column=1, padx=5)
        ttk.Button(buttons, text="Refresh", command=self.refresh_status).grid(row=0, column=2, padx=5)

        status_box = ttk.LabelFrame(self, text="Current effective state")
        status_box.grid(row=3, column=0, sticky="nsew", padx=12, pady=12)
        status_box.columnconfigure(0, weight=1)
        status_box.rowconfigure(0, weight=1)
        self.status = tk.Text(status_box, wrap="word", height=12)
        self.status.grid(row=0, column=0, sticky="nsew", padx=8, pady=8)

    def save(self) -> None:
        enabled = bool(self.enabled_var.get())
        if enabled:
            phrase = simpledialog.askstring(
                "Confirm Dangerous Mode",
                f"Type exactly: {CONFIRM_PHRASE}\n\nThis only changes Local Files MCP approval behavior. ChatGPT may still ask for action confirmation.",
                parent=self,
            )
            if phrase != CONFIRM_PHRASE:
                messagebox.showwarning(APP_TITLE, "Dangerous Mode was not enabled.")
                self.enabled_var.set(False)
                return

        self.cfg = load_config()
        set_dangerous_mode(
            self.cfg,
            enabled,
            warning_acknowledged=enabled,
            auto_approve_prepared_writes=bool(self.auto_approve_var.get()),
            expose_direct_write_file=bool(self.direct_write_var.get()),
            allow_create=bool(self.allow_create_var.get()),
            allow_overwrite=bool(self.allow_overwrite_var.get()),
            allow_delete=bool(self.allow_delete_var.get()),
            allow_move=bool(self.allow_move_var.get()),
            allow_shell=bool(self.allow_shell_var.get()),
        )
        save_config(self.cfg)
        self.refresh_status()
        messagebox.showinfo(APP_TITLE, "Saved. Restart the MCP server and refresh ChatGPT app actions for tool changes to appear.")

    def disable(self) -> None:
        self.cfg = load_config()
        set_dangerous_mode(self.cfg, False)
        save_config(self.cfg)
        self.enabled_var.set(False)
        self.auto_approve_var.set(False)
        self.direct_write_var.set(False)
        self.refresh_status()
        messagebox.showinfo(APP_TITLE, "Dangerous Mode disabled. Restart the MCP server and refresh ChatGPT app actions.")

    def refresh_status(self) -> None:
        self.cfg = load_config()
        dm = self.cfg.get("dangerous_mode", {})
        safety = self.cfg.get("safety", {})
        tools = self.cfg.get("tools", {})
        roots = self.cfg.get("roots", [])
        lines = [
            "Dangerous Mode settings:",
            f"  enabled: {dm.get('enabled')}",
            f"  auto_approve_prepared_writes: {dm.get('auto_approve_prepared_writes')}",
            f"  expose_direct_write_file: {dm.get('expose_direct_write_file')}",
            f"  allow_create: {dm.get('allow_create')}",
            f"  allow_overwrite: {dm.get('allow_overwrite')}",
            f"  allow_delete: {dm.get('allow_delete')}",
            f"  allow_move: {dm.get('allow_move')}",
            f"  allow_shell: {dm.get('allow_shell')}",
            "",
            "Effective MCP state:",
            f"  require_local_approval_for_writes: {safety.get('require_local_approval_for_writes')}",
            f"  write_file tool exposed after restart/refresh: {tools.get('write_file')}",
            "",
            "Roots:",
        ]
        for r in roots:
            lines.append(f"  {r.get('id')} | {r.get('access')} | {r.get('path')}")
        self.status.delete("1.0", "end")
        self.status.insert("1.0", "\n".join(lines))


def main() -> None:
    app = DangerousSettingsGUI()
    app.mainloop()


if __name__ == "__main__":
    main()
