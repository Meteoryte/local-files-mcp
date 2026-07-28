from __future__ import annotations

from pathlib import Path
from typing import Any
import copy
import json
import os
import platform

from .paths import CONFIG_PATH, AUDIT_PATH, ensure_dirs

SAFE_DENY_GLOBS = [
    "**/.env", "**/.env.*", "**/*secret*", "**/*token*", "**/*credential*",
    "**/.ssh/**", "**/.aws/**", "**/.azure/**", "**/.config/gcloud/**",
    "**/.npmrc", "**/.pypirc", "**/id_rsa", "**/id_ed25519",
    "**/Library/Keychains/**", "**/Login Data", "**/Cookies",
    "**/node_modules/**", "**/.git/**", "**/.venv/**", "**/__pycache__/**",
]

DEFAULT_EXTENSIONS = [
    ".txt", ".md", ".mdx", ".json", ".jsonl", ".csv", ".tsv",
    ".py", ".js", ".jsx", ".ts", ".tsx", ".css", ".scss",
    ".html", ".xml", ".yaml", ".yml", ".toml", ".ini", ".cfg",
    ".sql", ".sh", ".zsh", ".bash", ".ps1", ".go", ".rs", ".java",
    ".c", ".cpp", ".h", ".hpp", ".cs", ".php", ".rb", ".swift",
]

USER_SETTINGS_PATH = CONFIG_PATH.parent / "user_settings.json"
CONFIG_BACKUP_PATH = CONFIG_PATH.parent / "config.last-good.json"


def expand(path: str) -> str:
    return str(Path(os.path.expandvars(os.path.expanduser(path))).resolve())


def system_root() -> str:
    if platform.system().lower().startswith("win"):
        return Path.home().anchor or "C:\\"
    return "/"


def env_bool(name: str, default: bool) -> bool:
    value = os.environ.get(name)
    if value is None:
        return default
    return value not in {"0", "false", "False", "no", "No", "off", "OFF"}


def default_dangerous_mode() -> dict[str, Any]:
    return {
        "enabled": False,
        "auto_approve_prepared_writes": False,
        "expose_direct_write_file": False,
        "allow_create": True,
        "allow_overwrite": True,
        "allow_delete": False,
        "allow_move": False,
        "allow_shell": False,
        "warning_acknowledged": False,
    }


def default_config() -> dict[str, Any]:
    return {
        "version": 4,
        "profile": "unconfigured",
        "server": {
            "name": "Local Files MCP",
            "description": "Local document access for folders you explicitly configure. Search/read files; writes require local approval unless Dangerous Mode is enabled.",
            "host": os.environ.get("LOCAL_FILES_MCP_HOST", "127.0.0.1"),
            "port": int(os.environ.get("LOCAL_FILES_MCP_PORT", "8765")),
            "public_url": os.environ.get("LOCAL_FILES_MCP_PUBLIC_URL") or "",
            "auth_mode": os.environ.get("LOCAL_FILES_MCP_AUTH_MODE", "noauth"),
        },
        "auth": {
            "pairing_code_ttl_seconds": int(os.environ.get("LOCAL_FILES_MCP_PAIRING_CODE_TTL_SECONDS", "3600")),
            "authorization_code_ttl_seconds": int(os.environ.get("LOCAL_FILES_MCP_AUTHORIZATION_CODE_TTL_SECONDS", "600")),
            "access_token_ttl_seconds": int(os.environ.get("LOCAL_FILES_MCP_ACCESS_TOKEN_TTL_SECONDS", "2592000")),
            "refresh_token_ttl_seconds": int(os.environ.get("LOCAL_FILES_MCP_REFRESH_TOKEN_TTL_SECONDS", "31536000")),
            "sliding_access_tokens": env_bool("LOCAL_FILES_MCP_SLIDING_ACCESS_TOKENS", True),
            "preserve_tokens_when_pairing": True,
            "require_pkce_when_present": True,
            "token_scopes": ["files:metadata", "files:search", "files:read", "files:write"],
        },
        "safety": {
            "max_file_bytes": 1_048_576,
            "max_search_results": 100,
            "max_scan_files": 5000,
            "allow_symlinks": False,
            "block_hidden_files": True,
            "block_binary_files": True,
            "redact_secrets": True,
            "label_file_content_untrusted": True,
            "require_local_approval_for_writes": True,
            "allow_destructive_tools": False,
        },
        "dangerous_mode": default_dangerous_mode(),
        "tools": {
            "get_mcp_app_settings": True,
            "list_roots": True,
            "list_directory": True,
            "search_files": True,
            "read_file": True,
            "search": True,
            "fetch": True,
            "prepare_write": True,
            "commit_operation": True,
            "write_file": False,
            "delete_file": False,
            "move_file": False,
            "shell": False,
        },
        "global_deny_globs": SAFE_DENY_GLOBS[:],
        "roots": [],
        "audit": {
            "enabled": True,
            "path": str(AUDIT_PATH),
            "log_reads": True,
            "log_searches": True,
            "log_denials": True,
            "hash_paths": False,
        },
        "tunnel": {
            "ngrok_path": "",
        },
    }


