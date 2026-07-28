from __future__ import annotations

import json
import os
import platform
import subprocess
import sys
import shutil
import threading
import time
import webbrowser
from pathlib import Path
from typing import Any

import tkinter as tk
from tkinter import ttk, filedialog, messagebox, simpledialog
from tkinter.scrolledtext import ScrolledText

from .auth import create_pairing_session, clear_session
from .config import (
    CONFIG_PATH,
    add_root,
    apply_full_access,
    apply_home_read,
    apply_project,
    apply_safe_inbox,
    default_config,
    load_config,
    save_config,
)
from .pending import list_pending, approve as approve_operation, reject as reject_operation, commit as commit_operation
from .settings import app_settings, format_settings, detect_ngrok, base_url, normalize_public_base_url, validate_chatgpt_url, mcp_url

APP_TITLE = "Local Files MCP Control Panel"
DANGER_PHRASE = "I UNDERSTAND FULL ACCESS"


class LocalFilesMcpGUI(tk.Tk):
    def __init__(self) -> None:
        super().__init__()
        self.title(APP_TITLE)
        self.geometry("1180x780")
        self.minsize(980, 680)
        self.server_process: subprocess.Popen[str] | None = None
        self.ngrok_process: subprocess.Popen[str] | None = None
        self._log_queue: list[str] = []
        self.cfg = load_config()
        self._build_vars()
        self._build_ui()
        self.refresh_all()
        self.after(500, self._drain_log_queue)
        self.protocol("WM_DELETE_WINDOW", self.on_close)

    def _build_vars(self) -> None:
        server = self.cfg.setdefault("server", {})
        self.name_var = tk.StringVar(value=server.get("name", "Local Files MCP"))
        self.description_var = tk.StringVar(value=server.get("description", "Safely read/search selected local folders; optionally prepare locally approved writes."))
        self.host_var = tk.StringVar(value=server.get("host", "127.0.0.1"))
        self.port_var = tk.StringVar(value=str(server.get("port", 8765)))
        self.public_url_var = tk.StringVar(value=server.get("public_url", ""))
        tunnel = self.cfg.setdefault("tunnel", {})
        self.ngrok_path_var = tk.StringVar(value=tunnel.get("ngrok_path", ""))
        self.ngrok_token_var = tk.StringVar(value="")
        self.ngrok_status_var = tk.StringVar(value="ngrok tunnel stopped")
        self.auth_mode_var = tk.StringVar(value=server.get("auth_mode", "noauth"))
        self.status_var = tk.StringVar(value="Server stopped")
        self.pairing_code_var = tk.StringVar(value="")

        safety = self.cfg.setdefault("safety", {})
        self.redact_var = tk.BooleanVar(value=bool(safety.get("redact_secrets", True)))
        self.hidden_var = tk.BooleanVar(value=bool(safety.get("block_hidden_files", True)))
        self.binary_var = tk.BooleanVar(value=bool(safety.get("block_binary_files", True)))
        self.symlink_var = tk.BooleanVar(value=bool(safety.get("allow_symlinks", False)))
        self.approval_var = tk.BooleanVar(value=bool(safety.get("require_local_approval_for_writes", True)))
        self.max_file_var = tk.StringVar(value=str(safety.get("max_file_bytes", 1048576)))
        self.max_scan_var = tk.StringVar(value=str(safety.get("max_scan_files", 5000)))
        self.max_results_var = tk.StringVar(value=str(safety.get("max_search_results", 100)))

    def _build_ui(self) -> None:
        style = ttk.Style(self)
        try:
            style.theme_use("clam")
        except tk.TclError:
            pass

        self.columnconfigure(0, weight=1)
        self.rowconfigure(0, weight=1)
        notebook = ttk.Notebook(self)
        notebook.grid(row=0, column=0, sticky="nsew", padx=10, pady=10)

        self.tab_quick = ttk.Frame(notebook)
        self.tab_settings = ttk.Frame(notebook)
        self.tab_roots = ttk.Frame(notebook)
        self.tab_server = ttk.Frame(notebook)
        self.tab_pending = ttk.Frame(notebook)
        self.tab_logs = ttk.Frame(notebook)

        notebook.add(self.tab_quick, text="Quick Setup")
        notebook.add(self.tab_settings, text="Settings")
        notebook.add(self.tab_roots, text="Folders / Access")
        notebook.add(self.tab_server, text="Server + ChatGPT")
        notebook.add(self.tab_pending, text="Write Approvals")
        notebook.add(self.tab_logs, text="Logs")

        self._build_quick_tab()
        self._build_settings_tab()
        self._build_roots_tab()
        self._build_server_tab()
        self._build_pending_tab()
        self._build_logs_tab()

    def _build_quick_tab(self) -> None:
        f = self.tab_quick
        f.columnconfigure(0, weight=1)
        f.columnconfigure(1, weight=1)

        intro = ttk.LabelFrame(f, text="Choose a mode")
        intro.grid(row=0, column=0, columnspan=2, sticky="ew", padx=12, pady=12)
        intro.columnconfigure(0, weight=1)
        ttk.Label(
            intro,
            text=(
                "Use this page to configure everything without editing JSON. "
                "Safe Inbox is recommended. Full Access is available but dangerous."
            ),
            wraplength=980,
        ).grid(row=0, column=0, sticky="w", padx=12, pady=10)

        cards = ttk.Frame(f)
        cards.grid(row=1, column=0, columnspan=2, sticky="nsew", padx=12)
        for i in range(2):
            cards.columnconfigure(i, weight=1)

        self._quick_card(
            cards,
            0,
            0,
            "Safe Inbox",
            "Creates ~/ChatGPT-MCP-Inbox and only lets the MCP read files you put there.",
            "Use Safe Inbox",
            self.apply_safe_inbox_gui,
        )
        self._quick_card(
            cards,
            0,
            1,
            "Project Folder",
            "Pick one project folder. You can choose read-only or write-preparation mode.",
            "Pick Project Folder",
            self.apply_project_gui,
        )
        self._quick_card(
            cards,
            1,
            0,
            "Home Read-Only",
            "Read-only access to your home folder with deny rules for secrets, .git, node_modules, etc.",
            "Use Home Read-Only",
            self.apply_home_gui,
        )
        self._quick_card(
            cards,
            1,
            1,
            "FULL ACCESS",
            "Entire disk/root, write-capable, no deny rules. Writes still require local approval. Dangerous.",
            "Enable FULL ACCESS",
            self.apply_full_gui,
            danger=True,
        )

        bottom = ttk.LabelFrame(f, text="After setup")
        bottom.grid(row=2, column=0, columnspan=2, sticky="ew", padx=12, pady=14)
        for i in range(5):
            bottom.columnconfigure(i, weight=1)
        ttk.Button(bottom, text="Start MCP Server", command=self.start_server).grid(row=0, column=0, sticky="ew", padx=8, pady=8)
        ttk.Button(bottom, text="Start ngrok Tunnel", command=self.start_ngrok_tunnel).grid(row=0, column=1, sticky="ew", padx=8, pady=8)
        ttk.Button(bottom, text="Detect/Validate URL", command=self.detect_tunnel_gui).grid(row=0, column=2, sticky="ew", padx=8, pady=8)
        ttk.Button(bottom, text="Copy ChatGPT Settings", command=self.copy_settings).grid(row=0, column=3, sticky="ew", padx=8, pady=8)
        ttk.Button(bottom, text="Save Settings File", command=self.save_settings_file).grid(row=0, column=4, sticky="ew", padx=8, pady=8)

    def _quick_card(self, parent: ttk.Frame, row: int, col: int, title: str, desc: str, button: str, command, danger: bool = False) -> None:
        box = ttk.LabelFrame(parent, text=title)
        box.grid(row=row, column=col, sticky="nsew", padx=8, pady=8)
        box.columnconfigure(0, weight=1)
        ttk.Label(box, text=desc, wraplength=480).grid(row=0, column=0, sticky="w", padx=12, pady=(10, 8))
        b = ttk.Button(box, text=button, command=command)
        b.grid(row=1, column=0, sticky="ew", padx=12, pady=(0, 12))
        if danger:
            ttk.Label(box, text="Requires typing a confirmation phrase.", foreground="#8a3b00").grid(row=2, column=0, sticky="w", padx=12, pady=(0, 10))

    def _build_settings_tab(self) -> None:
        f = self.tab_settings
        f.columnconfigure(1, weight=1)
        row = 0
        for label, var in [
            ("App name", self.name_var),
            ("Description", self.description_var),
            ("Host", self.host_var),
            ("Port", self.port_var),
            ("Public HTTPS URL", self.public_url_var),
        ]:
            ttk.Label(f, text=label).grid(row=row, column=0, sticky="w", padx=12, pady=6)
            ttk.Entry(f, textvariable=var).grid(row=row, column=1, sticky="ew", padx=12, pady=6)
            row += 1

        ttk.Label(f, text="Authentication").grid(row=row, column=0, sticky="w", padx=12, pady=6)
        auth_frame = ttk.Frame(f)
        auth_frame.grid(row=row, column=1, sticky="w", padx=12, pady=6)
        ttk.Radiobutton(auth_frame, text="No authentication (easiest local dev)", value="noauth", variable=self.auth_mode_var).grid(row=0, column=0, sticky="w")
        ttk.Radiobutton(auth_frame, text="Pairing-code OAuth-style auth", value="oauth", variable=self.auth_mode_var).grid(row=1, column=0, sticky="w")
        row += 1

        safety_box = ttk.LabelFrame(f, text="Safety controls")
        safety_box.grid(row=row, column=0, columnspan=2, sticky="ew", padx=12, pady=12)
        safety_box.columnconfigure(1, weight=1)
        checks = [
            ("Redact likely secrets before returning file contents", self.redact_var),
            ("Block hidden files/folders", self.hidden_var),
            ("Block binary files", self.binary_var),
            ("Allow symlinks", self.symlink_var),
            ("Require local approval for writes", self.approval_var),
        ]
        for i, (text, var) in enumerate(checks):
            ttk.Checkbutton(safety_box, text=text, variable=var).grid(row=i, column=0, columnspan=2, sticky="w", padx=12, pady=4)
        ttk.Label(safety_box, text="Max file bytes").grid(row=5, column=0, sticky="w", padx=12, pady=6)
        ttk.Entry(safety_box, textvariable=self.max_file_var, width=20).grid(row=5, column=1, sticky="w", padx=12, pady=6)
        ttk.Label(safety_box, text="Max scan files").grid(row=6, column=0, sticky="w", padx=12, pady=6)
        ttk.Entry(safety_box, textvariable=self.max_scan_var, width=20).grid(row=6, column=1, sticky="w", padx=12, pady=6)
        ttk.Label(safety_box, text="Max search results").grid(row=7, column=0, sticky="w", padx=12, pady=6)
        ttk.Entry(safety_box, textvariable=self.max_results_var, width=20).grid(row=7, column=1, sticky="w", padx=12, pady=6)

        buttons = ttk.Frame(f)
        buttons.grid(row=row + 1, column=0, columnspan=2, sticky="ew", padx=12, pady=8)
        ttk.Button(buttons, text="Save Settings", command=self.save_from_vars).grid(row=0, column=0, padx=6)
        ttk.Button(buttons, text="Open Config Folder", command=self.open_config_folder).grid(row=0, column=1, padx=6)
        ttk.Button(buttons, text="Reset to Safe Defaults", command=self.apply_safe_inbox_gui).grid(row=0, column=2, padx=6)
        ttk.Button(buttons, text="Fix/Validate URL", command=self.fix_validate_url).grid(row=0, column=3, padx=6)
        ttk.Button(buttons, text="Unsafe URL Help", command=self.unsafe_url_help).grid(row=0, column=4, padx=6)

    def _build_roots_tab(self) -> None:
        f = self.tab_roots
        f.columnconfigure(0, weight=1)
        f.rowconfigure(0, weight=1)
        cols = ("id", "access", "path", "extensions")
        self.roots_tree = ttk.Treeview(f, columns=cols, show="headings", selectmode="browse")
        for c in cols:
            self.roots_tree.heading(c, text=c)
        self.roots_tree.column("id", width=120, stretch=False)
        self.roots_tree.column("access", width=90, stretch=False)
        self.roots_tree.column("path", width=650)
        self.roots_tree.column("extensions", width=250)
        self.roots_tree.grid(row=0, column=0, sticky="nsew", padx=12, pady=12)

        scroll = ttk.Scrollbar(f, command=self.roots_tree.yview)
        self.roots_tree.configure(yscrollcommand=scroll.set)
        scroll.grid(row=0, column=1, sticky="ns", pady=12)

        buttons = ttk.Frame(f)
        buttons.grid(row=1, column=0, columnspan=2, sticky="ew", padx=12, pady=(0, 12))
        ttk.Button(buttons, text="Add Folder", command=self.add_folder_gui).grid(row=0, column=0, padx=5)
        ttk.Button(buttons, text="Remove Selected", command=self.remove_selected_root).grid(row=0, column=1, padx=5)
        ttk.Button(buttons, text="Set Selected Read-Only", command=lambda: self.set_selected_access("read")).grid(row=0, column=2, padx=5)
        ttk.Button(buttons, text="Set Selected Write", command=lambda: self.set_selected_access("write")).grid(row=0, column=3, padx=5)
        ttk.Button(buttons, text="Save", command=self.save_config_only).grid(row=0, column=4, padx=5)

    def _build_server_tab(self) -> None:
        f = self.tab_server
        f.columnconfigure(0, weight=1)
        f.rowconfigure(3, weight=1)

        status = ttk.LabelFrame(f, text="Server")
        status.grid(row=0, column=0, sticky="ew", padx=12, pady=12)
        status.columnconfigure(1, weight=1)
        ttk.Label(status, textvariable=self.status_var).grid(row=0, column=0, columnspan=4, sticky="w", padx=10, pady=8)
        ttk.Button(status, text="Start Server", command=self.start_server).grid(row=1, column=0, padx=6, pady=8)
        ttk.Button(status, text="Stop Server", command=self.stop_server).grid(row=1, column=1, sticky="w", padx=6, pady=8)
        ttk.Button(status, text="Open Health", command=self.open_health).grid(row=1, column=2, padx=6, pady=8)
        ttk.Button(status, text="Detect ngrok Tunnel", command=self.detect_tunnel_gui).grid(row=1, column=3, padx=6, pady=8)
        ttk.Button(status, text="Fix/Validate URL", command=self.fix_validate_url).grid(row=1, column=4, padx=6, pady=8)

        tunnel = ttk.LabelFrame(f, text="ngrok Tunnel — no separate terminal needed")
        tunnel.grid(row=1, column=0, sticky="ew", padx=12, pady=(0, 12))
        tunnel.columnconfigure(1, weight=1)
        ttk.Label(tunnel, textvariable=self.ngrok_status_var).grid(row=0, column=0, columnspan=5, sticky="w", padx=10, pady=(8, 4))
        ttk.Label(tunnel, text="ngrok path").grid(row=1, column=0, sticky="w", padx=10, pady=6)
        ttk.Entry(tunnel, textvariable=self.ngrok_path_var).grid(row=1, column=1, sticky="ew", padx=10, pady=6)
        ttk.Button(tunnel, text="Auto-Find", command=self.find_ngrok_gui).grid(row=1, column=2, padx=6, pady=6)
        ttk.Button(tunnel, text="Choose...", command=self.choose_ngrok_gui).grid(row=1, column=3, padx=6, pady=6)
        ttk.Button(tunnel, text="Download ngrok", command=self.open_ngrok_download).grid(row=1, column=4, padx=6, pady=6)
        ttk.Label(tunnel, text="Auth token").grid(row=2, column=0, sticky="w", padx=10, pady=6)
        ttk.Entry(tunnel, textvariable=self.ngrok_token_var, show="•").grid(row=2, column=1, sticky="ew", padx=10, pady=6)
        ttk.Button(tunnel, text="Save Token to ngrok", command=self.save_ngrok_token).grid(row=2, column=2, padx=6, pady=6)
        ttk.Button(tunnel, text="Start Tunnel", command=self.start_ngrok_tunnel).grid(row=2, column=3, padx=6, pady=6)
        ttk.Button(tunnel, text="Stop Tunnel", command=self.stop_ngrok_tunnel).grid(row=2, column=4, padx=6, pady=6)
        ttk.Label(tunnel, text="After Start Tunnel, the public HTTPS URL is detected and pasted into ChatGPT settings automatically.", wraplength=980).grid(row=3, column=0, columnspan=5, sticky="w", padx=10, pady=(0, 8))

        pairing = ttk.LabelFrame(f, text="Pairing / Auth")
        pairing.grid(row=2, column=0, sticky="ew", padx=12, pady=(0, 12))
        pairing.columnconfigure(1, weight=1)
        ttk.Label(pairing, text="Pairing code").grid(row=0, column=0, sticky="w", padx=10, pady=8)
        ttk.Entry(pairing, textvariable=self.pairing_code_var, font=("TkDefaultFont", 16), state="readonly").grid(row=0, column=1, sticky="ew", padx=10, pady=8)
        ttk.Button(pairing, text="Generate Pairing Code", command=self.generate_pairing_code).grid(row=0, column=2, padx=6, pady=8)
        ttk.Button(pairing, text="Clear Session", command=self.clear_pairing).grid(row=0, column=3, padx=6, pady=8)

        settings_box = ttk.LabelFrame(f, text="Paste these into ChatGPT Developer Mode")
        settings_box.grid(row=3, column=0, sticky="nsew", padx=12, pady=(0, 12))
        settings_box.columnconfigure(0, weight=1)
        settings_box.rowconfigure(0, weight=1)
        self.settings_text = ScrolledText(settings_box, wrap="word", height=16)
        self.settings_text.grid(row=0, column=0, sticky="nsew", padx=10, pady=10)
        btns = ttk.Frame(settings_box)
        btns.grid(row=1, column=0, sticky="ew", padx=10, pady=(0, 10))
        ttk.Button(btns, text="Refresh", command=self.refresh_settings_text).grid(row=0, column=0, padx=5)
        ttk.Button(btns, text="Copy to Clipboard", command=self.copy_settings).grid(row=0, column=1, padx=5)
        ttk.Button(btns, text="Save to Desktop", command=self.save_settings_file).grid(row=0, column=2, padx=5)

    def _build_pending_tab(self) -> None:
        f = self.tab_pending
        f.columnconfigure(0, weight=1)
        f.rowconfigure(0, weight=1)
        cols = ("operation_id", "approved", "committed", "mode", "target_path")
        self.pending_tree = ttk.Treeview(f, columns=cols, show="headings", selectmode="browse")
        for c in cols:
            self.pending_tree.heading(c, text=c)
        self.pending_tree.column("operation_id", width=180, stretch=False)
        self.pending_tree.column("approved", width=90, stretch=False)
        self.pending_tree.column("committed", width=90, stretch=False)
        self.pending_tree.column("mode", width=90, stretch=False)
        self.pending_tree.column("target_path", width=650)
        self.pending_tree.grid(row=0, column=0, sticky="nsew", padx=12, pady=12)
        self.pending_tree.bind("<<TreeviewSelect>>", lambda e: self.show_selected_pending_diff())

        side = ttk.Frame(f)
        side.grid(row=0, column=1, sticky="ns", padx=(0, 12), pady=12)
        ttk.Button(side, text="Refresh", command=self.refresh_pending).grid(row=0, column=0, sticky="ew", pady=4)
        ttk.Button(side, text="Approve", command=self.approve_selected).grid(row=1, column=0, sticky="ew", pady=4)
        ttk.Button(side, text="Reject", command=self.reject_selected).grid(row=2, column=0, sticky="ew", pady=4)
        ttk.Button(side, text="Commit", command=self.commit_selected).grid(row=3, column=0, sticky="ew", pady=4)

        diff_box = ttk.LabelFrame(f, text="Diff preview")
        diff_box.grid(row=1, column=0, columnspan=2, sticky="nsew", padx=12, pady=(0, 12))
        diff_box.columnconfigure(0, weight=1)
        diff_box.rowconfigure(0, weight=1)
        self.diff_text = ScrolledText(diff_box, wrap="none", height=12)
        self.diff_text.grid(row=0, column=0, sticky="nsew", padx=8, pady=8)

    def _build_logs_tab(self) -> None:
        f = self.tab_logs
        f.columnconfigure(0, weight=1)
        f.rowconfigure(0, weight=1)
        self.log_text = ScrolledText(f, wrap="word")
        self.log_text.grid(row=0, column=0, sticky="nsew", padx=12, pady=12)
        btns = ttk.Frame(f)
        btns.grid(row=1, column=0, sticky="ew", padx=12, pady=(0, 12))
        ttk.Button(btns, text="Refresh Audit Log", command=self.refresh_audit_log).grid(row=0, column=0, padx=5)
        ttk.Button(btns, text="Open Config Folder", command=self.open_config_folder).grid(row=0, column=1, padx=5)
        ttk.Button(btns, text="Clear Screen", command=lambda: self.log_text.delete("1.0", "end")).grid(row=0, column=2, padx=5)


    def _preserve_runtime_settings_from_disk(self) -> None:
        """Preserve settings that the older Control Panel does not edit directly.

        This prevents the Control Panel from overwriting settings saved by
        companion panels such as dangerous_settings_gui.py.
        """
        try:
            current = load_config()
            for key in ("dangerous_mode",):
                if key in current:
                    self.cfg[key] = current[key]
        except Exception:
            pass

    def save_from_vars(self) -> None:
        self.cfg.setdefault("server", {}).update({
            "name": self.name_var.get().strip() or "Local Files MCP",
            "description": self.description_var.get().strip(),
            "host": self.host_var.get().strip() or "127.0.0.1",
            "port": int(self.port_var.get().strip() or "8765"),
            "public_url": normalize_public_base_url(self.public_url_var.get()),
            "auth_mode": self.auth_mode_var.get(),
        })
        self.cfg.setdefault("tunnel", {}).update({
            "ngrok_path": self.ngrok_path_var.get().strip(),
        })
        self.cfg.setdefault("safety", {}).update({
            "redact_secrets": bool(self.redact_var.get()),
            "block_hidden_files": bool(self.hidden_var.get()),
            "block_binary_files": bool(self.binary_var.get()),
            "allow_symlinks": bool(self.symlink_var.get()),
            "require_local_approval_for_writes": bool(self.approval_var.get()),
            "max_file_bytes": int(self.max_file_var.get().strip() or "1048576"),
            "max_scan_files": int(self.max_scan_var.get().strip() or "5000"),
            "max_search_results": int(self.max_results_var.get().strip() or "100"),
        })
        self._preserve_runtime_settings_from_disk()
        save_config(self.cfg)
        self.refresh_all()
        self.log("Settings saved. Preserved companion-panel settings.")

    def save_config_only(self) -> None:
        self.save_from_vars()

    def refresh_all(self) -> None:
        self.cfg = load_config()
        self.refresh_roots()
        self.refresh_settings_text()
        self.refresh_pending()
        self.refresh_audit_log()
        self._sync_vars_from_config()

    def _sync_vars_from_config(self) -> None:
        server = self.cfg.get("server", {})
        self.name_var.set(server.get("name", "Local Files MCP"))
        self.description_var.set(server.get("description", ""))
        self.host_var.set(server.get("host", "127.0.0.1"))
        self.port_var.set(str(server.get("port", 8765)))
        self.public_url_var.set(server.get("public_url", ""))
        self.ngrok_path_var.set(self.cfg.get("tunnel", {}).get("ngrok_path", ""))
        self.auth_mode_var.set(server.get("auth_mode", "noauth"))
        safety = self.cfg.get("safety", {})
        self.redact_var.set(bool(safety.get("redact_secrets", True)))
        self.hidden_var.set(bool(safety.get("block_hidden_files", True)))
        self.binary_var.set(bool(safety.get("block_binary_files", True)))
        self.symlink_var.set(bool(safety.get("allow_symlinks", False)))
        self.approval_var.set(bool(safety.get("require_local_approval_for_writes", True)))
        self.max_file_var.set(str(safety.get("max_file_bytes", 1048576)))
        self.max_scan_var.set(str(safety.get("max_scan_files", 5000)))
        self.max_results_var.set(str(safety.get("max_search_results", 100)))

    def apply_safe_inbox_gui(self) -> None:
        self.cfg = default_config()
        apply_safe_inbox(self.cfg)
        save_config(self.cfg)
        self.refresh_all()
        messagebox.showinfo(APP_TITLE, "Safe Inbox configured. Put files in ~/ChatGPT-MCP-Inbox for access.")

    def apply_project_gui(self) -> None:
        path = filedialog.askdirectory(title="Choose project folder")
        if not path:
            return
        write = messagebox.askyesno("Project access", "Allow write preparation in this project? Writes still require local approval.")
        self.cfg = default_config()
        apply_project(self.cfg, path, write=write)
        save_config(self.cfg)
        self.refresh_all()
        messagebox.showinfo(APP_TITLE, "Project folder configured.")

    def apply_home_gui(self) -> None:
        if not messagebox.askyesno("Home read-only", "Use your home folder read-only with deny rules? This may still expose many files."):
            return
        self.cfg = default_config()
        apply_home_read(self.cfg)
        save_config(self.cfg)
        self.refresh_all()
        messagebox.showinfo(APP_TITLE, "Home read-only mode configured.")

    def apply_full_gui(self) -> None:
        phrase = simpledialog.askstring(
            "FULL ACCESS confirmation",
            f"FULL ACCESS exposes your entire disk/root to the MCP and disables deny rules.\n\nType exactly: {DANGER_PHRASE}",
        )
        if phrase != DANGER_PHRASE:
            messagebox.showwarning(APP_TITLE, "Full access cancelled.")
            return
        self.cfg = default_config()
        apply_full_access(self.cfg)
        save_config(self.cfg)
        self.refresh_all()
        messagebox.showwarning(APP_TITLE, "FULL ACCESS enabled. Writes still require local approval.")

    def add_folder_gui(self) -> None:
        path = filedialog.askdirectory(title="Choose folder to allow")
        if not path:
            return
        default_id = Path(path).name.replace(" ", "_").lower() or "folder"
        root_id = simpledialog.askstring("Root id", "Short id for this folder:", initialvalue=default_id)
        if not root_id:
            return
        access = simpledialog.askstring("Access", "Access: metadata, search, read, or write", initialvalue="read") or "read"
        try:
            add_root(self.cfg, root_id=root_id, path=path, access=access)
            save_config(self.cfg)
            self.refresh_all()
        except Exception as e:
            messagebox.showerror(APP_TITLE, str(e))

    def remove_selected_root(self) -> None:
        sel = self.roots_tree.selection()
        if not sel:
            return
        root_id = self.roots_tree.item(sel[0], "values")[0]
        if not messagebox.askyesno("Remove folder", f"Remove root {root_id!r}?"):
            return
        self.cfg["roots"] = [r for r in self.cfg.get("roots", []) if r.get("id") != root_id]
        save_config(self.cfg)
        self.refresh_all()

    def set_selected_access(self, access: str) -> None:
        sel = self.roots_tree.selection()
        if not sel:
            return
        root_id = self.roots_tree.item(sel[0], "values")[0]
        for root in self.cfg.get("roots", []):
            if root.get("id") == root_id:
                root["access"] = access
                root["write_globs"] = ["**/*"] if access == "write" else []
        save_config(self.cfg)
        self.refresh_all()

    def refresh_roots(self) -> None:
        if not hasattr(self, "roots_tree"):
            return
        self.roots_tree.delete(*self.roots_tree.get_children())
        for root in self.cfg.get("roots", []):
            exts = ", ".join(root.get("allow_extensions", [])[:8])
            if len(root.get("allow_extensions", [])) > 8:
                exts += ", ..."
            self.roots_tree.insert("", "end", values=(root.get("id"), root.get("access"), root.get("path"), exts))

    def refresh_settings_text(self) -> None:
        if not hasattr(self, "settings_text"):
            return
        try:
            self.save_from_vars_silent()
        except Exception:
            pass
        text = format_settings(self.cfg)
        s = app_settings(self.cfg)
        text += "\nCopyable fields\n===============\n"
        text += f"Name: {s['name']}\n"
        text += f"Description: {s['description']}\n"
        text += f"MCP URL / Connector URL: {s['connector_url']}\n"
        text += f"Authentication: {s['authentication']}\n"
        self.settings_text.delete("1.0", "end")
        self.settings_text.insert("1.0", text)

    def save_from_vars_silent(self) -> None:
        self.cfg.setdefault("server", {}).update({
            "name": self.name_var.get().strip() or "Local Files MCP",
            "description": self.description_var.get().strip(),
            "host": self.host_var.get().strip() or "127.0.0.1",
            "port": int(self.port_var.get().strip() or "8765"),
            "public_url": normalize_public_base_url(self.public_url_var.get()),
            "auth_mode": self.auth_mode_var.get(),
        })
        self.cfg.setdefault("tunnel", {}).update({
            "ngrok_path": self.ngrok_path_var.get().strip(),
        })
        self.cfg.setdefault("safety", {}).update({
            "redact_secrets": bool(self.redact_var.get()),
            "block_hidden_files": bool(self.hidden_var.get()),
            "block_binary_files": bool(self.binary_var.get()),
            "allow_symlinks": bool(self.symlink_var.get()),
            "require_local_approval_for_writes": bool(self.approval_var.get()),
            "max_file_bytes": int(self.max_file_var.get().strip() or "1048576"),
            "max_scan_files": int(self.max_scan_var.get().strip() or "5000"),
            "max_search_results": int(self.max_results_var.get().strip() or "100"),
        })
        self._preserve_runtime_settings_from_disk()
        save_config(self.cfg)

    def start_server(self) -> None:
        try:
            self.save_from_vars()
        except Exception as e:
            messagebox.showerror(APP_TITLE, f"Could not save settings: {e}")
            return
        if self.server_process and self.server_process.poll() is None:
            messagebox.showinfo(APP_TITLE, "Server is already running.")
            return
        host = self.cfg.get("server", {}).get("host", "127.0.0.1")
        port = str(self.cfg.get("server", {}).get("port", 8765))
        cmd = [sys.executable, "-m", "uvicorn", "local_files_mcp.server:app", "--host", host, "--port", port]
        try:
            self.server_process = subprocess.Popen(
                cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                bufsize=1,
                cwd=str(Path(__file__).resolve().parents[1]),
            )
            self.status_var.set(f"Server running at http://{host}:{port}/mcp")
            threading.Thread(target=self._read_server_output, daemon=True).start()
            self.log("Started server: " + " ".join(cmd))
        except Exception as e:
            messagebox.showerror(APP_TITLE, f"Could not start server: {e}")

    def _read_server_output(self) -> None:
        proc = self.server_process
        if not proc or not proc.stdout:
            return
        for line in proc.stdout:
            self._log_queue.append(line.rstrip())
        self._log_queue.append("Server process exited.")

    def _drain_log_queue(self) -> None:
        while self._log_queue:
            self.log(self._log_queue.pop(0))
        if self.server_process and self.server_process.poll() is not None:
            self.status_var.set("Server stopped")
        self.after(500, self._drain_log_queue)

    def stop_server(self) -> None:
        if self.server_process and self.server_process.poll() is None:
            self.server_process.terminate()
            try:
                self.server_process.wait(timeout=4)
            except subprocess.TimeoutExpired:
                self.server_process.kill()
            self.status_var.set("Server stopped")
            self.log("Server stopped.")
        else:
            self.status_var.set("Server stopped")

    def open_health(self) -> None:
        self.save_from_vars_silent()
        webbrowser.open(base_url(self.cfg).rstrip("/") + "/health")

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
            self.save_from_vars_silent()
            messagebox.showinfo(APP_TITLE, f"Found ngrok:\n{found}")
        else:
            messagebox.showwarning(APP_TITLE, "ngrok was not found on your PATH. Click Download ngrok, install it, then click Auto-Find again — or choose the ngrok binary manually.")

    def choose_ngrok_gui(self) -> None:
        path = filedialog.askopenfilename(title="Choose ngrok executable")
        if path:
            self.ngrok_path_var.set(path)
            self.save_from_vars_silent()

    def open_ngrok_download(self) -> None:
        webbrowser.open("https://ngrok.com/download")

    def save_ngrok_token(self) -> None:
        ngrok = self._ngrok_bin()
        if not ngrok:
            messagebox.showerror(APP_TITLE, "ngrok is not installed or selected. Install ngrok first or choose its executable.")
            return
        token = self.ngrok_token_var.get().strip()
        if not token:
            messagebox.showwarning(APP_TITLE, "Paste your ngrok auth token first. This app does not store it; it passes it to `ngrok config add-authtoken`.")
            return
        try:
            result = subprocess.run([ngrok, "config", "add-authtoken", token], capture_output=True, text=True, timeout=20)
            self.ngrok_token_var.set("")
            if result.returncode == 0:
                messagebox.showinfo(APP_TITLE, "ngrok auth token saved to ngrok's own config. The token field has been cleared.")
                self.log("Saved ngrok auth token using ngrok config add-authtoken.")
            else:
                messagebox.showerror(APP_TITLE, result.stderr or result.stdout or "ngrok returned an error while saving the token.")
        except Exception as e:
            messagebox.showerror(APP_TITLE, f"Could not save ngrok token: {e}")

    def start_ngrok_tunnel(self) -> None:
        if not (self.server_process and self.server_process.poll() is None):
            if messagebox.askyesno(APP_TITLE, "The MCP server is not running. Start it now before opening the tunnel?"):
                self.start_server()
                self.update_idletasks()
                time.sleep(1.0)
            else:
                return
        if self.ngrok_process and self.ngrok_process.poll() is None:
            messagebox.showinfo(APP_TITLE, "ngrok tunnel is already running.")
            return
        ngrok = self._ngrok_bin()
        if not ngrok:
            messagebox.showerror(APP_TITLE, "ngrok is not installed or selected. Click Download ngrok, install it, then come back and click Auto-Find or Choose.")
            return
        port = str(self.cfg.get("server", {}).get("port", 8765))
        cmd = [ngrok, "http", port]
        try:
            self.ngrok_process = subprocess.Popen(
                cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                bufsize=1,
            )
            self.ngrok_status_var.set(f"ngrok tunnel starting for localhost:{port}...")
            threading.Thread(target=self._read_ngrok_output, daemon=True).start()
            self.log("Started ngrok: " + " ".join(cmd))
            self.after(1200, self.detect_tunnel_after_start)
        except Exception as e:
            messagebox.showerror(APP_TITLE, f"Could not start ngrok: {e}")

    def _read_ngrok_output(self) -> None:
        proc = self.ngrok_process
        if not proc or not proc.stdout:
            return
        for line in proc.stdout:
            self._log_queue.append("[ngrok] " + line.rstrip())
        self._log_queue.append("ngrok process exited.")

    def detect_tunnel_after_start(self, attempts: int = 12) -> None:
        url = detect_ngrok()
        if url:
            self.public_url_var.set(url)
            self.save_from_vars_silent()
            self.refresh_settings_text()
            self.ngrok_status_var.set(f"ngrok tunnel running: {url}")
            self.log(f"Detected ngrok public URL: {url}")
            return
        if attempts > 0 and self.ngrok_process and self.ngrok_process.poll() is None:
            self.after(1000, lambda: self.detect_tunnel_after_start(attempts - 1))
            return
        self.ngrok_status_var.set("ngrok started, but no HTTPS URL was detected yet. Click Detect/Validate URL or check the Logs tab.")

    def stop_ngrok_tunnel(self) -> None:
        if self.ngrok_process and self.ngrok_process.poll() is None:
            self.ngrok_process.terminate()
            try:
                self.ngrok_process.wait(timeout=4)
            except subprocess.TimeoutExpired:
                self.ngrok_process.kill()
            self.log("ngrok tunnel stopped.")
        self.ngrok_status_var.set("ngrok tunnel stopped")

    def detect_tunnel_gui(self) -> None:
        url = detect_ngrok()
        if not url:
            messagebox.showwarning(APP_TITLE, "No ngrok tunnel found yet. Use the Start Tunnel button in this GUI. If ngrok is not installed, click Download ngrok or Choose the ngrok executable.")
            return
        self.public_url_var.set(url)
        self.save_from_vars()
        messagebox.showinfo(APP_TITLE, f"Saved public URL:\n{url}")

    def copy_settings(self) -> None:
        self.refresh_settings_text()
        s = app_settings(self.cfg)
        if s.get("url_ready") != "yes":
            messagebox.showwarning(APP_TITLE, "The MCP URL is not ready for ChatGPT yet.\n\n" + s.get("url_status", "Use a public HTTPS /mcp URL."))
        text = self.settings_text.get("1.0", "end").strip()
        self.clipboard_clear()
        self.clipboard_append(text)
        self.log("Copied ChatGPT settings to clipboard.")

    def fix_validate_url(self) -> None:
        raw = self.public_url_var.get()
        cleaned_base = normalize_public_base_url(raw)
        self.public_url_var.set(cleaned_base)
        self.save_from_vars_silent()
        final_url = mcp_url(self.cfg)
        ok, message, corrected = validate_chatgpt_url(final_url)
        if not ok and corrected:
            # If the validator can safely correct the final endpoint, store its base part.
            corrected_base = normalize_public_base_url(corrected)
            if corrected_base and corrected_base != cleaned_base:
                self.public_url_var.set(corrected_base)
                self.save_from_vars_silent()
                final_url = mcp_url(self.cfg)
                ok, message, corrected = validate_chatgpt_url(final_url)
        self.refresh_settings_text()
        if ok:
            messagebox.showinfo(APP_TITLE, "URL looks ready for ChatGPT:\n\n" + final_url)
        else:
            messagebox.showwarning(APP_TITLE, message + "\n\nPaste your tunnel BASE URL in Public HTTPS URL, not localhost and not /mcp/mcp.")

    def unsafe_url_help(self) -> None:
        messagebox.showinfo(
            APP_TITLE,
            "ChatGPT shows 'unsafe URL' when the MCP URL is not a public HTTPS /mcp endpoint.\n\n"
            "Use this format in ChatGPT:\n"
            "https://abc123.ngrok-free.app/mcp\n\n"
            "Do not use:\n"
            "http://127.0.0.1:8765/mcp\n"
            "http://localhost:8765/mcp\n"
            "https://abc123.ngrok-free.app/mcp/mcp\n"
            "private IP addresses\n"
            "self-signed HTTPS URLs\n\n"
            "In this GUI's Public HTTPS URL field, paste only the BASE tunnel URL, e.g. https://abc123.ngrok-free.app. The GUI adds /mcp automatically."
        )

    def save_settings_file(self) -> None:
        self.refresh_settings_text()
        desktop = Path.home() / "Desktop"
        dest = desktop / "ChatGPT_Local_Files_MCP_Settings.txt" if desktop.exists() else Path.cwd() / "ChatGPT_Local_Files_MCP_Settings.txt"
        dest.write_text(self.settings_text.get("1.0", "end"), encoding="utf-8")
        messagebox.showinfo(APP_TITLE, f"Saved settings file:\n{dest}")

    def generate_pairing_code(self) -> None:
        self.save_from_vars_silent()
        ttl = int(self.cfg.get("auth", {}).get("pairing_code_ttl_seconds", 600))
        code = create_pairing_session(ttl)
        self.pairing_code_var.set(code)
        self.clipboard_clear()
        self.clipboard_append(code)
        messagebox.showinfo(APP_TITLE, f"Pairing code copied to clipboard. It expires in {ttl} seconds. Enter it only on the Local Files MCP auth page.")

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
            self.pending_tree.insert("", "end", iid=item.get("operation_id"), values=(
                item.get("operation_id"), item.get("approved"), item.get("committed"), item.get("mode"), item.get("target_path")
            ))
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
        result = approve_operation(op_id)
        self.log(json.dumps(result))
        self.refresh_pending()

    def reject_selected(self) -> None:
        op_id = self.selected_operation_id()
        if not op_id:
            return
        if not messagebox.askyesno("Reject operation", f"Reject and delete pending operation {op_id}?"):
            return
        result = reject_operation(op_id)
        self.log(json.dumps(result))
        self.refresh_pending()

    def commit_selected(self) -> None:
        op_id = self.selected_operation_id()
        if not op_id:
            return
        if not messagebox.askyesno("Commit operation", f"Write this approved operation to disk?\n\n{op_id}"):
            return
        result = commit_operation(load_config(), op_id)
        self.log(json.dumps(result))
        if not result.get("ok"):
            messagebox.showerror(APP_TITLE, result.get("error", "Commit failed"))
        self.refresh_pending()

    def refresh_audit_log(self) -> None:
        if not hasattr(self, "log_text"):
            return
        # Preserve process logs, append audit tail below.
        audit_path = Path(self.cfg.get("audit", {}).get("path", str(Path.home() / ".local-files-mcp" / "audit.jsonl"))).expanduser()
        if not audit_path.exists():
            self.log_text.insert("end", "Audit log not created yet.\n")
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

    def log(self, message: str) -> None:
        if hasattr(self, "log_text"):
            self.log_text.insert("end", f"[{time.strftime('%H:%M:%S')}] {message}\n")
            self.log_text.see("end")

    def on_close(self) -> None:
        if self.ngrok_process and self.ngrok_process.poll() is None:
            self.stop_ngrok_tunnel()
        if self.server_process and self.server_process.poll() is None:
            if messagebox.askyesno(APP_TITLE, "Stop the MCP server and quit?"):
                self.stop_server()
            else:
                return
        self.destroy()


def main() -> None:
    app = LocalFilesMcpGUI()
    app.mainloop()


if __name__ == "__main__":
    main()
