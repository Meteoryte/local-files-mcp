from __future__ import annotations

from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
import json
import os
import re
import subprocess

from .audit import audit_event
from .ops import encode_id
from .pending import batch_prepare_write as pending_batch_prepare_write
from .policy import validate
from .secrets import redact

DEFAULT_EXCLUDE_DIRS = {
    ".git", ".hg", ".svn", "node_modules", "__pycache__", ".venv", "venv",
    "dist", "build", "out", ".next", ".turbo", ".pytest_cache", ".mypy_cache",
}
DEFAULT_TEXT_EXTENSIONS = {
    ".txt", ".md", ".py", ".ts", ".tsx", ".js", ".jsx", ".json", ".yaml", ".yml",
    ".toml", ".ini", ".cfg", ".css", ".scss", ".html", ".xml", ".ps1", ".sh",
    ".bat", ".cmd", ".sql", ".env", ".gitignore",
}
ARCHIVE_NAME_RE = re.compile(r"(backup|backups|archive|archived|old|copy|duplicate|deprecated|bak|tmp|temp|\d{8}|\d{4}-\d{2}-\d{2})", re.IGNORECASE)
SECRET_HINT_RE = re.compile(r"(api[_-]?key|secret|token|password|passwd|credential|private[_-]?key|sk-[A-Za-z0-9]|sk-or-v1)", re.IGNORECASE)


def _root_by_id(cfg: dict[str, Any], root_id: str) -> dict[str, Any] | None:
    return next((r for r in cfg.get("roots", []) if r.get("id") == root_id), None)


def _resolve_under_root(cfg: dict[str, Any], root_id: str, subpath: str = ".") -> tuple[Path | None, str | None]:
    root = _root_by_id(cfg, root_id)
    if not root:
        return None, f"Unknown root_id: {root_id}"
    target = (Path(str(root["path"])) / subpath).resolve()
    decision = validate(cfg, target, "metadata", must_exist=True)
    if not decision.allowed:
        return None, decision.reason
    return Path(decision.resolved_path), None


def _validate_read_path(cfg: dict[str, Any], path: str) -> tuple[Path | None, str | None]:
    decision = validate(cfg, path, "read", must_exist=True)
    if not decision.allowed:
        return None, decision.reason
    p = Path(decision.resolved_path)
    if not p.is_file():
        return None, "Not a file"
    return p, None


def _is_text_candidate(path: Path, include_extensions: list[str] | None = None) -> bool:
    if include_extensions:
        exts = {e.lower() if e.startswith(".") else "." + e.lower() for e in include_extensions}
        return path.suffix.lower() in exts or path.name.lower() in exts
    return path.suffix.lower() in DEFAULT_TEXT_EXTENSIONS or path.name.lower() in {".env", ".gitignore"}


def _iter_files(cfg: dict[str, Any], base: Path, *, max_depth: int = 6, include_extensions: list[str] | None = None, exclude_dirs: list[str] | None = None, max_files: int = 5000) -> list[Path]:
    excludes = set(DEFAULT_EXCLUDE_DIRS)
    excludes.update(exclude_dirs or [])
    base = base.resolve()
    files: list[Path] = []
    for root, dirs, names in os.walk(base):
        root_path = Path(root)
        try:
            depth = len(root_path.relative_to(base).parts)
        except Exception:
            depth = 0
        if depth >= max_depth:
            dirs[:] = []
        dirs[:] = [d for d in dirs if d not in excludes and not d.endswith(".egg-info")]
        for name in names:
            if len(files) >= max_files:
                return files
            p = root_path / name
            if not _is_text_candidate(p, include_extensions):
                continue
            decision = validate(cfg, p, "metadata", must_exist=True)
            if decision.allowed and p.is_file():
                files.append(Path(decision.resolved_path))
    return files


