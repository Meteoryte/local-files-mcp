from __future__ import annotations

import json
import os
import platform
import shutil
import subprocess
import sys
import threading
import time
import urllib.request
import webbrowser
from pathlib import Path
from typing import Any

import tkinter as tk
from tkinter import ttk, filedialog, messagebox, simpledialog
from tkinter.scrolledtext import ScrolledText

from .auth import create_pairing_session, clear_session
from .config import (
    CONFIG_PATH,
    USER_SETTINGS_PATH,
    CONFIG_BACKUP_PATH,
    add_root,
    apply_full_access,
    apply_home_read,
    apply_project,
    apply_safe_inbox,
    dangerous_mode_enabled,
    direct_write_file_enabled,
    load_config,
    local_write_approval_required,
    save_config,
    set_dangerous_mode,
)
from .pending import list_pending, approve as approve_operation, reject as reject_operation, commit as commit_operation
from .settings import app_settings, format_settings, detect_ngrok, base_url, normalize_public_base_url, validate_chatgpt_url, mcp_url

APP_TITLE = "Local Files MCP Control Panel"
FULL_ACCESS_PHRASE = "I UNDERSTAND FULL ACCESS"
DANGEROUS_PHRASE = "ENABLE DANGEROUS MODE"


class FolderDialog(simpledialog.Dialog):
    def __init__(self, parent: tk.Tk, folder: str) -> None:
        self.folder = folder
        default_id = Path(folder).name.replace(" ", "_").replace("-", "_").lower() or "folder"
        self.root_id_var = tk.StringVar(value=default_id)
        self.access_var = tk.StringVar(value="write")
        self.result: tuple[str, str] | None = None
        super().__init__(parent, "Add folder")

    def body(self, master: tk.Widget) -> tk.Widget:
        master.columnconfigure(1, weight=1)
        ttk.Label(master, text="Folder").grid(row=0, column=0, sticky="w", padx=8, pady=6)
        ttk.Label(master, text=self.folder, wraplength=520).grid(row=0, column=1, sticky="w", padx=8, pady=6)
        ttk.Label(master, text="Root id").grid(row=1, column=0, sticky="w", padx=8, pady=6)
        entry = ttk.Entry(master, textvariable=self.root_id_var, width=38)
        entry.grid(row=1, column=1, sticky="ew", padx=8, pady=6)
        ttk.Label(master, text="Access").grid(row=2, column=0, sticky="w", padx=8, pady=6)
        combo = ttk.Combobox(master, textvariable=self.access_var, values=["metadata", "search", "read", "write"], state="readonly")
        combo.grid(row=2, column=1, sticky="w", padx=8, pady=6)
        ttk.Label(master, text="metadata = list root only\nsearch = filenames/snippets\nread = file contents\nwrite = create/overwrite files", justify="left").grid(row=3, column=0, columnspan=2, sticky="w", padx=8, pady=8)
        return entry

    def validate(self) -> bool:
        root_id = self.root_id_var.get().strip()
        if not root_id:
            messagebox.showerror(APP_TITLE, "Root id is required.")
            return False
        if any(ch in root_id for ch in "\\/ :"):
            messagebox.showerror(APP_TITLE, "Root id cannot contain spaces, slashes, or colons.")
            return False
        return True

    def apply(self) -> None:
        self.result = (self.root_id_var.get().strip(), self.access_var.get().strip())


