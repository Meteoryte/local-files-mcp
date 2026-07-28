from __future__ import annotations

import json
import os
import platform
import shutil
import subprocess
import time
import urllib.request
import webbrowser
from pathlib import Path
from typing import Any

import tkinter as tk
from tkinter import filedialog, messagebox, ttk
from tkinter.scrolledtext import ScrolledText

from .config import CONFIG_BACKUP_PATH, CONFIG_PATH, USER_SETTINGS_PATH, load_config, save_config
from .enhanced_gui import APP_TITLE, EnhancedGUI
from .ops import list_roots as op_list_roots
from .settings import base_url, mcp_url


KNOWN_PROBE_FILES = [
    "dangerous_mode_status_probe.txt",
    "dangerous_mode_status_probe_2.txt",
    "dangerous_mode_status_probe_3.txt",
    "dangerous_mode_write_test.txt",
    "direct_write_file_test.txt",
    "mcp_write_test.txt",
    "settings_write_test.txt",
]


class EnhancedGUIPlus(EnhancedGUI):
    """Small extension layer for settings backup/restore and diagnostics.

    This wrapper keeps local_files_mcp.enhanced_gui intact as a fallback while
    adding the maintenance controls that were planned after the Dangerous Mode
    work.
    """

    def _build_ui(self) -> None:
        super()._build_ui()
        self._add_settings_files_tab()

    def _notebook(self) -> ttk.Notebook | None:
        for child in self.winfo_children():
            if isinstance(child, ttk.Notebook):
                return child
        return None

    def _project_root(self) -> Path:
        return Path(__file__).resolve().parents[1]

    def _add_settings_files_tab(self) -> None:
        notebook = self._notebook()
        if notebook is None:
            return

        self.tab_settings_files = ttk.Frame(notebook)
        self.tab_settings_files.columnconfigure(0, weight=1)
        self.tab_settings_files.rowconfigure(2, weight=1)
        notebook.add(self.tab_settings_files, text="Settings Files")

        intro = ttk.LabelFrame(self.tab_settings_files, text="Backup, restore, import, and export")
        intro.grid(row=0, column=0, sticky="ew", padx=12, pady=12)
        intro.columnconfigure(0, weight=1)
        ttk.Label(
            intro,
            text=(
                "These controls operate on the persistent Local Files MCP settings files. "
                "Use Backup Now before experiments, Restore Last Good to roll back the previous config, "
                "and Export/Import to move settings between installs."
            ),
            wraplength=1050,
            justify="left",
        ).grid(row=0, column=0, sticky="w", padx=12, pady=10)

        paths = ttk.LabelFrame(self.tab_settings_files, text="Current paths")
        paths.grid(row=1, column=0, sticky="ew", padx=12, pady=8)
        paths.columnconfigure(1, weight=1)
        for row, (label, path) in enumerate(
            [
                ("Effective config", CONFIG_PATH),
                ("Persistent user settings", USER_SETTINGS_PATH),
                ("Last-good backup", CONFIG_BACKUP_PATH),
            ]
        ):
            ttk.Label(paths, text=label).grid(row=row, column=0, sticky="w", padx=12, pady=4)
            ttk.Label(paths, text=str(path), wraplength=880).grid(row=row, column=1, sticky="w", padx=12, pady=4)
            ttk.Button(paths, text="Open", command=lambda p=path: self._open_path(p)).grid(row=row, column=2, sticky="e", padx=8, pady=4)

        actions = ttk.LabelFrame(self.tab_settings_files, text="Actions")
        actions.grid(row=2, column=0, sticky="nsew", padx=12, pady=8)
        actions.columnconfigure(0, weight=0)
        actions.columnconfigure(1, weight=1)
        buttons = ttk.Frame(actions)
        buttons.grid(row=0, column=0, sticky="nsw", padx=10, pady=10)
        for i, (label, cmd) in enumerate(
            [
                ("Backup Now", self.backup_settings_now),
                ("Restore Last Good", self.restore_last_good_settings),
                ("Export Settings...", self.export_settings_file),
                ("Import Settings...", self.import_settings_file),
                ("Open Config Folder", self.open_config_folder),
                ("Copy MCP URL", self.copy_current_mcp_url),
                ("Test list_roots", self.test_list_roots),
                ("Open /tools", self.open_tools_diagnostics),
                ("Fetch /tools", self.fetch_tools_diagnostics),
                ("Clean Probe Files", self.clean_probe_files),
            ]
        ):
            ttk.Button(buttons, text=label, command=cmd).grid(row=i, column=0, sticky="ew", pady=3)

        self.settings_files_status = ScrolledText(actions, wrap="word", height=20)
        self.settings_files_status.grid(row=0, column=1, sticky="nsew", padx=10, pady=10)
        actions.rowconfigure(0, weight=1)
        self._write_settings_status("Settings maintenance tab ready.")

    def _write_settings_status(self, message: str | dict[str, Any] | list[Any]) -> None:
        if not hasattr(self, "settings_files_status"):
            return
        if isinstance(message, (dict, list)):
            rendered = json.dumps(message, indent=2, sort_keys=True)
        else:
            rendered = str(message)
        self.settings_files_status.insert("end", f"[{time.strftime('%H:%M:%S')}] {rendered}\n")
        self.settings_files_status.see("end")
        if hasattr(self, "log"):
            self.log(rendered.splitlines()[0] if rendered else "Settings maintenance action completed.")

    def _open_path(self, path: Path) -> None:
        target = path if path.exists() else path.parent
        try:
            if platform.system() == "Darwin":
                subprocess.Popen(["open", str(target)])
            elif platform.system().lower().startswith("win"):
                os.startfile(str(target))  # type: ignore[attr-defined]
            else:
                subprocess.Popen(["xdg-open", str(target)])
            self._write_settings_status(f"Opened: {target}")
        except Exception as exc:
            messagebox.showerror(APP_TITLE, f"Could not open {target}: {exc}")

    def backup_settings_now(self) -> None:
        try:
            CONFIG_PATH.parent.mkdir(parents=True, exist_ok=True)
            stamp = time.strftime("%Y%m%d-%H%M%S")
            copied: list[str] = []
            for source, stem in [(CONFIG_PATH, "config"), (USER_SETTINGS_PATH, "user_settings")]:
                if source.exists():
                    destination = source.with_name(f"{stem}.backup-{stamp}.json")
                    shutil.copy2(source, destination)
                    copied.append(str(destination))
            if CONFIG_PATH.exists():
                shutil.copy2(CONFIG_PATH, CONFIG_BACKUP_PATH)
                copied.append(str(CONFIG_BACKUP_PATH))
            if not copied:
                raise FileNotFoundError("No settings files exist yet.")
            self._write_settings_status("Backup created:\n" + "\n".join(copied))
            messagebox.showinfo(APP_TITLE, "Settings backup created.")
        except Exception as exc:
            messagebox.showerror(APP_TITLE, f"Backup failed: {exc}")

    def restore_last_good_settings(self) -> None:
        if not CONFIG_BACKUP_PATH.exists():
            messagebox.showwarning(APP_TITLE, f"No last-good backup found:\n{CONFIG_BACKUP_PATH}")
            return
        if not messagebox.askyesno(APP_TITLE, "Restore config.last-good.json? Current settings will be backed up first."):
            return
        try:
            self.backup_settings_now()
            with CONFIG_BACKUP_PATH.open("r", encoding="utf-8") as handle:
                restored = json.load(handle)
            save_config(restored)
            self.cfg = load_config()
            self.refresh_all()
            self._write_settings_status(f"Restored last-good settings from {CONFIG_BACKUP_PATH}")
            messagebox.showinfo(APP_TITLE, "Last-good settings restored.")
        except Exception as exc:
            messagebox.showerror(APP_TITLE, f"Restore failed: {exc}")

    def export_settings_file(self) -> None:
        default_name = f"local-files-mcp-settings-{time.strftime('%Y%m%d-%H%M%S')}.json"
        target = filedialog.asksaveasfilename(
            title="Export Local Files MCP settings",
            defaultextension=".json",
            initialfile=default_name,
            filetypes=[("JSON files", "*.json"), ("All files", "*.*")],
        )
        if not target:
            return
        try:
            data = load_config()
            with open(target, "w", encoding="utf-8") as handle:
                json.dump(data, handle, indent=2, sort_keys=True)
                handle.write("\n")
            self._write_settings_status(f"Exported settings to {target}")
            messagebox.showinfo(APP_TITLE, "Settings exported.")
        except Exception as exc:
            messagebox.showerror(APP_TITLE, f"Export failed: {exc}")

    def import_settings_file(self) -> None:
        source = filedialog.askopenfilename(
            title="Import Local Files MCP settings",
            filetypes=[("JSON files", "*.json"), ("All files", "*.*")],
        )
        if not source:
            return
        if not messagebox.askyesno(APP_TITLE, "Import this settings JSON? Current settings will be backed up first."):
            return
        try:
            with open(source, "r", encoding="utf-8") as handle:
                data = json.load(handle)
            if not isinstance(data, dict):
                raise ValueError("Settings file must contain a JSON object.")
            self.backup_settings_now()
            save_config(data)
            self.cfg = load_config()
            self.refresh_all()
            self._write_settings_status(f"Imported settings from {source}")
            messagebox.showinfo(APP_TITLE, "Settings imported.")
        except Exception as exc:
            messagebox.showerror(APP_TITLE, f"Import failed: {exc}")

    def copy_current_mcp_url(self) -> None:
        url = mcp_url(load_config())
        self.clipboard_clear()
        self.clipboard_append(url)
        self._write_settings_status(f"Copied MCP URL: {url}")

    def test_list_roots(self) -> None:
        try:
            result = op_list_roots(load_config())
            self._write_settings_status(result)
        except Exception as exc:
            messagebox.showerror(APP_TITLE, f"list_roots test failed: {exc}")

    def open_tools_diagnostics(self) -> None:
        url = base_url(load_config()).rstrip("/") + "/tools"
        webbrowser.open(url)
        self._write_settings_status(f"Opened diagnostics URL: {url}")

    def fetch_tools_diagnostics(self) -> None:
        url = base_url(load_config()).rstrip("/") + "/tools"
        try:
            with urllib.request.urlopen(url, timeout=6) as response:
                text = response.read(30000).decode("utf-8", errors="replace")
            try:
                parsed = json.loads(text)
                self._write_settings_status(parsed)
            except Exception:
                self._write_settings_status(text)
        except Exception as exc:
            messagebox.showerror(APP_TITLE, f"Could not fetch {url}: {exc}")

    def clean_probe_files(self) -> None:
        root = self._project_root()
        existing = [root / name for name in KNOWN_PROBE_FILES if (root / name).is_file()]
        if not existing:
            self._write_settings_status("No known probe/test files found to clean.")
            messagebox.showinfo(APP_TITLE, "No known probe/test files found.")
            return

        file_list = "\n".join(path.name for path in existing)
        if not messagebox.askyesno(
            APP_TITLE,
            "Delete these known probe/test files from the installer folder?\n\n" + file_list,
        ):
            self._write_settings_status("Probe/test cleanup cancelled.")
            return

        deleted: list[str] = []
        failed: dict[str, str] = {}
        for path in existing:
            try:
                path.unlink()
                deleted.append(path.name)
            except Exception as exc:
                failed[path.name] = str(exc)

        result: dict[str, Any] = {"deleted": deleted, "failed": failed}
        self._write_settings_status(result)
        if failed:
            messagebox.showwarning(APP_TITLE, "Some probe/test files could not be deleted. See the Settings Files log.")
        else:
            messagebox.showinfo(APP_TITLE, "Probe/test files cleaned.")


def main() -> None:
    app = EnhancedGUIPlus()
    app.mainloop()


if __name__ == "__main__":
    main()