def batch_read_files(cfg: dict[str, Any], paths: list[str], max_chars_per_file: int = 20000) -> dict[str, Any]:
    if not isinstance(paths, list) or not paths:
        return {"ok": False, "error": "paths must be a non-empty array"}
    if len(paths) > 50:
        return {"ok": False, "error": "batch_read_files supports at most 50 files"}
    max_chars = max(100, min(int(max_chars_per_file), 100000))
    results = []
    for raw_path in paths:
        path = str(raw_path)
        p, error = _validate_read_path(cfg, path)
        if error:
            results.append({"path": path, "ok": False, "error": error})
            continue
        try:
            text = p.read_text(encoding="utf-8", errors="replace")
            if cfg.get("safety", {}).get("redact_secrets", True):
                text = redact(text)
            results.append({"path": str(p), "id": encode_id(str(p)), "ok": True, "title": p.name, "size": p.stat().st_size, "text": text[:max_chars], "truncated": len(text) > max_chars})
        except Exception as e:
            results.append({"path": path, "ok": False, "error": str(e)})
    audit_event(cfg, "batch_read_files", {"count": len(results)})
    return {"ok": True, "files": results, "count": len(results)}


def batch_file_status(cfg: dict[str, Any], paths: list[str]) -> dict[str, Any]:
    if not isinstance(paths, list) or not paths:
        return {"ok": False, "error": "paths must be a non-empty array"}
    if len(paths) > 250:
        return {"ok": False, "error": "batch_file_status supports at most 250 paths"}
    results = []
    for raw_path in paths:
        path = str(raw_path)
        decision = validate(cfg, path, "metadata", must_exist=False)
        if not decision.allowed:
            results.append({"path": path, "ok": False, "error": decision.reason})
            continue
        p = Path(decision.resolved_path)
        exists = p.exists()
        item = {"path": str(p), "ok": True, "exists": exists, "type": "directory" if exists and p.is_dir() else "file" if exists and p.is_file() else "missing", "extension": p.suffix.lower(), "name": p.name}
        if exists:
            stat = p.stat()
            item.update({"size": stat.st_size if p.is_file() else None, "modified_at": datetime.fromtimestamp(stat.st_mtime, timezone.utc).isoformat(), "is_text_candidate": p.is_file() and _is_text_candidate(p)})
        results.append(item)
    audit_event(cfg, "batch_file_status", {"count": len(results)})
    return {"ok": True, "items": results, "count": len(results)}


def project_snapshot(cfg: dict[str, Any], root_id: str, subpath: str = ".", max_depth: int = 3, include_extensions: list[str] | None = None, exclude_dirs: list[str] | None = None, max_files: int = 2000) -> dict[str, Any]:
    base, error = _resolve_under_root(cfg, root_id, subpath)
    if error:
        return {"ok": False, "error": error}
    if not base.is_dir():
        return {"ok": False, "error": "Target is not a directory"}
    excludes = set(DEFAULT_EXCLUDE_DIRS)
    excludes.update(exclude_dirs or [])
    tree: list[str] = []
    ext_counts: Counter[str] = Counter()
    important: list[dict[str, Any]] = []
    suspicious: list[dict[str, Any]] = []
    large_files: list[dict[str, Any]] = []
    total_files = 0
    total_dirs = 0
    important_names = {"README.md", "PROJECT.md", "LLM.md", "STATUS.md", "package.json", "pyproject.toml", "requirements.txt", "pnpm-lock.yaml", "package-lock.json", ".env", ".gitignore", "AGENTS.md", "CHANGELOG.md", "ROADMAP.md"}
    for root, dirs, names in os.walk(base):
        root_path = Path(root)
        rel = root_path.relative_to(base)
        depth = len(rel.parts)
        if depth > max_depth:
            dirs[:] = []
            continue
        dirs[:] = [d for d in sorted(dirs) if d not in excludes]
        indent = "  " * depth
        tree.append(f"{base.name}/" if depth == 0 else f"{indent}{root_path.name}/")
        total_dirs += len(dirs)
        for dirname in dirs:
            if ARCHIVE_NAME_RE.search(dirname) or dirname in {"node_modules", "__pycache__", "dist", "out"}:
                suspicious.append({"type": "directory", "path": str(root_path / dirname), "reason": "archive/cache/build-looking directory"})
        shown = 0
        for name in sorted(names):
            p = root_path / name
            decision = validate(cfg, p, "metadata", must_exist=True)
            if not decision.allowed or not p.is_file():
                continue
            total_files += 1
            ext_counts[p.suffix.lower() or "[no_ext]"] += 1
            if shown < 40 and depth <= max_depth:
                tree.append(f"{indent}  {name}")
                shown += 1
            stat = p.stat()
            if stat.st_size > 1_000_000:
                large_files.append({"path": str(p), "size": stat.st_size})
            if name in important_names:
                important.append({"name": name, "path": str(p), "size": stat.st_size})
            if name.lower() in {"nul", ".env"} or SECRET_HINT_RE.search(name):
                suspicious.append({"type": "file", "path": str(p), "reason": "sensitive or suspicious filename"})
        if total_files >= max_files:
            break
    audit_event(cfg, "project_snapshot", {"path": str(base), "files": total_files})
    return {"ok": True, "root_id": root_id, "path": str(base), "max_depth": max_depth, "tree": tree[:1000], "file_count": total_files, "directory_count": total_dirs, "extension_counts": dict(ext_counts.most_common()), "important_files": important[:100], "large_files": large_files[:100], "suspicious_items": suspicious[:100]}


