from __future__ import annotations

from pathlib import Path
from typing import Any
import json
import re
import shutil
import subprocess

from .audit import audit_event
from .config import dangerous_mode_allows, dangerous_mode_enabled, direct_write_file_enabled
from .policy import validate

MAX_OUTPUT_CHARS = 40000
DEFAULT_TIMEOUT_SECONDS = 180
SAFE_ITEM_RE = re.compile(r"^[A-Za-z0-9@._:/\\-]+$")
SAFE_REGISTRY_RE = re.compile(r"^(@[A-Za-z0-9_.-]+|https?://[A-Za-z0-9._~:/?#\[\]@!$&'()*+,;=%-]+)$")


def _tool_config(cfg: dict[str, Any]) -> dict[str, Any]:
    integrations = cfg.setdefault("integrations", {})
    shadcn = integrations.setdefault("shadcn", {})
    return {
        "enabled": bool(shadcn.get("enabled", True)),
        "command": str(shadcn.get("command", "npx")),
        "package": str(shadcn.get("package", "shadcn@latest")),
        "timeout_seconds": int(shadcn.get("timeout_seconds", DEFAULT_TIMEOUT_SECONDS)),
    }


def _resolve_command(command: str) -> str:
    found = shutil.which(command)
    if found:
        return found
    if command == "npx":
        found = shutil.which("npx.cmd")
        if found:
            return found
    return command


def _cwd_decision(cfg: dict[str, Any], cwd: str, write: bool) -> tuple[bool, str, Path | None, str | None]:
    if not cwd:
        return False, "cwd is required", None, None
    decision = validate(cfg, cwd, "write" if write else "read", must_exist=True)
    if not decision.allowed:
        return False, decision.reason, None, None
    path = Path(decision.resolved_path)
    if not path.is_dir():
        return False, "cwd must be a directory", None, decision.root_id
    return True, "allowed", path, decision.root_id


def _safe_items(items: list[str], *, allow_registry: bool = False) -> tuple[bool, str]:
    if not items:
        return False, "At least one item is required"
    for item in items:
        value = str(item).strip()
        if not value:
            return False, "Empty item is not allowed"
        if value.startswith("-"):
            return False, f"Options are not allowed as items: {value}"
        if allow_registry and not SAFE_REGISTRY_RE.match(value):
            return False, f"Registry must be @name or URL: {value}"
        if not allow_registry and not SAFE_ITEM_RE.match(value):
            return False, f"Unsupported item characters: {value}"
    return True, "ok"


def _run(cfg: dict[str, Any], cwd: Path, args: list[str], action: str) -> dict[str, Any]:
    settings = _tool_config(cfg)
    if not settings["enabled"]:
        return {"ok": False, "error": "shadcn integration is disabled in config.integrations.shadcn.enabled"}
    command = _resolve_command(settings["command"])
    cmd = [command, settings["package"], *args]
    try:
        proc = subprocess.run(
            cmd,
            cwd=str(cwd),
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            timeout=settings["timeout_seconds"],
            shell=False,
        )
    except subprocess.TimeoutExpired as exc:
        audit_event(cfg, "shadcn_timeout", {"action": action, "cwd": str(cwd), "timeout": settings["timeout_seconds"]})
        return {
            "ok": False,
            "error": f"shadcn command timed out after {settings['timeout_seconds']} seconds",
            "stdout": (exc.stdout or "")[:MAX_OUTPUT_CHARS],
            "stderr": (exc.stderr or "")[:MAX_OUTPUT_CHARS],
        }
    except FileNotFoundError:
        return {"ok": False, "error": f"Command not found: {settings['command']}. Install Node/npm or configure integrations.shadcn.command."}
    except Exception as exc:
        return {"ok": False, "error": str(exc)}

    stdout = (proc.stdout or "")[:MAX_OUTPUT_CHARS]
    stderr = (proc.stderr or "")[:MAX_OUTPUT_CHARS]
    audit_event(cfg, "shadcn_command", {"action": action, "cwd": str(cwd), "returncode": proc.returncode})
    result: dict[str, Any] = {
        "ok": proc.returncode == 0,
        "action": action,
        "cwd": str(cwd),
        "command": [settings["command"], settings["package"], *args],
        "returncode": proc.returncode,
        "stdout": stdout,
        "stderr": stderr,
    }
    if stdout.strip().startswith("{") or stdout.strip().startswith("["):
        try:
            result["json"] = json.loads(stdout)
        except Exception:
            pass
    if proc.returncode != 0 and not result.get("error"):
        result["error"] = stderr.strip() or stdout.strip() or f"shadcn exited with code {proc.returncode}"
    return result


