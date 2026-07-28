from __future__ import annotations

from pathlib import Path
from typing import Any
from uuid import uuid4
import json
import time

from .paths import APP_DIR, ensure_dirs

WORKFLOW_DIR = APP_DIR / "workflows"
MAX_EVENT_TEXT = 4000


TERMINAL_STATUSES = {"cancelled", "completed", "rejected"}
DESTRUCTIVE_ACTIONS = {"delete_file", "move_file", "shell"}


def _now() -> int:
    return int(time.time())


def _ensure_workflow_dir() -> None:
    ensure_dirs()
    WORKFLOW_DIR.mkdir(parents=True, exist_ok=True)


def _workflow_path(workflow_id: str) -> Path:
    safe = "".join(ch for ch in workflow_id if ch.isalnum() or ch in {"_", "-"})
    return WORKFLOW_DIR / f"{safe}.json"


def _read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")
    tmp.replace(path)


def _list_workflows() -> list[dict[str, Any]]:
    _ensure_workflow_dir()
    items: list[dict[str, Any]] = []
    for path in sorted(WORKFLOW_DIR.glob("*.json"), key=lambda p: p.stat().st_mtime, reverse=True):
        try:
            items.append(_read_json(path))
        except Exception:
            continue
    return items


def _load_workflow(workflow_id: str | None = None, *, require_active: bool = False) -> tuple[dict[str, Any] | None, str | None]:
    _ensure_workflow_dir()
    if workflow_id:
        path = _workflow_path(workflow_id)
        if not path.exists():
            return None, f"Workflow not found: {workflow_id}"
        return _read_json(path), None

    candidates = _list_workflows()
    if require_active:
        candidates = [item for item in candidates if item.get("status") == "approved"]
    if not candidates:
        return None, "No matching workflow found."
    return candidates[0], None


def _save_workflow(workflow: dict[str, Any]) -> None:
    _write_json(_workflow_path(str(workflow["workflow_id"])), workflow)


def _event(kind: str, detail: str, payload: dict[str, Any] | None = None) -> dict[str, Any]:
    text = str(detail or "")[:MAX_EVENT_TEXT]
    return {
        "at": _now(),
        "kind": kind,
        "detail": text,
        "payload": payload or {},
    }


def _clean_string_list(raw: Any) -> list[str]:
    if not isinstance(raw, list):
        return []
    return [str(item).strip() for item in raw if str(item).strip()]


def _summary(workflow: dict[str, Any], *, include_events: bool = False) -> dict[str, Any]:
    budgets = workflow.get("budgets", {})
    usage = workflow.get("usage", {})
    payload = {
        "workflow_id": workflow.get("workflow_id"),
        "name": workflow.get("name"),
        "goal": workflow.get("goal"),
        "status": workflow.get("status"),
        "approved": workflow.get("status") == "approved",
        "created_at": workflow.get("created_at"),
        "approved_at": workflow.get("approved_at"),
        "updated_at": workflow.get("updated_at"),
        "scope": workflow.get("scope", {}),
        "budgets": budgets,
        "usage": usage,
        "remaining": {
            "tool_calls": max(0, int(budgets.get("max_tool_calls", 0)) - int(usage.get("tool_calls", 0))),
            "file_writes": max(0, int(budgets.get("max_file_writes", 0)) - int(usage.get("file_writes", 0))),
        },
        "stop_conditions": workflow.get("stop_conditions", {}),
        "deliverables": workflow.get("deliverables", []),
        "last_event": (workflow.get("events") or [])[-1] if workflow.get("events") else None,
    }
    if include_events:
        payload["events"] = workflow.get("events", [])
    return payload