def batch_search_patterns(cfg: dict[str, Any], root_id: str, patterns: list[str], subpath: str = ".", include_extensions: list[str] | None = None, exclude_dirs: list[str] | None = None, regex: bool = False, max_results_per_pattern: int = 50, max_files: int = 5000) -> dict[str, Any]:
    base, error = _resolve_under_root(cfg, root_id, subpath)
    if error:
        return {"ok": False, "error": error}
    if not isinstance(patterns, list) or not patterns:
        return {"ok": False, "error": "patterns must be a non-empty array"}
    if len(patterns) > 50:
        return {"ok": False, "error": "At most 50 patterns are supported"}
    files = _iter_files(cfg, base, include_extensions=include_extensions, exclude_dirs=exclude_dirs, max_files=max_files)
    results = {str(p): [] for p in patterns}
    if regex:
        searchers = []
        for pat in patterns:
            try:
                searchers.append((str(pat), re.compile(str(pat), re.IGNORECASE)))
            except Exception as e:
                results[str(pat)].append({"ok": False, "error": f"invalid regex: {e}"})
    else:
        searchers = [(str(pat), None) for pat in patterns]
    for path in files:
        try:
            lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
        except Exception:
            continue
        for pat, rx in searchers:
            current = results.setdefault(pat, [])
            if len(current) >= max_results_per_pattern:
                continue
            for line_no, line in enumerate(lines, start=1):
                matched = bool(rx.search(line)) if rx else pat.lower() in line.lower()
                if matched:
                    snippet = redact(line.strip()) if cfg.get("safety", {}).get("redact_secrets", True) else line.strip()
                    current.append({"path": str(path), "line": line_no, "snippet": snippet[:500]})
                    if len(current) >= max_results_per_pattern:
                        break
    audit_event(cfg, "batch_search_patterns", {"root_id": root_id, "patterns": len(patterns), "files": len(files)})
    return {"ok": True, "root_id": root_id, "path": str(base), "scanned_files": len(files), "results": results}