def shadcn_info(cfg: dict[str, Any], cwd: str) -> dict[str, Any]:
    ok, reason, path, root_id = _cwd_decision(cfg, cwd, write=False)
    if not ok or path is None:
        return {"ok": False, "error": reason}
    result = _run(cfg, path, ["info", "--json", "--cwd", str(path)], "shadcn_info")
    result["root_id"] = root_id
    return result


def shadcn_search(
    cfg: dict[str, Any],
    cwd: str,
    registries: list[str] | None = None,
    query: str | None = None,
    limit: int = 25,
    offset: int = 0,
) -> dict[str, Any]:
    ok, reason, path, root_id = _cwd_decision(cfg, cwd, write=False)
    if not ok or path is None:
        return {"ok": False, "error": reason}
    regs = registries or ["@shadcn"]
    safe, message = _safe_items([str(r) for r in regs], allow_registry=True)
    if not safe:
        return {"ok": False, "error": message}
    limit = max(1, min(int(limit), 100))
    offset = max(0, int(offset))
    args = ["search", *[str(r) for r in regs], "--cwd", str(path), "--limit", str(limit), "--offset", str(offset)]
    if query:
        args.extend(["--query", str(query)[:200]])
    result = _run(cfg, path, args, "shadcn_search")
    result["root_id"] = root_id
    return result


def shadcn_view(cfg: dict[str, Any], cwd: str, items: list[str]) -> dict[str, Any]:
    ok, reason, path, root_id = _cwd_decision(cfg, cwd, write=False)
    if not ok or path is None:
        return {"ok": False, "error": reason}
    safe, message = _safe_items([str(i) for i in items])
    if not safe:
        return {"ok": False, "error": message}
    result = _run(cfg, path, ["view", *[str(i) for i in items], "--cwd", str(path)], "shadcn_view")
    result["root_id"] = root_id
    return result


def _write_action_allowed(cfg: dict[str, Any], *, overwrite: bool) -> tuple[bool, str]:
    if not dangerous_mode_enabled(cfg):
        return False, "Dangerous Mode must be enabled for shadcn write actions"
    if not direct_write_file_enabled(cfg):
        return False, "Direct write_file exposure must be enabled before shadcn write actions are available"
    if not dangerous_mode_allows(cfg, "allow_create"):
        return False, "Dangerous Mode allow_create must be enabled for shadcn write actions"
    if overwrite and not dangerous_mode_allows(cfg, "allow_overwrite"):
        return False, "Dangerous Mode allow_overwrite must be enabled when overwrite=true"
    return True, "ok"


def shadcn_add(
    cfg: dict[str, Any],
    cwd: str,
    components: list[str],
    overwrite: bool = False,
    dry_run: bool = True,
    yes: bool = True,
) -> dict[str, Any]:
    write = not bool(dry_run)
    ok, reason, path, root_id = _cwd_decision(cfg, cwd, write=write)
    if not ok or path is None:
        return {"ok": False, "error": reason}
    safe, message = _safe_items([str(c) for c in components])
    if not safe:
        return {"ok": False, "error": message}
    if write:
        allowed, message = _write_action_allowed(cfg, overwrite=bool(overwrite))
        if not allowed:
            return {"ok": False, "error": message}
    args = ["add", *[str(c) for c in components], "--cwd", str(path)]
    if yes:
        args.append("--yes")
    if overwrite:
        args.append("--overwrite")
    if dry_run:
        args.append("--dry-run")
    result = _run(cfg, path, args, "shadcn_add_dry_run" if dry_run else "shadcn_add")
    result.update({"root_id": root_id, "dry_run": bool(dry_run), "write_action": write})
    return result


def shadcn_init(
    cfg: dict[str, Any],
    cwd: str,
    defaults: bool = False,
    template: str | None = None,
    base: str | None = None,
    yes: bool = True,
) -> dict[str, Any]:
    ok, reason, path, root_id = _cwd_decision(cfg, cwd, write=True)
    if not ok or path is None:
        return {"ok": False, "error": reason}
    allowed, message = _write_action_allowed(cfg, overwrite=True)
    if not allowed:
        return {"ok": False, "error": message}
    args = ["init", "--cwd", str(path)]
    if yes:
        args.append("--yes")
    if defaults:
        args.append("--defaults")
    if template:
        if template not in {"next", "vite", "start", "react-router", "laravel", "astro"}:
            return {"ok": False, "error": "Unsupported template"}
        args.extend(["--template", template])
    if base:
        if base not in {"radix", "base"}:
            return {"ok": False, "error": "base must be radix or base"}
        args.extend(["--base", base])
    result = _run(cfg, path, args, "shadcn_init")
    result["root_id"] = root_id
    return result