def _deep_merge(base: dict[str, Any], override: dict[str, Any]) -> dict[str, Any]:
    result = copy.deepcopy(base)
    for key, value in (override or {}).items():
        if isinstance(value, dict) and isinstance(result.get(key), dict):
            result[key] = _deep_merge(result[key], value)
        else:
            result[key] = copy.deepcopy(value)
    return result


def _stable_user_subset(cfg: dict[str, Any]) -> dict[str, Any]:
    return {
        "version": 4,
        "profile": cfg.get("profile", "unconfigured"),
        "server": cfg.get("server", {}),
        "auth": cfg.get("auth", {}),
        "safety": cfg.get("safety", {}),
        "dangerous_mode": cfg.get("dangerous_mode", default_dangerous_mode()),
        "tools": cfg.get("tools", {}),
        "global_deny_globs": cfg.get("global_deny_globs", []),
        "roots": cfg.get("roots", []),
        "audit": cfg.get("audit", {}),
        "tunnel": cfg.get("tunnel", {}),
    }


def _write_json(path: Path, data: dict[str, Any]) -> None:
    tmp = path.with_suffix(path.suffix + ".tmp")
    with tmp.open("w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, sort_keys=True)
        f.write("\n")
    tmp.replace(path)


def _read_json(path: Path) -> dict[str, Any]:
    with path.open("r", encoding="utf-8") as f:
        return json.load(f)


def _apply_env_overrides(cfg: dict[str, Any]) -> None:
    server = cfg.setdefault("server", {})
    if os.environ.get("LOCAL_FILES_MCP_HOST"):
        server["host"] = os.environ["LOCAL_FILES_MCP_HOST"]
    if os.environ.get("LOCAL_FILES_MCP_PORT"):
        server["port"] = int(os.environ["LOCAL_FILES_MCP_PORT"])
    if os.environ.get("LOCAL_FILES_MCP_PUBLIC_URL"):
        server["public_url"] = os.environ["LOCAL_FILES_MCP_PUBLIC_URL"].rstrip("/")
    if os.environ.get("LOCAL_FILES_MCP_AUTH_MODE"):
        server["auth_mode"] = os.environ["LOCAL_FILES_MCP_AUTH_MODE"]

    auth = cfg.setdefault("auth", {})
    if os.environ.get("LOCAL_FILES_MCP_PAIRING_CODE_TTL_SECONDS"):
        auth["pairing_code_ttl_seconds"] = int(os.environ["LOCAL_FILES_MCP_PAIRING_CODE_TTL_SECONDS"])
    if os.environ.get("LOCAL_FILES_MCP_AUTHORIZATION_CODE_TTL_SECONDS"):
        auth["authorization_code_ttl_seconds"] = int(os.environ["LOCAL_FILES_MCP_AUTHORIZATION_CODE_TTL_SECONDS"])
    if os.environ.get("LOCAL_FILES_MCP_ACCESS_TOKEN_TTL_SECONDS"):
        auth["access_token_ttl_seconds"] = int(os.environ["LOCAL_FILES_MCP_ACCESS_TOKEN_TTL_SECONDS"])
    if os.environ.get("LOCAL_FILES_MCP_REFRESH_TOKEN_TTL_SECONDS"):
        auth["refresh_token_ttl_seconds"] = int(os.environ["LOCAL_FILES_MCP_REFRESH_TOKEN_TTL_SECONDS"])
    if os.environ.get("LOCAL_FILES_MCP_SLIDING_ACCESS_TOKENS"):
        auth["sliding_access_tokens"] = env_bool("LOCAL_FILES_MCP_SLIDING_ACCESS_TOKENS", True)


def _migrate_dangerous_mode(cfg: dict[str, Any]) -> None:
    legacy_requires_approval = bool(cfg.get("safety", {}).get("require_local_approval_for_writes", True))
    legacy_enabled = not legacy_requires_approval
    existing = cfg.get("dangerous_mode")
    if not isinstance(existing, dict):
        existing = {}
    defaults = default_dangerous_mode()
    dm = _deep_merge(defaults, existing)
    if legacy_enabled and existing == {}:
        dm.update({
            "enabled": True,
            "auto_approve_prepared_writes": True,
            "expose_direct_write_file": True,
            "warning_acknowledged": True,
        })
    cfg["dangerous_mode"] = dm


def _normalize_tools_for_safety(cfg: dict[str, Any]) -> None:
    _migrate_dangerous_mode(cfg)
    safety = cfg.setdefault("safety", {})
    tools = cfg.setdefault("tools", {})
    dm = cfg.setdefault("dangerous_mode", default_dangerous_mode())
    enabled = bool(dm.get("enabled", False))
    auto_approve = bool(dm.get("auto_approve_prepared_writes", False)) if enabled else False
    direct_write = bool(dm.get("expose_direct_write_file", False)) if enabled else False

    safety["require_local_approval_for_writes"] = not auto_approve
    tools.setdefault("prepare_write", True)
    tools.setdefault("commit_operation", True)
    tools["write_file"] = direct_write
    tools["delete_file"] = bool(enabled and dm.get("allow_delete", False) and safety.get("allow_destructive_tools", False))
    tools["move_file"] = bool(enabled and dm.get("allow_move", False) and safety.get("allow_destructive_tools", False))
    tools["shell"] = bool(enabled and dm.get("allow_shell", False) and safety.get("allow_destructive_tools", False))


def load_config(path: Path = CONFIG_PATH) -> dict[str, Any]:
    ensure_dirs()
    defaults = default_config()
    disk_cfg: dict[str, Any] = {}
    if path.exists():
        try:
            disk_cfg = _read_json(path)
        except Exception:
            disk_cfg = {}

    user_cfg: dict[str, Any] = {}
    if USER_SETTINGS_PATH.exists():
        try:
            user_cfg = _read_json(USER_SETTINGS_PATH)
        except Exception:
            user_cfg = {}

    if not USER_SETTINGS_PATH.exists() and disk_cfg:
        try:
            seeded = _stable_user_subset(_deep_merge(defaults, disk_cfg))
            _write_json(USER_SETTINGS_PATH, seeded)
            user_cfg = seeded
        except Exception:
            pass

    cfg = _deep_merge(defaults, disk_cfg)
    cfg = _deep_merge(cfg, user_cfg)
    cfg["version"] = max(int(cfg.get("version", 0) or 0), 4)
    _apply_env_overrides(cfg)
    _normalize_tools_for_safety(cfg)
    return cfg


def save_config(cfg: dict[str, Any], path: Path = CONFIG_PATH) -> None:
    ensure_dirs()
    merged = _deep_merge(default_config(), cfg)
    _normalize_tools_for_safety(merged)
    if path.exists():
        try:
            _write_json(CONFIG_BACKUP_PATH, _read_json(path))
        except Exception:
            pass
    _write_json(path, merged)
    _write_json(USER_SETTINGS_PATH, _stable_user_subset(merged))


def root_template(root_id: str, path: str, access: str = "read", full: bool = False) -> dict[str, Any]:
    return {
        "id": root_id,
        "path": expand(path),
        "access": access,
        "recursive": True,
        "allow_extensions": ["*"] if full else DEFAULT_EXTENSIONS[:],
        "deny_globs": [] if full else ["**/.env*", "**/secrets/**", "**/.git/**", "**/node_modules/**"],
        "write_globs": ["**/*"] if access == "write" else [],
        "tags": ["full-access"] if full else [],
    }


def add_root(cfg: dict[str, Any], root_id: str, path: str, access: str = "read", full: bool = False) -> dict[str, Any]:
    if access not in {"none", "metadata", "search", "read", "write"}:
        raise ValueError("access must be none, metadata, search, read, or write")
    roots = cfg.setdefault("roots", [])
    roots[:] = [r for r in roots if r.get("id") != root_id]
    root = root_template(root_id, path, access=access, full=full)
    roots.append(root)
    return root


def _reset_safe_write_mode(cfg: dict[str, Any]) -> None:
    cfg["dangerous_mode"] = default_dangerous_mode()
    cfg.setdefault("safety", {})["require_local_approval_for_writes"] = True
    _normalize_tools_for_safety(cfg)


def apply_safe_inbox(cfg: dict[str, Any]) -> None:
    inbox = Path.home() / "ChatGPT-MCP-Inbox"
    inbox.mkdir(parents=True, exist_ok=True)
    cfg["profile"] = "safe_inbox"
    cfg["roots"] = [root_template("inbox", str(inbox), "read")]
    _reset_safe_write_mode(cfg)


def apply_project(cfg: dict[str, Any], project_path: str, write: bool = False) -> None:
    cfg["profile"] = "project"
    cfg["roots"] = [root_template("project", project_path, "write" if write else "read")]
    _reset_safe_write_mode(cfg)


def apply_home_read(cfg: dict[str, Any]) -> None:
    cfg["profile"] = "home_read"
    cfg["roots"] = [root_template("home", str(Path.home()), "read")]
    cfg.setdefault("safety", {})["max_scan_files"] = 20000
    _reset_safe_write_mode(cfg)


def apply_full_access(cfg: dict[str, Any]) -> None:
    cfg["profile"] = "full_access"
    cfg["roots"] = [root_template("FULL_ACCESS", system_root(), "write", full=True)]
    cfg["global_deny_globs"] = []
    cfg.setdefault("safety", {}).update({
        "max_file_bytes": 25_000_000,
        "max_search_results": 1000,
        "max_scan_files": 250000,
        "allow_symlinks": True,
        "block_hidden_files": False,
        "block_binary_files": False,
        "redact_secrets": False,
        "allow_destructive_tools": False,
    })
    _reset_safe_write_mode(cfg)


def dangerous_mode_enabled(cfg: dict[str, Any]) -> bool:
    _migrate_dangerous_mode(cfg)
    return bool(cfg.get("dangerous_mode", {}).get("enabled", False))


def local_write_approval_required(cfg: dict[str, Any]) -> bool:
    _migrate_dangerous_mode(cfg)
    dm = cfg.get("dangerous_mode", {})
    if bool(dm.get("enabled", False)) and bool(dm.get("auto_approve_prepared_writes", False)):
        return False
    return True


def direct_write_file_enabled(cfg: dict[str, Any]) -> bool:
    _migrate_dangerous_mode(cfg)
    dm = cfg.get("dangerous_mode", {})
    return bool(dm.get("enabled", False) and dm.get("expose_direct_write_file", False))


def dangerous_mode_allows(cfg: dict[str, Any], capability: str) -> bool:
    _migrate_dangerous_mode(cfg)
    dm = cfg.get("dangerous_mode", {})
    if not bool(dm.get("enabled", False)):
        return False
    return bool(dm.get(capability, False))


def set_dangerous_mode(cfg: dict[str, Any], enabled: bool, **options: Any) -> None:
    dm = _deep_merge(default_dangerous_mode(), cfg.get("dangerous_mode", {}))
    dm["enabled"] = bool(enabled)
    if enabled:
        dm["warning_acknowledged"] = bool(options.pop("warning_acknowledged", dm.get("warning_acknowledged", True)))
        dm["auto_approve_prepared_writes"] = bool(options.pop("auto_approve_prepared_writes", dm.get("auto_approve_prepared_writes", True)))
        dm["expose_direct_write_file"] = bool(options.pop("expose_direct_write_file", dm.get("expose_direct_write_file", True)))
    else:
        dm.update(default_dangerous_mode())
    for key, value in options.items():
        if key in dm:
            dm[key] = value
    cfg["dangerous_mode"] = dm
    _normalize_tools_for_safety(cfg)