class EnhancedGUI(tk.Tk):
    def __init__(self) -> None:
        super().__init__()
        self.title(APP_TITLE)
        self.geometry("1240x840")
        self.minsize(1040, 720)
        self.cfg = load_config()
        self.server_process: subprocess.Popen[str] | None = None
        self.ngrok_process: subprocess.Popen[str] | None = None
        self._log_queue: list[str] = []
        self._build_vars()
        self._build_ui()
        self.refresh_all()
        self.after(400, self._drain_log_queue)
        self.protocol("WM_DELETE_WINDOW", self.on_close)

    def _build_vars(self) -> None:
        server = self.cfg.setdefault("server", {})
        safety = self.cfg.setdefault("safety", {})
        dm = self.cfg.setdefault("dangerous_mode", {})
        auth = self.cfg.setdefault("auth", {})
        tunnel = self.cfg.setdefault("tunnel", {})
        self.name_var = tk.StringVar(value=server.get("name", "Local Files MCP"))
        self.description_var = tk.StringVar(value=server.get("description", "Safely read/search selected local folders; optionally prepare locally approved writes."))
        self.host_var = tk.StringVar(value=server.get("host", "127.0.0.1"))
        self.port_var = tk.StringVar(value=str(server.get("port", 8765)))
        self.public_url_var = tk.StringVar(value=server.get("public_url", ""))
        self.auth_mode_var = tk.StringVar(value=server.get("auth_mode", "noauth"))
        self.ngrok_path_var = tk.StringVar(value=tunnel.get("ngrok_path", ""))
        self.ngrok_token_var = tk.StringVar(value="")
        self.pairing_code_var = tk.StringVar(value="")
        self.server_status_var = tk.StringVar(value="Server stopped")
        self.tunnel_status_var = tk.StringVar(value="Tunnel stopped")

        self.redact_var = tk.BooleanVar(value=bool(safety.get("redact_secrets", True)))
        self.hidden_var = tk.BooleanVar(value=bool(safety.get("block_hidden_files", True)))
        self.binary_var = tk.BooleanVar(value=bool(safety.get("block_binary_files", True)))
        self.symlink_var = tk.BooleanVar(value=bool(safety.get("allow_symlinks", False)))
        self.max_file_var = tk.StringVar(value=str(safety.get("max_file_bytes", 1048576)))
        self.max_scan_var = tk.StringVar(value=str(safety.get("max_scan_files", 5000)))
        self.max_results_var = tk.StringVar(value=str(safety.get("max_search_results", 100)))
        self.pairing_ttl_var = tk.StringVar(value=str(auth.get("pairing_code_ttl_seconds", 3600)))
        self.access_ttl_var = tk.StringVar(value=str(auth.get("access_token_ttl_seconds", 2592000)))
        self.refresh_ttl_var = tk.StringVar(value=str(auth.get("refresh_token_ttl_seconds", 31536000)))

        self.danger_enabled_var = tk.BooleanVar(value=bool(dm.get("enabled", False)))
        self.danger_auto_var = tk.BooleanVar(value=bool(dm.get("auto_approve_prepared_writes", False)))
        self.danger_direct_var = tk.BooleanVar(value=bool(dm.get("expose_direct_write_file", False)))
        self.danger_create_var = tk.BooleanVar(value=bool(dm.get("allow_create", True)))
        self.danger_overwrite_var = tk.BooleanVar(value=bool(dm.get("allow_overwrite", True)))
        self.danger_delete_var = tk.BooleanVar(value=bool(dm.get("allow_delete", False)))
        self.danger_move_var = tk.BooleanVar(value=bool(dm.get("allow_move", False)))
        self.danger_shell_var = tk.BooleanVar(value=bool(dm.get("allow_shell", False)))

    def _build_ui(self) -> None:
        try:
            ttk.Style(self).theme_use("clam")
        except tk.TclError:
            pass
        self.columnconfigure(0, weight=1)
        self.rowconfigure(0, weight=1)
        nb = ttk.Notebook(self)
        nb.grid(row=0, column=0, sticky="nsew", padx=10, pady=10)
        self.tab_dash = ttk.Frame(nb)
        self.tab_folders = ttk.Frame(nb)
        self.tab_safety = ttk.Frame(nb)
        self.tab_server = ttk.Frame(nb)
        self.tab_pending = ttk.Frame(nb)
        self.tab_logs = ttk.Frame(nb)
        nb.add(self.tab_dash, text="Dashboard")
        nb.add(self.tab_folders, text="Folders & Access")
        nb.add(self.tab_safety, text="Safety & Dangerous Mode")
        nb.add(self.tab_server, text="Server + ChatGPT")
        nb.add(self.tab_pending, text="Write Approvals")
        nb.add(self.tab_logs, text="Logs")
        self._build_dashboard()
        self._build_folders()
        self._build_safety()
        self._build_server()
        self._build_pending()
        self._build_logs()

    def _build_dashboard(self) -> None:
        f = self.tab_dash
        f.columnconfigure(0, weight=1)
        f.columnconfigure(1, weight=1)
        f.rowconfigure(1, weight=1)
        status = ttk.LabelFrame(f, text="Current state")
        status.grid(row=0, column=0, columnspan=2, sticky="ew", padx=12, pady=12)
        status.columnconfigure(0, weight=1)
        self.summary_text = tk.Text(status, height=12, wrap="word", borderwidth=0)
        self.summary_text.grid(row=0, column=0, sticky="ew", padx=12, pady=10)
        self.summary_text.configure(state="disabled")

        presets = ttk.LabelFrame(f, text="Presets")
        presets.grid(row=1, column=0, sticky="nsew", padx=12, pady=8)
        presets.columnconfigure(0, weight=1)
        ttk.Button(presets, text="Safe Inbox", command=self.apply_safe_inbox_gui).grid(row=0, column=0, sticky="ew", padx=10, pady=5)
        ttk.Button(presets, text="Pick Project Folder", command=self.apply_project_gui).grid(row=1, column=0, sticky="ew", padx=10, pady=5)
        ttk.Button(presets, text="Home Read-Only", command=self.apply_home_gui).grid(row=2, column=0, sticky="ew", padx=10, pady=5)
        ttk.Button(presets, text="FULL ACCESS", command=self.apply_full_gui).grid(row=3, column=0, sticky="ew", padx=10, pady=5)
        ttk.Label(presets, text="Full Access controls path scope. Dangerous Mode is separate and controlled on the Safety tab.", wraplength=500).grid(row=4, column=0, sticky="ew", padx=10, pady=12)

        actions = ttk.LabelFrame(f, text="Common actions")
        actions.grid(row=1, column=1, sticky="nsew", padx=12, pady=8)
        actions.columnconfigure(0, weight=1)
        ttk.Button(actions, text="Save Settings", command=self.save_settings).grid(row=0, column=0, sticky="ew", padx=10, pady=5)
        ttk.Button(actions, text="Start Server", command=self.start_server).grid(row=1, column=0, sticky="ew", padx=10, pady=5)
        ttk.Button(actions, text="Start Tunnel", command=self.start_ngrok_tunnel).grid(row=2, column=0, sticky="ew", padx=10, pady=5)
        ttk.Button(actions, text="Copy ChatGPT Settings", command=self.copy_settings).grid(row=3, column=0, sticky="ew", padx=10, pady=5)
        ttk.Button(actions, text="Open Config Folder", command=self.open_config_folder).grid(row=4, column=0, sticky="ew", padx=10, pady=5)
        ttk.Label(actions, text="After changing Dangerous Mode or tool exposure, restart the MCP server and refresh/recreate the ChatGPT Developer Mode app actions.", wraplength=500).grid(row=5, column=0, sticky="ew", padx=10, pady=12)

    def _build_folders(self) -> None:
        f = self.tab_folders
        f.columnconfigure(0, weight=1)
        f.rowconfigure(1, weight=1)
        help_box = ttk.LabelFrame(f, text="Folder access")
        help_box.grid(row=0, column=0, sticky="ew", padx=12, pady=12)
        ttk.Label(help_box, text="Add folders with a dropdown access level. No JSON editing and no typing 'write' required.", wraplength=1000).grid(row=0, column=0, sticky="w", padx=12, pady=10)
        cols = ("id", "access", "path", "tags")
        self.roots_tree = ttk.Treeview(f, columns=cols, show="headings", selectmode="browse")
        for col in cols:
            self.roots_tree.heading(col, text=col)
        self.roots_tree.column("id", width=160, stretch=False)
        self.roots_tree.column("access", width=100, stretch=False)
        self.roots_tree.column("path", width=760)
        self.roots_tree.column("tags", width=180)
        self.roots_tree.grid(row=1, column=0, sticky="nsew", padx=12, pady=6)
        buttons = ttk.Frame(f)
        buttons.grid(row=2, column=0, sticky="ew", padx=12, pady=10)
        for i, (label, cmd) in enumerate([
            ("Add Folder...", self.add_folder_gui),
            ("Remove Selected", self.remove_selected_root),
            ("Metadata", lambda: self.set_selected_access("metadata")),
            ("Search", lambda: self.set_selected_access("search")),
            ("Read", lambda: self.set_selected_access("read")),
            ("Write", lambda: self.set_selected_access("write")),
            ("Refresh", self.refresh_roots),
            ("Save", self.save_settings),
        ]):
            ttk.Button(buttons, text=label, command=cmd).grid(row=0, column=i, padx=4)

    def _build_safety(self) -> None:
        f = self.tab_safety
        f.columnconfigure(0, weight=1)
        warning = ttk.LabelFrame(f, text="Safety model")
        warning.grid(row=0, column=0, sticky="ew", padx=12, pady=12)
        ttk.Label(warning, text="Full Access controls path scope. Root access controls read/write capability. Dangerous Mode controls local MCP write approval. ChatGPT may still show its own action confirmation prompts.", wraplength=1000, justify="left").grid(row=0, column=0, sticky="w", padx=12, pady=10)

        general = ttk.LabelFrame(f, text="General safety")
        general.grid(row=1, column=0, sticky="ew", padx=12, pady=8)
        ttk.Checkbutton(general, text="Redact likely secrets", variable=self.redact_var).grid(row=0, column=0, sticky="w", padx=12, pady=4)
        ttk.Checkbutton(general, text="Block hidden files/folders", variable=self.hidden_var).grid(row=1, column=0, sticky="w", padx=12, pady=4)
        ttk.Checkbutton(general, text="Block binary files", variable=self.binary_var).grid(row=2, column=0, sticky="w", padx=12, pady=4)
        ttk.Checkbutton(general, text="Allow symlinks", variable=self.symlink_var).grid(row=3, column=0, sticky="w", padx=12, pady=4)
        for row, (label, var) in enumerate([("Max file bytes", self.max_file_var), ("Max scan files", self.max_scan_var), ("Max search results", self.max_results_var)], start=4):
            ttk.Label(general, text=label).grid(row=row, column=0, sticky="w", padx=12, pady=5)
            ttk.Entry(general, textvariable=var, width=18).grid(row=row, column=1, sticky="w", padx=12, pady=5)

        danger = ttk.LabelFrame(f, text="Dangerous Mode")
        danger.grid(row=2, column=0, sticky="ew", padx=12, pady=12)
        ttk.Label(danger, text="Use these only when you intentionally want this local MCP to skip its own write approval flow for writable roots.", wraplength=1000).grid(row=0, column=0, columnspan=2, sticky="w", padx=12, pady=8)
        checks = [
            ("Enable Dangerous Mode", self.danger_enabled_var),
            ("Auto-approve prepared writes", self.danger_auto_var),
            ("Expose direct write_file action", self.danger_direct_var),
            ("Allow create new files", self.danger_create_var),
            ("Allow overwrite existing files", self.danger_overwrite_var),
            ("Allow delete files (tool support disabled unless separately implemented)", self.danger_delete_var),
            ("Allow move/rename files (tool support disabled unless separately implemented)", self.danger_move_var),
            ("Allow shell commands (should remain disabled)", self.danger_shell_var),
        ]
        for i, (label, var) in enumerate(checks, start=1):
            ttk.Checkbutton(danger, text=label, variable=var).grid(row=i, column=0, sticky="w", padx=12, pady=3)
        ttk.Button(danger, text="Save Dangerous Settings", command=self.save_dangerous_settings).grid(row=len(checks)+1, column=0, sticky="ew", padx=12, pady=8)
        ttk.Button(danger, text="Disable Dangerous Mode", command=self.disable_dangerous_mode).grid(row=len(checks)+2, column=0, sticky="ew", padx=12, pady=4)

    def _build_server(self) -> None:
        f = self.tab_server
        f.columnconfigure(1, weight=1)
        f.rowconfigure(7, weight=1)
        fields = [
            ("App name", self.name_var),
            ("Description", self.description_var),
            ("Host", self.host_var),
            ("Port", self.port_var),
            ("Public HTTPS base URL", self.public_url_var),
            ("ngrok executable", self.ngrok_path_var),
        ]
        for row, (label, var) in enumerate(fields):
            ttk.Label(f, text=label).grid(row=row, column=0, sticky="w", padx=12, pady=5)
            ttk.Entry(f, textvariable=var).grid(row=row, column=1, sticky="ew", padx=12, pady=5)
        auth = ttk.LabelFrame(f, text="Authentication")
        auth.grid(row=6, column=0, columnspan=2, sticky="ew", padx=12, pady=8)
        ttk.Radiobutton(auth, text="No authentication", variable=self.auth_mode_var, value="noauth").grid(row=0, column=0, sticky="w", padx=10, pady=3)
        ttk.Radiobutton(auth, text="OAuth / pairing code", variable=self.auth_mode_var, value="oauth").grid(row=1, column=0, sticky="w", padx=10, pady=3)
        ttk.Label(auth, text="Pairing TTL").grid(row=0, column=1, sticky="w", padx=10)
        ttk.Entry(auth, textvariable=self.pairing_ttl_var, width=12).grid(row=0, column=2, padx=5)
        ttk.Label(auth, text="Access TTL").grid(row=1, column=1, sticky="w", padx=10)
        ttk.Entry(auth, textvariable=self.access_ttl_var, width=12).grid(row=1, column=2, padx=5)
        ttk.Label(auth, text="Refresh TTL").grid(row=2, column=1, sticky="w", padx=10)
        ttk.Entry(auth, textvariable=self.refresh_ttl_var, width=12).grid(row=2, column=2, padx=5)
        ttk.Label(auth, text="Pairing code").grid(row=0, column=3, sticky="w", padx=10)
        ttk.Entry(auth, textvariable=self.pairing_code_var, state="readonly", width=24).grid(row=0, column=4, padx=5)
        ttk.Button(auth, text="Generate", command=self.generate_pairing_code).grid(row=1, column=4, sticky="ew", padx=5)
        ttk.Button(auth, text="Clear Session", command=self.clear_pairing).grid(row=2, column=4, sticky="ew", padx=5)

        buttons = ttk.Frame(f)
        buttons.grid(row=0, column=2, rowspan=7, sticky="ns", padx=12, pady=5)
        for i, (label, cmd) in enumerate([
            ("Save", self.save_settings),
            ("Start Server", self.start_server),
            ("Stop Server", self.stop_server),
            ("Find ngrok", self.find_ngrok_gui),
            ("Start Tunnel", self.start_ngrok_tunnel),
            ("Stop Tunnel", self.stop_ngrok_tunnel),
            ("Detect URL", self.detect_tunnel_gui),
            ("Validate URL", self.fix_validate_url),
            ("Open Health", self.open_health),
            ("Copy Settings", self.copy_settings),
        ]):
            ttk.Button(buttons, text=label, command=cmd).grid(row=i, column=0, sticky="ew", pady=3)
        ttk.Label(buttons, textvariable=self.server_status_var, wraplength=180).grid(row=10, column=0, sticky="ew", pady=8)
        ttk.Label(buttons, textvariable=self.tunnel_status_var, wraplength=180).grid(row=11, column=0, sticky="ew", pady=8)

        box = ttk.LabelFrame(f, text="ChatGPT Developer Mode settings")
        box.grid(row=7, column=0, columnspan=3, sticky="nsew", padx=12, pady=8)
        box.columnconfigure(0, weight=1)
        box.rowconfigure(0, weight=1)
        self.settings_text = ScrolledText(box, wrap="word", height=14)
        self.settings_text.grid(row=0, column=0, sticky="nsew", padx=8, pady=8)

    def _build_pending(self) -> None:
        f = self.tab_pending
        f.columnconfigure(0, weight=1)
        f.rowconfigure(0, weight=1)
        cols = ("operation_id", "approved", "committed", "source", "target_path")
        self.pending_tree = ttk.Treeview(f, columns=cols, show="headings", selectmode="browse")
        for col in cols:
            self.pending_tree.heading(col, text=col)
        self.pending_tree.column("operation_id", width=180, stretch=False)
        self.pending_tree.column("approved", width=90, stretch=False)
        self.pending_tree.column("committed", width=90, stretch=False)
        self.pending_tree.column("source", width=150, stretch=False)
        self.pending_tree.column("target_path", width=760)
        self.pending_tree.grid(row=0, column=0, sticky="nsew", padx=12, pady=12)
        self.pending_tree.bind("<<TreeviewSelect>>", lambda _e: self.show_selected_pending_diff())
        side = ttk.Frame(f)
        side.grid(row=0, column=1, sticky="ns", padx=(0, 12), pady=12)
        for i, (label, cmd) in enumerate([("Refresh", self.refresh_pending), ("Approve", self.approve_selected), ("Reject", self.reject_selected), ("Commit", self.commit_selected)]):
            ttk.Button(side, text=label, command=cmd).grid(row=i, column=0, sticky="ew", pady=4)
        diff = ttk.LabelFrame(f, text="Diff preview")
        diff.grid(row=1, column=0, columnspan=2, sticky="nsew", padx=12, pady=(0, 12))
        diff.columnconfigure(0, weight=1)
        self.diff_text = ScrolledText(diff, wrap="none", height=12)
        self.diff_text.grid(row=0, column=0, sticky="nsew", padx=8, pady=8)

    def _build_logs(self) -> None:
        f = self.tab_logs
        f.columnconfigure(0, weight=1)
        f.rowconfigure(0, weight=1)
        self.log_text = ScrolledText(f, wrap="word")
        self.log_text.grid(row=0, column=0, sticky="nsew", padx=12, pady=12)
        buttons = ttk.Frame(f)
        buttons.grid(row=1, column=0, sticky="ew", padx=12, pady=8)
        ttk.Button(buttons, text="Refresh Audit", command=self.refresh_audit_log).grid(row=0, column=0, padx=5)
        ttk.Button(buttons, text="Open Config Folder", command=self.open_config_folder).grid(row=0, column=1, padx=5)
        ttk.Button(buttons, text="Clear Screen", command=lambda: self.log_text.delete("1.0", "end")).grid(row=0, column=2, padx=5)

    def _sync_vars(self) -> None:
        self.cfg = load_config()
        server = self.cfg.get("server", {})
        safety = self.cfg.get("safety", {})
        dm = self.cfg.get("dangerous_mode", {})
        auth = self.cfg.get("auth", {})
        self.name_var.set(server.get("name", "Local Files MCP"))
        self.description_var.set(server.get("description", ""))
        self.host_var.set(server.get("host", "127.0.0.1"))
        self.port_var.set(str(server.get("port", 8765)))
        self.public_url_var.set(server.get("public_url", ""))
        self.auth_mode_var.set(server.get("auth_mode", "noauth"))
        self.ngrok_path_var.set(self.cfg.get("tunnel", {}).get("ngrok_path", ""))
        self.redact_var.set(bool(safety.get("redact_secrets", True)))
        self.hidden_var.set(bool(safety.get("block_hidden_files", True)))
        self.binary_var.set(bool(safety.get("block_binary_files", True)))
        self.symlink_var.set(bool(safety.get("allow_symlinks", False)))
        self.max_file_var.set(str(safety.get("max_file_bytes", 1048576)))
        self.max_scan_var.set(str(safety.get("max_scan_files", 5000)))
        self.max_results_var.set(str(safety.get("max_search_results", 100)))
        self.pairing_ttl_var.set(str(auth.get("pairing_code_ttl_seconds", 3600)))
        self.access_ttl_var.set(str(auth.get("access_token_ttl_seconds", 2592000)))
        self.refresh_ttl_var.set(str(auth.get("refresh_token_ttl_seconds", 31536000)))
        self.danger_enabled_var.set(bool(dm.get("enabled", False)))
        self.danger_auto_var.set(bool(dm.get("auto_approve_prepared_writes", False)))
        self.danger_direct_var.set(bool(dm.get("expose_direct_write_file", False)))
        self.danger_create_var.set(bool(dm.get("allow_create", True)))
        self.danger_overwrite_var.set(bool(dm.get("allow_overwrite", True)))
        self.danger_delete_var.set(bool(dm.get("allow_delete", False)))
        self.danger_move_var.set(bool(dm.get("allow_move", False)))
        self.danger_shell_var.set(bool(dm.get("allow_shell", False)))

    def save_settings(self) -> None:
        try:
            self.cfg = load_config()
            self.cfg.setdefault("server", {}).update({
                "name": self.name_var.get().strip() or "Local Files MCP",
                "description": self.description_var.get().strip(),
                "host": self.host_var.get().strip() or "127.0.0.1",
                "port": int(self.port_var.get().strip() or "8765"),
                "public_url": normalize_public_base_url(self.public_url_var.get()),
                "auth_mode": self.auth_mode_var.get(),
            })
            self.cfg.setdefault("tunnel", {})["ngrok_path"] = self.ngrok_path_var.get().strip()
            self.cfg.setdefault("auth", {}).update({
                "pairing_code_ttl_seconds": int(self.pairing_ttl_var.get().strip() or "3600"),
                "access_token_ttl_seconds": int(self.access_ttl_var.get().strip() or "2592000"),
                "refresh_token_ttl_seconds": int(self.refresh_ttl_var.get().strip() or "31536000"),
            })
            self.cfg.setdefault("safety", {}).update({
                "redact_secrets": bool(self.redact_var.get()),
                "block_hidden_files": bool(self.hidden_var.get()),
                "block_binary_files": bool(self.binary_var.get()),
                "allow_symlinks": bool(self.symlink_var.get()),
                "max_file_bytes": int(self.max_file_var.get().strip() or "1048576"),
                "max_scan_files": int(self.max_scan_var.get().strip() or "5000"),
                "max_search_results": int(self.max_results_var.get().strip() or "100"),
            })
            set_dangerous_mode(
                self.cfg,
                bool(self.danger_enabled_var.get()),
                warning_acknowledged=bool(self.danger_enabled_var.get()),
                auto_approve_prepared_writes=bool(self.danger_auto_var.get()),
                expose_direct_write_file=bool(self.danger_direct_var.get()),
                allow_create=bool(self.danger_create_var.get()),
                allow_overwrite=bool(self.danger_overwrite_var.get()),
                allow_delete=bool(self.danger_delete_var.get()),
                allow_move=bool(self.danger_move_var.get()),
                allow_shell=bool(self.danger_shell_var.get()),
            )
            save_config(self.cfg)
            self.log("Settings saved to config.json and persistent user_settings.json.")
            self.refresh_all()
        except Exception as e:
            messagebox.showerror(APP_TITLE, f"Could not save settings: {e}")

    def save_dangerous_settings(self) -> None:
        if self.danger_enabled_var.get():
            phrase = simpledialog.askstring("Confirm Dangerous Mode", f"Type exactly: {DANGEROUS_PHRASE}\n\nThis changes local MCP write approval behavior. ChatGPT may still ask for action confirmation.")
            if phrase != DANGEROUS_PHRASE:
                messagebox.showwarning(APP_TITLE, "Dangerous Mode not enabled.")
                self.danger_enabled_var.set(False)
                return
        self.save_settings()
        messagebox.showinfo(APP_TITLE, "Dangerous settings saved. Restart the MCP server and refresh ChatGPT app actions for tool changes.")

    def disable_dangerous_mode(self) -> None:
        self.cfg = load_config()
        set_dangerous_mode(self.cfg, False)
        save_config(self.cfg)
        self.refresh_all()
        messagebox.showinfo(APP_TITLE, "Dangerous Mode disabled. Restart server and refresh ChatGPT app actions.")

    def refresh_all(self) -> None:
        self._sync_vars()
        self.refresh_summary()
        self.refresh_roots()
        self.refresh_settings_text()
        self.refresh_pending()

    def refresh_summary(self) -> None:
        if not hasattr(self, "summary_text"):
            return
        roots = self.cfg.get("roots", [])
        writable = [r for r in roots if r.get("access") == "write"]
        full = any("full-access" in r.get("tags", []) for r in roots)
        lines = [
            f"Profile: {self.cfg.get('profile')}",
            f"Full Access root present: {'YES' if full else 'no'}",
            f"Dangerous Mode: {'ON' if dangerous_mode_enabled(self.cfg) else 'off'}",
            f"Local approval for prepared writes: {'required' if local_write_approval_required(self.cfg) else 'not required'}",
            f"Direct write_file action: {'enabled' if direct_write_file_enabled(self.cfg) else 'hidden'}",
            f"Writable roots: {len(writable)} of {len(roots)}",
            f"Auth mode: {self.cfg.get('server', {}).get('auth_mode')}",
            f"MCP URL: {mcp_url(self.cfg)}",
            f"Persistent settings: {USER_SETTINGS_PATH}",
            f"Last-good backup: {CONFIG_BACKUP_PATH}",
            "",
            "Roots:",
        ]
        for r in roots:
            lines.append(f"  - {r.get('id')} | {r.get('access')} | {r.get('path')}")
        self.summary_text.configure(state="normal")
        self.summary_text.delete("1.0", "end")
        self.summary_text.insert("1.0", "\n".join(lines))
        self.summary_text.configure(state="disabled")

    def refresh_roots(self) -> None:
        if not hasattr(self, "roots_tree"):
            return
        self.roots_tree.delete(*self.roots_tree.get_children())
        for root in self.cfg.get("roots", []):
            self.roots_tree.insert("", "end", values=(root.get("id"), root.get("access"), root.get("path"), ",".join(root.get("tags", []))))

    def add_folder_gui(self) -> None:
        folder = filedialog.askdirectory(title="Choose folder")
        if not folder:
            return
        dlg = FolderDialog(self, folder)
        if not dlg.result:
            return
        root_id, access = dlg.result
        try:
            self.cfg = load_config()
            add_root(self.cfg, root_id=root_id, path=folder, access=access)
            save_config(self.cfg)
            self.refresh_all()
        except Exception as e:
            messagebox.showerror(APP_TITLE, str(e))

    def remove_selected_root(self) -> None:
        sel = self.roots_tree.selection()
        if not sel:
            return
        root_id = self.roots_tree.item(sel[0], "values")[0]
        if not messagebox.askyesno(APP_TITLE, f"Remove root {root_id}?"):
            return
        self.cfg = load_config()
        self.cfg["roots"] = [r for r in self.cfg.get("roots", []) if r.get("id") != root_id]
        save_config(self.cfg)
        self.refresh_all()

    def set_selected_access(self, access: str) -> None:
        sel = self.roots_tree.selection()
        if not sel:
            messagebox.showinfo(APP_TITLE, "Select a root first.")
            return
        root_id = self.roots_tree.item(sel[0], "values")[0]
        self.cfg = load_config()
        for root in self.cfg.get("roots", []):
            if root.get("id") == root_id:
                root["access"] = access
                root["write_globs"] = ["**/*"] if access == "write" else []
        save_config(self.cfg)
        self.refresh_all()

    def apply_safe_inbox_gui(self) -> None:
        if messagebox.askyesno(APP_TITLE, "Switch to Safe Inbox? This replaces current roots and disables Dangerous Mode."):
            self.cfg = load_config()
            apply_safe_inbox(self.cfg)
            save_config(self.cfg)
            self.refresh_all()

    def apply_project_gui(self) -> None:
        folder = filedialog.askdirectory(title="Choose project folder")
        if not folder:
            return
        write = messagebox.askyesno(APP_TITLE, "Allow write access for this project folder?")
        self.cfg = load_config()
        apply_project(self.cfg, folder, write=write)
        save_config(self.cfg)
        self.refresh_all()

    def apply_home_gui(self) -> None:
        if messagebox.askyesno(APP_TITLE, "Use home folder read-only with deny rules?"):
            self.cfg = load_config()
            apply_home_read(self.cfg)
            save_config(self.cfg)
            self.refresh_all()

    def apply_full_gui(self) -> None:
        phrase = simpledialog.askstring("FULL ACCESS", f"Type exactly: {FULL_ACCESS_PHRASE}\n\nFull Access controls filesystem scope. Dangerous Mode remains separate.")
        if phrase != FULL_ACCESS_PHRASE:
            messagebox.showwarning(APP_TITLE, "Full Access cancelled.")
            return
        self.cfg = load_config()
        apply_full_access(self.cfg)
        save_config(self.cfg)
        self.refresh_all()
        messagebox.showwarning(APP_TITLE, "Full Access enabled. Dangerous Mode remains separate.")

    def refresh_settings_text(self) -> None:
        if not hasattr(self, "settings_text"):
            return
        try:
            text = format_settings(self.cfg)
            s = app_settings(self.cfg)
            text += "\n\nPersistent settings\n===================\n"
            text += f"User settings: {USER_SETTINGS_PATH}\nEffective config: {CONFIG_PATH}\nLast-good backup: {CONFIG_BACKUP_PATH}\n"
            text += "\nCurrent safety state\n====================\n"
            text += f"Dangerous Mode: {dangerous_mode_enabled(self.cfg)}\n"
            text += f"Local approval required: {local_write_approval_required(self.cfg)}\n"
            text += f"Direct write_file enabled: {direct_write_file_enabled(self.cfg)}\n"
            text += "\nCopyable fields\n===============\n"
            text += f"Name: {s['name']}\nDescription: {s['description']}\nMCP URL / Connector URL: {s['connector_url']}\nAuthentication: {s['authentication']}\n"
        except Exception as e:
            text = f"Could not render settings: {e}"
        self.settings_text.delete("1.0", "end")
        self.settings_text.insert("1.0", text)

    def copy_settings(self) -> None:
        self.refresh_settings_text()
        text = self.settings_text.get("1.0", "end").strip()
        self.clipboard_clear()
        self.clipboard_append(text)
        self.log("Copied ChatGPT settings.")

    def start_server(self) -> None:
        self.save_settings()
        if self.server_process and self.server_process.poll() is None:
            messagebox.showinfo(APP_TITLE, "Server already running.")
            return
        host = self.cfg.get("server", {}).get("host", "127.0.0.1")
        port = str(self.cfg.get("server", {}).get("port", 8765))
        cmd = [sys.executable, "-m", "uvicorn", "local_files_mcp.server:app", "--host", host, "--port", port]
        try:
            self.server_process = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, bufsize=1, cwd=str(Path(__file__).resolve().parents[1]))
            self.server_status_var.set(f"Server running at http://{host}:{port}/mcp")
            threading.Thread(target=self._read_server_output, daemon=True).start()
            self.log("Started server: " + " ".join(cmd))
        except Exception as e:
            messagebox.showerror(APP_TITLE, f"Could not start server: {e}")

    def stop_server(self) -> None:
        if self.server_process and self.server_process.poll() is None:
            self.server_process.terminate()
            try:
                self.server_process.wait(timeout=4)
            except subprocess.TimeoutExpired:
                self.server_process.kill()
            self.log("Server stopped.")
        self.server_status_var.set("Server stopped")

    def _read_server_output(self) -> None:
        proc = self.server_process
        if not proc or not proc.stdout:
            return
        for line in proc.stdout:
            self._log_queue.append(line.rstrip())
        self._log_queue.append("Server process exited.")

    def _ngrok_bin(self) -> str | None:
        configured = self.ngrok_path_var.get().strip()
        if configured and Path(configured).exists():
            return configured
        found = shutil.which("ngrok")
        if found:
            self.ngrok_path_var.set(found)
            return found
        return None

    def find_ngrok_gui(self) -> None:
        found = shutil.which("ngrok")
        if found:
            self.ngrok_path_var.set(found)
            self.save_settings()
            messagebox.showinfo(APP_TITLE, f"Found ngrok:\n{found}")
        else:
            messagebox.showwarning(APP_TITLE, "ngrok was not found on PATH.")

    def start_ngrok_tunnel(self) -> None:
        if not (self.server_process and self.server_process.poll() is None):
            if messagebox.askyesno(APP_TITLE, "Server is not running. Start it first?"):
                self.start_server()
                self.update_idletasks()
                time.sleep(1)
            else:
                return
        ngrok = self._ngrok_bin()
        if not ngrok:
            webbrowser.open("https://ngrok.com/download")
            messagebox.showerror(APP_TITLE, "ngrok is not installed or selected.")
            return
        if self.ngrok_process and self.ngrok_process.poll() is None:
            messagebox.showinfo(APP_TITLE, "Tunnel already running.")
            return
        port = str(self.cfg.get("server", {}).get("port", 8765))
        cmd = [ngrok, "http", port]
        try:
            self.ngrok_process = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, bufsize=1)
            self.tunnel_status_var.set(f"Tunnel starting for localhost:{port}")
            threading.Thread(target=self._read_ngrok_output, daemon=True).start()
            self.after(1200, self.detect_tunnel_after_start)
            self.log("Started ngrok: " + " ".join(cmd))
        except Exception as e:
            messagebox.showerror(APP_TITLE, f"Could not start ngrok: {e}")

    def _read_ngrok_output(self) -> None:
        proc = self.ngrok_process
        if not proc or not proc.stdout:
            return
        for line in proc.stdout:
            self._log_queue.append("[ngrok] " + line.rstrip())
        self._log_queue.append("ngrok process exited.")

    def stop_ngrok_tunnel(self) -> None:
        if self.ngrok_process and self.ngrok_process.poll() is None:
            self.ngrok_process.terminate()
            try:
                self.ngrok_process.wait(timeout=4)
            except subprocess.TimeoutExpired:
                self.ngrok_process.kill()
            self.log("Tunnel stopped.")
        self.tunnel_status_var.set("Tunnel stopped")

    def detect_tunnel_after_start(self, attempts: int = 12) -> None:
        url = detect_ngrok()
        if url:
            self.public_url_var.set(url)
            self.save_settings()
            self.tunnel_status_var.set(f"Tunnel running: {url}")
            return
        if attempts > 0 and self.ngrok_process and self.ngrok_process.poll() is None:
            self.after(1000, lambda: self.detect_tunnel_after_start(attempts - 1))
            return
        self.tunnel_status_var.set("Tunnel running, URL not detected yet.")

    def detect_tunnel_gui(self) -> None:
        url = detect_ngrok()
        if not url:
            messagebox.showwarning(APP_TITLE, "No ngrok tunnel detected.")
            return
        self.public_url_var.set(url)
        self.save_settings()
        messagebox.showinfo(APP_TITLE, f"Saved public URL:\n{url}")

    def fix_validate_url(self) -> None:
        self.public_url_var.set(normalize_public_base_url(self.public_url_var.get()))
        self.save_settings()
        final_url = mcp_url(self.cfg)
        ok, message, _corrected = validate_chatgpt_url(final_url)
        if ok:
            messagebox.showinfo(APP_TITLE, "URL looks ready:\n\n" + final_url)
        else:
            messagebox.showwarning(APP_TITLE, message)

    def open_health(self) -> None:
        self.save_settings()
        webbrowser.open(base_url(self.cfg).rstrip("/") + "/health")

    def generate_pairing_code(self) -> None:
        self.save_settings()
        ttl = int(self.cfg.get("auth", {}).get("pairing_code_ttl_seconds", 3600))
        code = create_pairing_session(ttl)
        self.pairing_code_var.set(code)
        self.clipboard_clear()
        self.clipboard_append(code)
        messagebox.showinfo(APP_TITLE, f"Pairing code copied. Expires in {ttl} seconds.")

    def clear_pairing(self) -> None:
        clear_session()
        self.pairing_code_var.set("")
        self.log("Pairing session cleared.")

    def refresh_pending(self) -> None:
        if not hasattr(self, "pending_tree"):
            return
        self.pending_tree.delete(*self.pending_tree.get_children())
        self._pending_items = list_pending()
        for item in self._pending_items:
            self.pending_tree.insert("", "end", iid=item.get("operation_id"), values=(item.get("operation_id"), item.get("approved"), item.get("committed"), item.get("approval_source"), item.get("target_path")))
        self.show_selected_pending_diff()

    def selected_operation_id(self) -> str | None:
        sel = self.pending_tree.selection()
        return sel[0] if sel else None

    def show_selected_pending_diff(self) -> None:
        if not hasattr(self, "diff_text"):
            return
        op_id = self.selected_operation_id()
        self.diff_text.delete("1.0", "end")
        if not op_id:
            return
        for item in getattr(self, "_pending_items", []):
            if item.get("operation_id") == op_id:
                self.diff_text.insert("1.0", item.get("diff_preview") or "")
                break

    def approve_selected(self) -> None:
        op_id = self.selected_operation_id()
        if not op_id:
            return
        self.log(json.dumps(approve_operation(op_id)))
        self.refresh_pending()

    def reject_selected(self) -> None:
        op_id = self.selected_operation_id()
        if not op_id:
            return
        if messagebox.askyesno(APP_TITLE, f"Reject operation {op_id}?"):
            self.log(json.dumps(reject_operation(op_id)))
            self.refresh_pending()

    def commit_selected(self) -> None:
        op_id = self.selected_operation_id()
        if not op_id:
            return
        if not messagebox.askyesno(APP_TITLE, f"Commit operation to disk?\n\n{op_id}"):
            return
        result = commit_operation(load_config(), op_id)
        self.log(json.dumps(result))
        if not result.get("ok"):
            messagebox.showerror(APP_TITLE, result.get("error", "Commit failed"))
        self.refresh_pending()

    def refresh_audit_log(self) -> None:
        audit_path = Path(self.cfg.get("audit", {}).get("path", str(Path.home() / ".local-files-mcp" / "audit.jsonl"))).expanduser()
        if not audit_path.exists():
            self.log("Audit log not created yet.")
            return
        try:
            lines = audit_path.read_text(encoding="utf-8", errors="replace").splitlines()[-200:]
            self.log_text.delete("1.0", "end")
            self.log_text.insert("1.0", "\n".join(lines) + "\n")
        except Exception as e:
            self.log(f"Could not read audit log: {e}")

    def open_config_folder(self) -> None:
        folder = CONFIG_PATH.parent
        folder.mkdir(parents=True, exist_ok=True)
        if platform.system() == "Darwin":
            subprocess.Popen(["open", str(folder)])
        elif platform.system().lower().startswith("win"):
            os.startfile(str(folder))  # type: ignore[attr-defined]
        else:
            subprocess.Popen(["xdg-open", str(folder)])

    def _drain_log_queue(self) -> None:
        while self._log_queue:
            self.log(self._log_queue.pop(0))
        self.after(400, self._drain_log_queue)

    def log(self, message: str) -> None:
        if hasattr(self, "log_text"):
            self.log_text.insert("end", f"[{time.strftime('%H:%M:%S')}] {message}\n")
            self.log_text.see("end")

    def on_close(self) -> None:
        if self.ngrok_process and self.ngrok_process.poll() is None:
            self.stop_ngrok_tunnel()
        if self.server_process and self.server_process.poll() is None:
            if messagebox.askyesno(APP_TITLE, "Stop MCP server and quit?"):
                self.stop_server()
            else:
                return
        self.destroy()


def main() -> None:
    app = EnhancedGUI()
    app.mainloop()


if __name__ == "__main__":
    main()