def workflow_prepare(
    cfg: dict[str, Any],
    *,
    name: str,
    goal: str,
    allowed_roots: list[str] | None = None,
    allowed_actions: list[str] | None = None,
    max_tool_calls: int = 25,
    max_file_writes: int = 10,
    allow_delete: bool = False,
    allow_move: bool = False,
    allow_shell: bool = False,
    stop_on_error: bool = True,
    stop_before_destructive_action: bool = True,
    deliverables: list[str] | None = None,
    notes: str = "",
) -> dict[str, Any]:
    _ensure_workflow_dir()
    clean_name = str(name or "workflow").strip()[:80] or "workflow"
    clean_goal = str(goal or "").strip()
    if not clean_goal:
        return {"ok": False, "error": "workflow_prepare requires a non-empty goal."}

    roots = _clean_string_list(allowed_roots or [])
    actions = _clean_string_list(allowed_actions or [])
    if not actions:
        actions = [
            "list_roots",
            "list_directory",
            "search_files",
            "read_file",
            "batch_read_files",
            "batch_file_status",
            "project_snapshot",
            "batch_search_patterns",
            "prepare_write",
            "batch_prepare_write",
            "batch_replace_text",
            "commit_operation",
            "commit_operations",
            "verify_tool_registered",
        ]

    destructive_requested = {
        "delete_file": bool(allow_delete),
        "move_file": bool(allow_move),
        "shell": bool(allow_shell),
    }
    if stop_before_destructive_action:
        actions = [action for action in actions if action not in DESTRUCTIVE_ACTIONS]

    workflow_id = f"wf_{uuid4().hex[:12]}"
    workflow = {
        "workflow_id": workflow_id,
        "name": clean_name,
        "goal": clean_goal,
        "status": "prepared",
        "created_at": _now(),
        "approved_at": None,
        "updated_at": _now(),
        "scope": {
            "allowed_roots": roots,
            "allowed_actions": actions,
            "destructive_requested": destructive_requested,
            "notes": str(notes or "")[:MAX_EVENT_TEXT],
        },
        "budgets": {
            "max_tool_calls": max(1, min(int(max_tool_calls), 250)),
            "max_file_writes": max(0, min(int(max_file_writes), 100)),
        },
        "usage": {
            "tool_calls": 0,
            "file_writes": 0,
        },
        "stop_conditions": {
            "stop_on_error": bool(stop_on_error),
            "stop_before_destructive_action": bool(stop_before_destructive_action),
            "stop_when_tool_budget_exhausted": True,
            "stop_when_file_write_budget_exhausted": True,
            "stop_when_outside_allowed_roots": bool(roots),
            "stop_when_outside_allowed_actions": bool(actions),
        },
        "deliverables": _clean_string_list(deliverables or []),
        "events": [
            _event(
                "prepared",
                "Workflow prepared. Call workflow_commit once to approve this bounded multi-step scope.",
            )
        ],
    }
    _save_workflow(workflow)
    return {
        "ok": True,
        "workflow": _summary(workflow, include_events=True),
        "next_step": "Call workflow_commit with this workflow_id to approve the bounded workflow.",
    }


def workflow_commit(cfg: dict[str, Any], *, workflow_id: str = "", approval_note: str = "") -> dict[str, Any]:
    workflow, error = _load_workflow(workflow_id or None)
    if error or workflow is None:
        return {"ok": False, "error": error or "Workflow not found."}
    if workflow.get("status") in TERMINAL_STATUSES:
        return {"ok": False, "error": f"Workflow is terminal: {workflow.get('status')}"}
    workflow["status"] = "approved"
    workflow["approved_at"] = _now()
    workflow["updated_at"] = _now()
    workflow.setdefault("events", []).append(_event("approved", approval_note or "Workflow approved."))
    _save_workflow(workflow)
    return {
        "ok": True,
        "workflow": _summary(workflow, include_events=True),
        "message": "Workflow approved. The assistant may continue within this scope until a stop condition is hit.",
    }


def workflow_status(cfg: dict[str, Any], *, workflow_id: str = "", include_events: bool = False) -> dict[str, Any]:
    if workflow_id:
        workflow, error = _load_workflow(workflow_id)
        if error or workflow is None:
            return {"ok": False, "error": error or "Workflow not found."}
        return {"ok": True, "workflow": _summary(workflow, include_events=include_events)}

    workflows = [_summary(item, include_events=False) for item in _list_workflows()]
    return {"ok": True, "workflows": workflows, "count": len(workflows)}


