from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Any
import hashlib
import json
import os


def _maybe_hash(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def audit_event(cfg: dict[str, Any], event_type: str, details: dict[str, Any]) -> None:
    audit = cfg.get("audit", {})
    if not audit.get("enabled", True):
        return
    path = Path(os.path.expandvars(os.path.expanduser(audit.get("path", "~/.local-files-mcp/audit.jsonl")))).resolve()
    path.parent.mkdir(parents=True, exist_ok=True)
    safe_details = dict(details)
    if audit.get("hash_paths", False):
        for key in ("path", "resolved_path", "target_path"):
            if key in safe_details and safe_details[key]:
                safe_details[key] = _maybe_hash(str(safe_details[key]))
    row = {"ts": datetime.now(timezone.utc).isoformat(), "type": event_type, "details": safe_details}
    with path.open("a", encoding="utf-8") as f:
        f.write(json.dumps(row, sort_keys=True) + "\n")
