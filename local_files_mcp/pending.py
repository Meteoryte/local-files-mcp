from __future__ import annotations

from pathlib import Path
from typing import Any
import difflib
import json
import secrets
import time

from .paths import PENDING_DIR, ensure_dirs
from .policy import validate
from .audit import audit_event
from .config import (
    dangerous_mode_enabled,
    dangerous_mode_allows,
    direct_write_file_enabled,
    local_write_approval_required,
)


MAX_BATCH_FILES = 25


def _pending_path(operation_id: str) -> Path:
    ensure_dirs()
    safe = operation_id.replace("/", "_")
    return PENDING_DIR / f"{safe}.json"


def _read_before(path: Path) -> str:
    if path.exists() and path.is_file():
        return path.read_text(encoding="utf-8", errors="replace")
    return ""


def _diff(before: str, after: str) -> str:
    return "\n".join(difflib.unified_diff(before.splitlines(), after.splitlines(), fromfile="before", tofile="after", lineterm=""))


def _mode_allowed(cfg: dict[str, Any], mode: str) -> bool:
    if not dangerous_mode_enabled(cfg):
        return True
    if mode == "create":
        return dangerous_mode_allows(cfg, "allow_create")
    if mode == "overwrite":
        return dangerous_mode_allows(cfg, "allow_overwrite")
    return False


def _new_operation_id(prefix: str = "op_") -> str:
    return prefix + secrets.token_urlsafe(12)


def _auto_approved(cfg: dict[str, Any]) -> bool:
    return not local_write_approval_required(cfg)


def _operation_approval_fields(cfg: dict[str, Any]) -> dict[str, Any]:
    auto_approved = _auto_approved(cfg)
    return {
        "approved": bool(auto_approved),
        "approved_at": int(time.time()) if auto_approved else None,
        "approval_source": "dangerous_mode_auto" if auto_approved else "local_gui_required",
    }


def _validate_write_target(cfg: dict[str, Any], path: str, mode: str) -> tuple[dict[str, Any] | None, str | None]:
    if mode not in {"overwrite", "create"}:
        return None, "mode must be overwrite or create"
    if not _mode_allowed(cfg, mode):
        return None, f"Dangerous Mode setting does not allow {mode} writes"

    target_candidate = Path(path).expanduser()
    exists = target_candidate.exists()
    if mode == "create" and exists:
        return None, "File already exists; use overwrite mode to replace it"

    decision = validate(cfg, path, "write", must_exist=(mode == "overwrite" and exists))
    if not decision.allowed:
        return None, decision.reason

    target = Path(decision.resolved_path)
    return {"target": target, "exists": exists}, None


def prepare_write(cfg: dict[str, Any], path: str, content: str, mode: str = "overwrite") -> dict[str, Any]:
    validation, error = _validate_write_target(cfg, path, mode)
    if error:
        audit_event(cfg, "prepare_write_denied", {"path": path, "reason": error})
        return {"ok": False, "error": error}

    target = validation["target"]
    before = _read_before(target)
    diff = _diff(before, content)
    auto_approved = _auto_approved(cfg)
    op_id = _new_operation_id()
    op = {
        "operation_id": op_id,
        "type": "write",
        "target_path": str(target),
        "mode": mode,
        "content": content,
        "diff": diff[:20000],
        "created_at": int(time.time()),
        **_operation_approval_fields(cfg),
        "committed": False,
    }
    _pending_path(op_id).write_text(json.dumps(op, indent=2), encoding="utf-8")
    audit_event(cfg, "prepare_write", {"operation_id": op_id, "target_path": str(target), "auto_approved": auto_approved})
    return {
        "ok": True,
        "operation_id": op_id,
        "target_path": str(target),
        "diff": diff[:20000],
        "approval_required": not auto_approved,
        "auto_approved": auto_approved,
        "dangerous_mode": dangerous_mode_enabled(cfg),
        "next_step": "commit_operation can now write without local GUI approval" if auto_approved else "approve locally in the GUI, then call commit_operation",
    }