def detect_archive_candidates(cfg: dict[str, Any], root_id: str, subpath: str = ".", max_depth: int = 2, max_items: int = 200) -> dict[str, Any]:
    base, error = _resolve_under_root(cfg, root_id, subpath)
    if error:
        return {"ok": False, "error": error}
    candidates = []
    for root, dirs, names in os.walk(base):
        root_path = Path(root)
        try:
            depth = len(root_path.relative_to(base).parts)
        except Exception:
            depth = 0
        if depth >= max_depth:
            dirs[:] = []
        for name in sorted(dirs + names):
            if len(candidates) >= max_items:
                break
            p = root_path / name
            reason = ""
            if ARCHIVE_NAME_RE.search(name):
                reason = "backup/archive/dated/copy-looking name"
            elif name in {"node_modules", "__pycache__", "dist", "out", ".pytest_cache"}:
                reason = "cache/build artifact directory"
            elif name.lower() == "nul":
                reason = "suspicious Windows nul file"
            if reason:
                decision = validate(cfg, p, "metadata", must_exist=True)
                if decision.allowed:
                    candidates.append({"path": str(Path(decision.resolved_path)), "name": name, "type": "directory" if Path(decision.resolved_path).is_dir() else "file", "reason": reason})
    audit_event(cfg, "detect_archive_candidates", {"path": str(base), "count": len(candidates)})
    return {"ok": True, "path": str(base), "candidates": candidates, "count": len(candidates)}


def audit_project_structure(cfg: dict[str, Any], root_id: str, subpath: str = ".", profile: str = "generic") -> dict[str, Any]:
    base, error = _resolve_under_root(cfg, root_id, subpath)
    if error:
        return {"ok": False, "error": error}
    if not base.is_dir():
        return {"ok": False, "error": "Target is not a directory"}
    def exists(rel: str) -> bool:
        return (base / rel).exists()
    checks = [
        {"id": "readme", "label": "Has README.md", "passed": exists("README.md")},
        {"id": "project_md", "label": "Has PROJECT.md", "passed": exists("PROJECT.md")},
        {"id": "llm_md", "label": "Has LLM.md", "passed": exists("LLM.md")},
        {"id": "status_md", "label": "Has STATUS.md", "passed": exists("STATUS.md")},
        {"id": "brainn_dir", "label": "Has .brainn/", "passed": exists(".brainn")},
        {"id": "tests", "label": "Has tests/", "passed": exists("tests") or exists("test")},
        {"id": "docs", "label": "Has docs/", "passed": exists("docs")},
        {"id": "gitignore", "label": "Has .gitignore", "passed": exists(".gitignore")},
    ]
    package_markers = [m for m in ["package.json", "pyproject.toml", "requirements.txt", "pnpm-lock.yaml", "tsconfig.json"] if exists(m)]
    checks.append({"id": "build_markers", "label": "Has project/package markers", "passed": bool(package_markers), "detail": package_markers})
    suspicious = detect_archive_candidates(cfg, root_id=root_id, subpath=subpath, max_depth=2, max_items=100)
    secret_hits = batch_search_patterns(cfg, root_id=root_id, subpath=subpath, patterns=["apiKey", "sk-or-v1", "password", "secret", "token"], include_extensions=[".md", ".py", ".ts", ".tsx", ".js", ".json", ".yaml", ".yml", ".env"], max_results_per_pattern=10, max_files=1000)
    checks.append({"id": "no_secret_hits", "label": "No obvious secret-like strings", "passed": not any(secret_hits.get("results", {}).get(k) for k in secret_hits.get("results", {}))})
    passed = sum(1 for c in checks if c.get("passed"))
    score = round((passed / len(checks)) * 10, 2) if checks else 0
    recommendations = []
    if not exists("PROJECT.md"):
        recommendations.append("Add PROJECT.md")
    if not exists("LLM.md"):
        recommendations.append("Add LLM.md")
    if not exists("STATUS.md"):
        recommendations.append("Add STATUS.md")
    if suspicious.get("candidates"):
        recommendations.append("Review archive/cache/backup candidates")
    audit_event(cfg, "audit_project_structure", {"path": str(base), "score": score})
    return {"ok": True, "path": str(base), "profile": profile, "score_out_of_10": score, "checks": checks, "package_markers": package_markers, "archive_candidates": suspicious.get("candidates", [])[:50], "secret_pattern_hits": secret_hits.get("results", {}), "recommendations": recommendations}