def workflow_cancel(cfg: dict[str, Any], *, workflow_id: str = "", reason: str = "") -> dict[str, Any]:
    workflow, error = _load_workflow(workflow_id or None)
    if error or workflow is None:
        return {"ok": False, "error": error or "Workflow not found."}
    if workflow.get("status") in TERMINAL_STATUSES:
        return {"ok": True, "workflow": _summary(workflow, include_events=True), "message": "Workflow was already terminal."}
    workflow["status"] = "cancelled"
    workflow["updated_at"] = _now()
    workflow.setdefault("events", []).append(_event("cancelled", reason or "Workflow cancelled."))
    _save_workflow(workflow)
    return {"ok": True, "workflow": _summary(workflow, include_events=True)}


def workflow_continue(
    cfg: dict[str, Any],
    *,
    workflow_id: str = "",
    step_summary: str = "",
    tool_calls_used: int = 0,
    file_writes_used: int = 0,
    observed_error: str = "",
    next_action: str = "",
) -> dict[str, Any]:
    workflow, error = _load_workflow(workflow_id or None, require_active=True)
    if error or workflow is None:
        return {"ok": False, "can_continue": False, "error": error or "No approved workflow found."}
    if workflow.get("status") != "approved":
        return {"ok": False, "can_continue": False, "error": f"Workflow status is {workflow.get('status')!r}, not approved."}

    usage = workflow.setdefault("usage", {"tool_calls": 0, "file_writes": 0})
    usage["tool_calls"] = int(usage.get("tool_calls", 0)) + max(0, int(tool_calls_used))
    usage["file_writes"] = int(usage.get("file_writes", 0)) + max(0, int(file_writes_used))
    workflow["updated_at"] = _now()

    payload = {
        "tool_calls_used": max(0, int(tool_calls_used)),
        "file_writes_used": max(0, int(file_writes_used)),
        "next_action": str(next_action or ""),
    }
    if step_summary:
        workflow.setdefault("events", []).append(_event("step", step_summary, payload))
    if observed_error:
        workflow.setdefault("events", []).append(_event("error", observed_error, payload))

    budgets = workflow.get("budgets", {})
    stop_conditions = workflow.get("stop_conditions", {})
    reasons: list[str] = []

    remaining_tool_calls = int(budgets.get("max_tool_calls", 0)) - int(usage.get("tool_calls", 0))
    remaining_file_writes = int(budgets.get("max_file_writes", 0)) - int(usage.get("file_writes", 0))

    if remaining_tool_calls <= 0:
        reasons.append("Tool-call budget exhausted.")
    if remaining_file_writes < 0:
        reasons.append("File-write budget exceeded.")
    if observed_error and stop_conditions.get("stop_on_error", True):
        reasons.append("Observed error and stop_on_error is enabled.")
    if next_action in DESTRUCTIVE_ACTIONS and stop_conditions.get("stop_before_destructive_action", True):
        reasons.append(f"Next action {next_action!r} is destructive and requires a fresh approval.")
    allowed_actions = set(workflow.get("scope", {}).get("allowed_actions", []))
    if next_action and allowed_actions and next_action not in allowed_actions:
        reasons.append(f"Next action {next_action!r} is outside allowed_actions.")

    if reasons:
        workflow["status"] = "paused"
        workflow.setdefault("events", []).append(_event("paused", "Workflow paused: " + " ".join(reasons)))

    _save_workflow(workflow)
    return {
        "ok": not reasons,
        "can_continue": not reasons,
        "pause_reasons": reasons,
        "workflow": _summary(workflow, include_events=False),
        "allowed_actions": workflow.get("scope", {}).get("allowed_actions", []),
        "allowed_roots": workflow.get("scope", {}).get("allowed_roots", []),
        "message": "Continue within the approved workflow scope." if not reasons else "Workflow paused. Ask the operator before continuing.",
    }