def batch_prepare_write(cfg: dict[str, Any], files: list[dict[str, Any]], label: str = "") -> dict[str, Any]:
    """Prepare multiple file writes as one pending operation.

    This is intentionally all-or-nothing at prepare time: if any file is invalid,
    no operation is stored.
    """
    if not isinstance(files, list):
        return {"ok": False, "error": "files must be an array"}
    if not files:
        return {"ok": False, "error": "files must contain at least one item"}
    if len(files) > MAX_BATCH_FILES:
        return {"ok": False, "error": f"batch_prepare_write supports at most {MAX_BATCH_FILES} files"}

    prepared_files: list[dict[str, Any]] = []
    errors: list[dict[str, Any]] = []
    seen_targets: set[str] = set()

    for index, item in enumerate(files):
        if not isinstance(item, dict):
            errors.append({"index": index, "error": "file entry must be an object"})
            continue
        path = str(item.get("path", ""))
        content = str(item.get("content", ""))
        mode = str(item.get("mode", "overwrite"))
        if not path:
            errors.append({"index": index, "error": "path is required"})
            continue

        validation, error = _validate_write_target(cfg, path, mode)
        if error:
            errors.append({"index": index, "path": path, "error": error})
            continue

        target = validation["target"]
        target_key = str(target).lower()
        if target_key in seen_targets:
            errors.append({"index": index, "path": str(target), "error": "duplicate target path in batch"})
            continue
        seen_targets.add(target_key)

        before = _read_before(target)
        diff = _diff(before, content)
        prepared_files.append({
            "index": index,
            "target_path": str(target),
            "mode": mode,
            "content": content,
            "diff": diff[:20000],
        })

    if errors:
        audit_event(cfg, "batch_prepare_write_denied", {"label": label, "errors": errors})
        return {"ok": False, "error": "One or more files failed validation; no batch operation was stored", "errors": errors}

    auto_approved = _auto_approved(cfg)
    op_id = _new_operation_id("op_batch_")
    op = {
        "operation_id": op_id,
        "type": "batch_write",
        "label": str(label or ""),
        "files": prepared_files,
        "file_count": len(prepared_files),
        "created_at": int(time.time()),
        **_operation_approval_fields(cfg),
        "committed": False,
    }
    _pending_path(op_id).write_text(json.dumps(op, indent=2), encoding="utf-8")
    audit_event(cfg, "batch_prepare_write", {"operation_id": op_id, "label": label, "file_count": len(prepared_files), "auto_approved": auto_approved})
    return {
        "ok": True,
        "operation_id": op_id,
        "type": "batch_write",
        "label": str(label or ""),
        "file_count": len(prepared_files),
        "files": [
            {
                "index": f["index"],
                "target_path": f["target_path"],
                "mode": f["mode"],
                "diff": f["diff"],
            }
            for f in prepared_files
        ],
        "approval_required": not auto_approved,
        "auto_approved": auto_approved,
        "dangerous_mode": dangerous_mode_enabled(cfg),
        "next_step": "commit_operation can now write the entire batch" if auto_approved else "approve locally in the GUI, then call commit_operation",
    }


def list_pending() -> list[dict[str, Any]]:
    ensure_dirs()
    items = []
    for p in sorted(PENDING_DIR.glob("op_*.json")):
        try:
            op = json.loads(p.read_text(encoding="utf-8"))
            op_type = op.get("type", "write")
            item = {k: op.get(k) for k in ["operation_id", "type", "target_path", "mode", "created_at", "approved", "committed", "approval_source", "label", "file_count"]}
            if op_type == "batch_write":
                files = op.get("files", []) if isinstance(op.get("files"), list) else []
                item["file_count"] = len(files)
                item["target_paths"] = [str(f.get("target_path", "")) for f in files if isinstance(f, dict)]
                item["diff_preview"] = "\n\n".join(
                    f"--- {f.get('target_path', '')}\n{str(f.get('diff', ''))[:1000]}"
                    for f in files[:3]
                    if isinstance(f, dict)
                )[:3000]
            else:
                item["file_count"] = 1
                item["target_paths"] = [op.get("target_path", "")]
                item["diff_preview"] = op.get("diff", "")[:1000]
            items.append(item)
        except Exception:
            continue
    return items


def list_pending_operations() -> dict[str, Any]:
    items = list_pending()
    return {"ok": True, "pending_operations": items, "count": len(items)}


def approve(operation_id: str) -> dict[str, Any]:
    p = _pending_path(operation_id)
    if not p.exists():
        return {"ok": False, "error": "Unknown operation_id"}
    op = json.loads(p.read_text(encoding="utf-8"))
    op["approved"] = True
    op["approved_at"] = int(time.time())
    op["approval_source"] = "local_gui"
    p.write_text(json.dumps(op, indent=2), encoding="utf-8")
    return {"ok": True, "operation_id": operation_id, "approved": True}


def reject(operation_id: str) -> dict[str, Any]:
    p = _pending_path(operation_id)
    if not p.exists():
        return {"ok": False, "error": "Unknown operation_id"}
    p.unlink()
    return {"ok": True, "operation_id": operation_id, "rejected": True}


def _require_commit_allowed(cfg: dict[str, Any], op: dict[str, Any], operation_id: str) -> str | None:
    if op.get("committed"):
        return "Operation already committed"
    if local_write_approval_required(cfg) and not op.get("approved"):
        return "Local approval required. Approve this operation in the GUI: " + operation_id
    return None