def _classify_project_dir(path: Path) -> dict[str, Any]:
    markers = [m for m in ["README.md", "PROJECT.md", "LLM.md", "STATUS.md", "package.json", "pyproject.toml", "requirements.txt", "tsconfig.json", ".git"] if (path / m).exists()]
    lower_name = path.name.lower()
    if "package.json" in markers:
        kind = "node/typescript"
    elif "pyproject.toml" in markers or "requirements.txt" in markers:
        kind = "python"
    elif any(x in lower_name for x in ["backup", "archive", "old"]):
        kind = "backup/archive"
    else:
        kind = "folder/unknown"
    backup_like = bool(ARCHIVE_NAME_RE.search(path.name))
    return {"name": path.name, "path": str(path), "likely_type": kind, "markers": markers, "backup_like": backup_like, "status_guess": "Backed Up" if backup_like else "Unknown", "priority_guess": "P4" if backup_like else "Unknown", "next_action": "Archive/index after review" if backup_like else "Audit project structure"}


def generate_project_inventory(cfg: dict[str, Any], root_id: str, subpath: str = ".", depth: int = 1, include_files: bool = False) -> dict[str, Any]:
    base, error = _resolve_under_root(cfg, root_id, subpath)
    if error:
        return {"ok": False, "error": error}
    if not base.is_dir():
        return {"ok": False, "error": "Target is not a directory"}
    rows = []
    for child in sorted(base.iterdir(), key=lambda p: (not p.is_dir(), p.name.lower())):
        decision = validate(cfg, child, "metadata", must_exist=True)
        if not decision.allowed:
            continue
        p = Path(decision.resolved_path)
        if p.is_dir():
            rows.append(_classify_project_dir(p))
        elif include_files:
            rows.append({"name": p.name, "path": str(p), "likely_type": "file", "markers": [p.suffix.lower() or "[no_ext]"], "backup_like": bool(ARCHIVE_NAME_RE.search(p.name)), "status_guess": "Unknown", "priority_guess": "Unknown", "next_action": "Classify root file"})
    audit_event(cfg, "generate_project_inventory", {"path": str(base), "count": len(rows)})
    return {"ok": True, "path": str(base), "rows": rows, "count": len(rows)}


def batch_replace_text(cfg: dict[str, Any], replacements: list[dict[str, Any]], label: str = "batch_replace_text") -> dict[str, Any]:
    """Prepare ordered text replacements across up to 25 replacement specs.

    Multiple replacement specs may target the same file. Replacements are applied
    in input order against an in-memory copy of that file, then the final content
    is sent to pending.batch_prepare_write once per unique target path. This
    avoids pending.py's intentional duplicate-target protection while preserving
    atomic all-or-nothing validation for the whole replacement batch.
    """
    if not isinstance(replacements, list) or not replacements:
        return {"ok": False, "error": "replacements must be a non-empty array"}
    if len(replacements) > 25:
        return {"ok": False, "error": "At most 25 replacements are supported"}

    errors: list[dict[str, Any]] = []
    grouped: dict[str, dict[str, Any]] = {}

    for index, item in enumerate(replacements):
        path = str(item.get("path", ""))
        find = str(item.get("find", ""))
        replace = str(item.get("replace", ""))
        if not path or find == "":
            errors.append({"index": index, "path": path, "error": "path and find are required"})
            continue

        p, error = _validate_read_path(cfg, path)
        if error:
            errors.append({"index": index, "path": path, "error": error})
            continue

        resolved = str(p)
        if resolved not in grouped:
            try:
                grouped[resolved] = {
                    "path": resolved,
                    "content": p.read_text(encoding="utf-8", errors="replace"),
                    "replacement_count": 0,
                    "spec_indexes": [],
                }
            except Exception as e:
                errors.append({"index": index, "path": resolved, "error": str(e)})
                continue

        current = str(grouped[resolved]["content"])
        count = int(item.get("count", 0) or 0)
        available = current.count(find)
        if available <= 0:
            errors.append({
                "index": index,
                "path": resolved,
                "error": "find text not found after applying earlier replacements for this file",
            })
            continue

        applied = min(available, count) if count > 0 else available
        grouped[resolved]["content"] = current.replace(find, replace, count if count > 0 else -1)
        grouped[resolved]["replacement_count"] = int(grouped[resolved]["replacement_count"]) + applied
        grouped[resolved]["spec_indexes"].append(index)

    if errors:
        return {"ok": False, "error": "One or more replacements failed; no batch prepared", "errors": errors}

    files = [
        {"path": item["path"], "content": item["content"], "mode": "overwrite"}
        for item in grouped.values()
    ]
    result = pending_batch_prepare_write(cfg, files=files, label=label)
    if isinstance(result, dict):
        result["replacement_summary"] = [
            {
                "path": item["path"],
                "replacement_count": item["replacement_count"],
                "spec_indexes": item["spec_indexes"],
            }
            for item in grouped.values()
        ]
    return result


