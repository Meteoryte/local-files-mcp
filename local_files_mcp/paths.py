from pathlib import Path
import os

APP_DIR = Path(os.path.expanduser(os.environ.get("LOCAL_FILES_MCP_HOME", "~/.local-files-mcp"))).resolve()
CONFIG_PATH = APP_DIR / "config.json"
SESSION_PATH = APP_DIR / "session.json"
PENDING_DIR = APP_DIR / "pending"
AUDIT_PATH = APP_DIR / "audit.jsonl"


def ensure_dirs() -> None:
    APP_DIR.mkdir(parents=True, exist_ok=True)
    PENDING_DIR.mkdir(parents=True, exist_ok=True)
