from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any
import fnmatch
import os


class PolicyError(Exception):
    pass


@dataclass
class Decision:
    allowed: bool
    reason: str
    root_id: str | None = None
    resolved_path: str | None = None


def norm(path: str | Path) -> Path:
    return Path(os.path.expandvars(os.path.expanduser(str(path)))).resolve()


def is_relative_to(child: Path, parent: Path) -> bool:
    try:
        child.relative_to(parent)
        return True
    except ValueError:
        return False


def hidden_part(path: Path) -> bool:
    return any(part.startswith(".") and part not in {".", ".."} for part in path.parts)


def match_any(path: Path, patterns: list[str]) -> bool:
    text = path.as_posix()
    name = path.name
    for pattern in patterns:
        if pattern == "*":
            return True
        if fnmatch.fnmatch(text, pattern) or fnmatch.fnmatch(name, pattern):
            return True
    return False


def looks_binary(path: Path, sample_size: int = 4096) -> bool:
    try:
        with path.open("rb") as f:
            return b"\x00" in f.read(sample_size)
    except OSError:
        return True


def locate_root(cfg: dict[str, Any], requested_path: str | Path) -> tuple[dict[str, Any], Path]:
    p = norm(requested_path)
    roots = sorted(cfg.get("roots", []), key=lambda r: len(str(r.get("path", ""))), reverse=True)
    for root in roots:
        root_path = norm(root["path"])
        if is_relative_to(p, root_path):
            return root, p
    raise PolicyError("Path is outside all configured allowlisted roots")


def validate(cfg: dict[str, Any], requested_path: str | Path, operation: str, must_exist: bool = True) -> Decision:
    try:
        root, p = locate_root(cfg, requested_path)
        safety = cfg.get("safety", {})
        access = root.get("access", "none")
        rank = {"none": 0, "metadata": 1, "search": 2, "read": 3, "write": 4}
        needed = {"metadata": 1, "list": 1, "search": 2, "read": 3, "write": 4, "patch": 4}.get(operation, 3)

        if rank.get(access, 0) < needed:
            raise PolicyError(f"Root access {access!r} does not permit {operation!r}")
        if must_exist and not p.exists():
            raise PolicyError("Path does not exist")
        if p.exists() and p.is_symlink() and not safety.get("allow_symlinks", False):
            raise PolicyError("Symlinks are blocked")
        if safety.get("block_hidden_files", True) and hidden_part(p):
            raise PolicyError("Hidden files/directories are blocked")

        deny = list(cfg.get("global_deny_globs", [])) + list(root.get("deny_globs", []))
        if deny and match_any(p, deny):
            raise PolicyError("Path matches deny rules")

        if p.exists() and p.is_file():
            allowed_ext = set(root.get("allow_extensions") or [])
            if "*" not in allowed_ext and p.suffix not in allowed_ext:
                raise PolicyError(f"Extension {p.suffix!r} is not allowed")
            max_bytes = int(safety.get("max_file_bytes", 1_048_576))
            if p.stat().st_size > max_bytes:
                raise PolicyError(f"File exceeds max_file_bytes ({max_bytes})")
            if safety.get("block_binary_files", True) and looks_binary(p):
                raise PolicyError("Binary files are blocked")

        if operation in {"write", "patch"}:
            if not root.get("write_globs"):
                raise PolicyError("No write_globs configured for this root")
            if not match_any(p, root.get("write_globs", [])):
                raise PolicyError("Path is not allowed by write_globs")

        return Decision(True, "allowed", root.get("id"), str(p))
    except PolicyError as e:
        return Decision(False, str(e), None, str(norm(requested_path)))