def prepare_project_scaffold(cfg: dict[str, Any], project_path: str, profile: str = "generic", overwrite: bool = False) -> dict[str, Any]:
    decision = validate(cfg, project_path, "metadata", must_exist=True)
    if not decision.allowed:
        return {"ok": False, "error": decision.reason}
    base = Path(decision.resolved_path)
    if not base.is_dir():
        return {"ok": False, "error": "project_path must be a directory"}
    project_name = base.name
    today = datetime.now(timezone.utc).date().isoformat()
    templates = {
        "PROJECT.md": f"# {project_name}\n\n## Purpose\n\nTBD.\n\n## Status\n\nUnknown.\n\n## Stack/Profile\n\n{profile}\n\n## Current Next Action\n\nAudit and classify this project.\n",
        "LLM.md": f"# LLM Instructions — {project_name}\n\n- Read `PROJECT.md` and `STATUS.md` before making changes.\n- Do not expose secrets or credentials.\n- Prefer small, reviewable changes.\n- Update `STATUS.md` after meaningful work.\n",
        "STATUS.md": f"# Status — {project_name}\n\n**Last reviewed:** {today}\n\n## Current State\n\nUnknown / pending audit.\n\n## Next Actions\n\n- [ ] Complete project audit.\n- [ ] Register in Home Base project registry.\n",
        ".brainn/project.json": json.dumps({"name": project_name, "profile": profile, "created_at": today, "home_base_imported": False}, indent=2) + "\n",
    }
    files = []
    skipped = []
    for rel, content in templates.items():
        path = base / rel
        if path.exists() and not overwrite:
            skipped.append(str(path))
            continue
        files.append({"path": str(path), "content": content, "mode": "overwrite" if overwrite and path.exists() else "create"})
    if not files:
        return {"ok": True, "message": "All scaffold files already exist", "skipped": skipped, "prepared": False}
    result = pending_batch_prepare_write(cfg, files=files, label=f"Project scaffold: {project_name}")
    result["skipped"] = skipped
    return result