def _commit_single(cfg: dict[str, Any], op: dict[str, Any], operation_id: str) -> dict[str, Any]:
    error = _require_commit_allowed(cfg, op, operation_id)
    if error:
        return {"ok": False, "error": error}
    mode = str(op.get("mode", "overwrite"))
    if not _mode_allowed(cfg, mode):
        return {"ok": False, "error": "Current settings do not allow this write mode"}
    decision = validate(cfg, op["target_path"], "write", must_exist=False)
    if not decision.allowed:
        audit_event(cfg, "commit_denied", {"operation_id": operation_id, "path": op.get("target_path"), "reason": decision.reason})
        return {"ok": False, "error": decision.reason}
    target = Path(decision.resolved_path)
    if mode == "create" and target.exists():
        return {"ok": False, "error": "File already exists; use overwrite mode to replace it"}
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(op.get("content", ""), encoding="utf-8")
    op["committed"] = True
    op["committed_at"] = int(time.time())
    _pending_path(operation_id).write_text(json.dumps(op, indent=2), encoding="utf-8")
    audit_event(cfg, "commit_write", {"operation_id": operation_id, "path": str(target), "dangerous_mode": dangerous_mode_enabled(cfg)})
    return {"ok": True, "operation_id": operation_id, "path": str(target), "committed": True, "dangerous_mode": dangerous_mode_enabled(cfg)}


def _commit_batch(cfg: dict[str, Any], op: dict[str, Any], operation_id: str) -> dict[str, Any]:
    error = _require_commit_allowed(cfg, op, operation_id)
    if error:
        return {"ok": False, "error": error}
    files = op.get("files", [])
    if not isinstance(files, list) or not files:
        return {"ok": False, "error": "Batch operation has no files"}

    validations: list[tuple[Path, dict[str, Any]]] = []
    errors: list[dict[str, Any]] = []
    for index, item in enumerate(files):
        if not isinstance(item, dict):
            errors.append({"index": index, "error": "file entry is invalid"})
            continue
        target_path = str(item.get("target_path", ""))
        mode = str(item.get("mode", "overwrite"))
        if not _mode_allowed(cfg, mode):
            errors.append({"index": index, "path": target_path, "error": "Current settings do not allow this write mode"})
            continue
        decision = validate(cfg, target_path, "write", must_exist=False)
        if not decision.allowed:
            errors.append({"index": index, "path": target_path, "error": decision.reason})
            continue
        target = Path(decision.resolved_path)
        if mode == "create" and target.exists():
            errors.append({"index": index, "path": str(target), "error": "File already exists; use overwrite mode to replace it"})
            continue
        validations.append((target, item))

    if errors:
        audit_event(cfg, "batch_commit_denied", {"operation_id": operation_id, "errors": errors})
        return {"ok": False, "error": "One or more files failed validation at commit time; no files were written", "errors": errors}

    written_paths: list[str] = []
    for target, item in validations:
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(str(item.get("content", "")), encoding="utf-8")
        written_paths.append(str(target))

    op["committed"] = True
    op["committed_at"] = int(time.time())
    _pending_path(operation_id).write_text(json.dumps(op, indent=2), encoding="utf-8")
    audit_event(cfg, "commit_batch_write", {"operation_id": operation_id, "file_count": len(written_paths), "paths": written_paths, "dangerous_mode": dangerous_mode_enabled(cfg)})
    return {
        "ok": True,
        "operation_id": operation_id,
        "type": "batch_write",
        "file_count": len(written_paths),
        "paths": written_paths,
        "committed": True,
        "dangerous_mode": dangerous_mode_enabled(cfg),
    }


def commit(cfg: dict[str, Any], operation_id: str) -> dict[str, Any]:
    p = _pending_path(operation_id)
    if not p.exists():
        return {"ok": False, "error": "Unknown operation_id"}
    op = json.loads(p.read_text(encoding="utf-8"))
    if op.get("type") == "batch_write":
        return _commit_batch(cfg, op, operation_id)
    return _commit_single(cfg, op, operation_id)


def commit_operations(cfg: dict[str, Any], operation_ids: list[str], continue_on_error: bool = False) -> dict[str, Any]:
    if not isinstance(operation_ids, list) or not operation_ids:
        return {"ok": False, "error": "operation_ids must be a non-empty array"}
    results: list[dict[str, Any]] = []
    all_ok = True
    for raw_id in operation_ids:
        operation_id = str(raw_id)
        result = commit(cfg, operation_id)
        results.append({"operation_id": operation_id, "result": result})
        if not result.get("ok"):
            all_ok = False
            if not continue_on_error:
                break
    return {"ok": all_ok, "results": results, "committed_count": sum(1 for item in results if item["result"].get("ok"))}


def write_file(cfg: dict[str, Any], path: str, content: str, mode: str = "overwrite") -> dict[str, Any]:
    if not direct_write_file_enabled(cfg):
        return {"ok": False, "error": "Direct write_file is disabled. Enable it in Dangerous Mode settings or use prepare_write."}

    validation, error = _validate_write_target(cfg, path, mode)
    if error:
        audit_event(cfg, "write_file_denied", {"path": path, "reason": error})
        return {"ok": False, "error": error}

    target = validation["target"]
    before = _read_before(target)
    diff = _diff(before, content)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(content, encoding="utf-8")
    audit_event(cfg, "dangerous_write_file", {"path": str(target), "mode": mode})
    return {
        "ok": True,
        "path": str(target),
        "mode": mode,
        "committed": True,
        "dangerous_mode": dangerous_mode_enabled(cfg),
        "diff": diff[:20000],
    }