def git_status(cfg: dict[str, Any], cwd: str, include_diff_stat: bool = True, timeout_seconds: int = 30) -> dict[str, Any]:
    decision = validate(cfg, cwd, "metadata", must_exist=True)
    if not decision.allowed:
        return {"ok": False, "error": decision.reason}
    path = Path(decision.resolved_path)
    if not path.is_dir():
        return {"ok": False, "error": "cwd must be a directory"}
    timeout = max(1, min(int(timeout_seconds), 120))
    try:
        status = subprocess.run(["git", "status", "--short", "--branch"], cwd=str(path), capture_output=True, text=True, timeout=timeout, shell=False)
        result = {"ok": status.returncode == 0, "cwd": str(path), "status_returncode": status.returncode, "status_stdout": status.stdout[-20000:], "status_stderr": status.stderr[-4000:]}
        if include_diff_stat:
            diff = subprocess.run(["git", "diff", "--stat"], cwd=str(path), capture_output=True, text=True, timeout=timeout, shell=False)
            result.update({"diff_returncode": diff.returncode, "diff_stdout": diff.stdout[-20000:], "diff_stderr": diff.stderr[-4000:]})
        audit_event(cfg, "git_status", {"cwd": str(path), "ok": result["ok"]})
        return result
    except FileNotFoundError:
        return {"ok": False, "error": "git executable not found"}
    except Exception as e:
        return {"ok": False, "error": str(e)}


def mcp_self_check(cfg: dict[str, Any], include_smoke_paths: bool = False) -> dict[str, Any]:
    package_dir = Path(__file__).resolve().parent
    server = package_dir / "server.py"
    pending = package_dir / "pending.py"
    server_text = server.read_text(encoding="utf-8", errors="replace") if server.exists() else ""
    pending_text = pending.read_text(encoding="utf-8", errors="replace") if pending.exists() else ""
    expected_tools = ["batch_prepare_write", "list_pending_operations", "commit_operations", "batch_read_files", "batch_file_status", "project_snapshot", "batch_search_patterns", "audit_project_structure", "generate_project_inventory", "batch_replace_text", "detect_archive_candidates", "prepare_project_scaffold", "git_status", "mcp_self_check"]
    checks = []
    for name in expected_tools:
        checks.append({"tool": name, "defined_or_imported": name in server_text or name in pending_text, "registered_in_server": f'"name": "{name}"' in server_text, "routed_in_server": f'name == "{name}"' in server_text})
    roots = [{"id": r.get("id"), "path": r.get("path"), "access": r.get("access")} for r in cfg.get("roots", [])]
    return {"ok": True, "package_dir": str(package_dir), "server_py": str(server), "pending_py": str(pending), "server_version_line": next((line.strip() for line in server_text.splitlines() if line.startswith("SERVER_VERSION")), ""), "tools": checks, "roots": roots, "dangerous_mode": cfg.get("dangerous_mode", {})}


def list_artifacts(cfg: dict[str, Any], root_id: str, subpath: str = ".", extensions: list[str] | None = None, limit: int = 100) -> dict[str, Any]:
    base, error = _resolve_under_root(cfg, root_id, subpath)
    if error:
        return {"ok": False, "error": error}
    exts = extensions or [".md", ".txt", ".json", ".jsonl", ".log"]
    files = _iter_files(cfg, base, max_depth=6, include_extensions=exts, max_files=max(100, int(limit) * 10))
    items = []
    for p in sorted(files, key=lambda x: x.stat().st_mtime, reverse=True)[: max(1, min(int(limit), 500))]:
        stat = p.stat()
        items.append({"path": str(p), "name": p.name, "size": stat.st_size, "modified_at": datetime.fromtimestamp(stat.st_mtime, timezone.utc).isoformat()})
    return {"ok": True, "path": str(base), "artifacts": items, "count": len(items)}


def read_latest_report(cfg: dict[str, Any], root_id: str, subpath: str = ".", name_contains: str = "REPORT", max_chars: int = 40000) -> dict[str, Any]:
    listing = list_artifacts(cfg, root_id=root_id, subpath=subpath, extensions=[".md", ".txt", ".json"], limit=250)
    if not listing.get("ok"):
        return listing
    needle = name_contains.lower()
    candidates = [item for item in listing.get("artifacts", []) if needle in item.get("name", "").lower()]
    if not candidates:
        return {"ok": False, "error": "No matching report found", "path": listing.get("path")}
    latest = candidates[0]
    return batch_read_files(cfg, [latest["path"]], max_chars_per_file=max_chars)
