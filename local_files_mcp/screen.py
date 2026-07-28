from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Any
import base64
import io
import json
import platform
import time

from .paths import APP_DIR, ensure_dirs

SCREEN_DIR = APP_DIR / "screenshots"
LATEST_METADATA_PATH = SCREEN_DIR / "latest.json"
ANNOTATED_METADATA_PATH = SCREEN_DIR / "annotated_latest.json"


class ScreenPolicyError(Exception):
    pass


def _now_stamp() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")


def _ensure_screen_dir() -> None:
    ensure_dirs()
    SCREEN_DIR.mkdir(parents=True, exist_ok=True)


def _screen_cfg(cfg: dict[str, Any]) -> dict[str, Any]:
    integrations = cfg.setdefault("integrations", {})
    screen = integrations.setdefault("screen", {})
    return {
        "enabled": bool(screen.get("enabled", False)),
        "privacy_acknowledged": bool(screen.get("privacy_acknowledged", False)),
        "allow_full_screen": bool(screen.get("allow_full_screen", False)),
        "allow_active_window": bool(screen.get("allow_active_window", True)),
        "allow_window_capture": bool(screen.get("allow_window_capture", True)),
        "save_captures": bool(screen.get("save_captures", True)),
        "retention_latest_only": bool(screen.get("retention_latest_only", True)),
        "max_width": int(screen.get("max_width", 1920)),
        "jpeg_quality": int(screen.get("jpeg_quality", 85)),
    }


def _require_screen_enabled(cfg: dict[str, Any], capability: str) -> dict[str, Any]:
    sc = _screen_cfg(cfg)
    if not sc["enabled"]:
        raise ScreenPolicyError("Screen tools are disabled. Set integrations.screen.enabled=true in the local MCP config/UI to use them.")
    if not sc["privacy_acknowledged"]:
        raise ScreenPolicyError("Screen privacy warning has not been acknowledged. Set integrations.screen.privacy_acknowledged=true after reviewing the warning.")
    if capability == "full" and not sc["allow_full_screen"]:
        raise ScreenPolicyError("Full-screen capture is disabled. Enable integrations.screen.allow_full_screen=true to use screen_capture_once.")
    if capability == "active" and not sc["allow_active_window"]:
        raise ScreenPolicyError("Active-window capture is disabled.")
    if capability == "window" and not sc["allow_window_capture"]:
        raise ScreenPolicyError("Specific-window capture is disabled.")
    return sc


def _redact_title(title: str, max_len: int = 180) -> str:
    # Window titles are metadata, but can still contain sensitive document names.
    # Keep them useful while avoiding huge title dumps.
    return str(title or "")[:max_len]


def _windows_windows() -> list[dict[str, Any]]:
    """List visible top-level windows on Windows using ctypes only."""
    if platform.system().lower() != "windows":
        return []

    import ctypes
    from ctypes import wintypes

    user32 = ctypes.windll.user32
    psapi = ctypes.windll.psapi
    kernel32 = ctypes.windll.kernel32

    EnumWindows = user32.EnumWindows
    EnumWindowsProc = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
    IsWindowVisible = user32.IsWindowVisible
    GetWindowTextLengthW = user32.GetWindowTextLengthW
    GetWindowTextW = user32.GetWindowTextW
    GetWindowThreadProcessId = user32.GetWindowThreadProcessId
    GetWindowRect = user32.GetWindowRect

    PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
    PROCESS_VM_READ = 0x0010
    windows: list[dict[str, Any]] = []

    class RECT(ctypes.Structure):
        _fields_ = [("left", ctypes.c_long), ("top", ctypes.c_long), ("right", ctypes.c_long), ("bottom", ctypes.c_long)]

    def _process_name(pid: int) -> str:
        handle = kernel32.OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION | PROCESS_VM_READ, False, pid)
        if not handle:
            return ""
        try:
            buffer = ctypes.create_unicode_buffer(1024)
            size = wintypes.DWORD(len(buffer))
            if psapi.GetModuleBaseNameW(handle, None, buffer, size):
                return buffer.value
        finally:
            kernel32.CloseHandle(handle)
        return ""

    def callback(hwnd: int, lparam: int) -> bool:
        if not IsWindowVisible(hwnd):
            return True
        length = GetWindowTextLengthW(hwnd)
        if length <= 0:
            return True
        buf = ctypes.create_unicode_buffer(length + 1)
        GetWindowTextW(hwnd, buf, length + 1)
        title = buf.value.strip()
        if not title:
            return True
        rect = RECT()
        if not GetWindowRect(hwnd, ctypes.byref(rect)):
            return True
        width = int(rect.right - rect.left)
        height = int(rect.bottom - rect.top)
        if width <= 0 or height <= 0:
            return True
        pid = wintypes.DWORD()
        GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
        windows.append({
            "window_id": str(int(hwnd)),
            "title": _redact_title(title),
            "process_id": int(pid.value),
            "process_name": _process_name(int(pid.value)),
            "bounds": {"left": int(rect.left), "top": int(rect.top), "right": int(rect.right), "bottom": int(rect.bottom), "width": width, "height": height},
        })
        return True

    EnumWindows(EnumWindowsProc(callback), 0)
    return windows


def _active_window_windows() -> dict[str, Any] | None:
    if platform.system().lower() != "windows":
        return None
    import ctypes
    hwnd = int(ctypes.windll.user32.GetForegroundWindow())
    if not hwnd:
        return None
    for item in _windows_windows():
        if str(item.get("window_id")) == str(hwnd):
            return item
    return {"window_id": str(hwnd), "title": "", "process_id": None, "process_name": "", "bounds": None}


def _load_imagegrab():
    try:
        from PIL import ImageGrab  # type: ignore
        return ImageGrab, None
    except Exception as e:
        return None, str(e)


def _resize_if_needed(image: Any, max_width: int) -> Any:
    try:
        width, height = image.size
        if max_width > 0 and width > max_width:
            ratio = max_width / float(width)
            new_size = (max_width, max(1, int(height * ratio)))
            return image.resize(new_size)
    except Exception:
        pass
    return image


def _cleanup_old_captures(path_to_keep: Path) -> None:
    for path in SCREEN_DIR.glob("screen_*.jpg"):
        if path.resolve() != path_to_keep.resolve():
            try:
                path.unlink()
            except Exception:
                pass


def _save_capture(image: Any, kind: str, metadata: dict[str, Any], settings: dict[str, Any]) -> dict[str, Any]:
    _ensure_screen_dir()
    image = _resize_if_needed(image, int(settings.get("max_width", 1920)))
    out_path = SCREEN_DIR / f"screen_{kind}_{_now_stamp()}_{int(time.time() * 1000) % 100000}.jpg"
    image.save(out_path, format="JPEG", quality=max(1, min(int(settings.get("jpeg_quality", 85)), 95)))
    if settings.get("retention_latest_only", True):
        _cleanup_old_captures(out_path)
    payload = {
        "ok": True,
        "capture_kind": kind,
        "path": str(out_path),
        "metadata_path": str(LATEST_METADATA_PATH),
        "created_at": datetime.now(timezone.utc).isoformat(),
        "image": {
            "width": int(getattr(image, "size", [0, 0])[0]),
            "height": int(getattr(image, "size", [0, 0])[1]),
            "format": "JPEG",
        },
        "metadata": metadata,
        "privacy_note": "Screenshot is stored locally. Review before sharing or reading it through other tools.",
    }
    LATEST_METADATA_PATH.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    return payload


def screen_list_windows(cfg: dict[str, Any], include_empty_titles: bool = False) -> dict[str, Any]:
    try:
        _require_screen_enabled(cfg, "list")
    except ScreenPolicyError as e:
        return {"ok": False, "error": str(e)}
    windows = _windows_windows()
    if not include_empty_titles:
        windows = [item for item in windows if str(item.get("title", "")).strip()]
    return {
        "ok": True,
        "platform": platform.system(),
        "windows": windows,
        "count": len(windows),
        "privacy_note": "Window titles can contain sensitive document names. Titles are truncated but not otherwise redacted.",
    }


def _grab_image(ImageGrab: Any, bbox: tuple[int, int, int, int] | None = None) -> Any:
    """Grab screen pixels with Windows multi-monitor support.

    On Windows, secondary monitors can have negative coordinates. Pillow's
    ImageGrab needs all_screens=True for those bounds to return real pixels
    instead of a black/empty capture on some setups.
    """
    if platform.system().lower() == "windows":
        try:
            return ImageGrab.grab(bbox=bbox, all_screens=True)
        except TypeError:
            return ImageGrab.grab(bbox=bbox)
    return ImageGrab.grab(bbox=bbox)


def screen_capture_once(cfg: dict[str, Any]) -> dict[str, Any]:
    try:
        settings = _require_screen_enabled(cfg, "full")
    except ScreenPolicyError as e:
        return {"ok": False, "error": str(e)}
    ImageGrab, error = _load_imagegrab()
    if error:
        return {"ok": False, "error": f"Pillow ImageGrab is unavailable: {error}"}
    image = _grab_image(ImageGrab)
    return _save_capture(image, "full", {"scope": "full_screen", "platform": platform.system(), "all_screens": platform.system().lower() == "windows"}, settings)


def screen_capture_active_window(cfg: dict[str, Any]) -> dict[str, Any]:
    try:
        settings = _require_screen_enabled(cfg, "active")
    except ScreenPolicyError as e:
        return {"ok": False, "error": str(e)}
    active = _active_window_windows()
    if not active or not active.get("bounds"):
        return {"ok": False, "error": "Could not determine active window bounds on this platform."}
    return _capture_bounds(settings, active["bounds"], "active_window", {"window": active})


def screen_capture_window(cfg: dict[str, Any], window_id: str) -> dict[str, Any]:
    try:
        settings = _require_screen_enabled(cfg, "window")
    except ScreenPolicyError as e:
        return {"ok": False, "error": str(e)}
    wanted = str(window_id or "").strip()
    if not wanted:
        return {"ok": False, "error": "window_id is required. Call screen_list_windows first."}
    for item in _windows_windows():
        if str(item.get("window_id")) == wanted:
            return _capture_bounds(settings, item.get("bounds"), "window", {"window": item})
    return {"ok": False, "error": f"Window not found: {wanted}"}


def _capture_bounds(settings: dict[str, Any], bounds: dict[str, Any] | None, kind: str, metadata: dict[str, Any]) -> dict[str, Any]:
    if not bounds:
        return {"ok": False, "error": "Window bounds are unavailable."}
    ImageGrab, error = _load_imagegrab()
    if error:
        return {"ok": False, "error": f"Pillow ImageGrab is unavailable: {error}"}
    left = int(bounds.get("left", 0))
    top = int(bounds.get("top", 0))
    right = int(bounds.get("right", 0))
    bottom = int(bounds.get("bottom", 0))
    if right <= left or bottom <= top:
        return {"ok": False, "error": "Invalid window bounds."}
    image = _grab_image(ImageGrab, bbox=(left, top, right, bottom))
    metadata = {**metadata, "scope": kind, "platform": platform.system(), "bounds": bounds, "all_screens": platform.system().lower() == "windows"}
    return _save_capture(image, kind, metadata, settings)


def _save_capture_batch_member(image: Any, kind: str, metadata: dict[str, Any], settings: dict[str, Any], index: int) -> dict[str, Any]:
    """Save one member of a batch capture. Writes a per-capture sidecar JSON, does NOT touch latest.json or run cleanup."""
    _ensure_screen_dir()
    image = _resize_if_needed(image, int(settings.get("max_width", 1920)))
    out_path = SCREEN_DIR / f"screen_{kind}_{_now_stamp()}_{int(time.time() * 1000) % 100000}_{index}.jpg"
    image.save(out_path, format="JPEG", quality=max(1, min(int(settings.get("jpeg_quality", 85)), 95)))
    payload = {
        "ok": True,
        "capture_kind": kind,
        "path": str(out_path),
        "metadata_path": str(out_path.with_suffix(".json")),
        "created_at": datetime.now(timezone.utc).isoformat(),
        "image": {
            "width": int(getattr(image, "size", [0, 0])[0]),
            "height": int(getattr(image, "size", [0, 0])[1]),
            "format": "JPEG",
        },
        "metadata": metadata,
        "privacy_note": "Batch screenshot is stored locally. Inspect bytes to verify content before annotating; call screen_select_latest to promote one to the active frame.",
    }
    out_path.with_suffix(".json").write_text(json.dumps(payload, indent=2), encoding="utf-8")
    return payload


def screen_capture_windows(
    cfg: dict[str, Any],
    window_ids: list[str] | None = None,
    title_contains: str | None = None,
    process_name: str | None = None,
    all_windows: bool = False,
    include_empty_titles: bool = False,
    max_captures: int = 12,
) -> dict[str, Any]:
    """Capture multiple candidate windows in one call.

    Use when several windows could be the intended target (e.g., a multi-monitor / multi-pane app
    where window title alone does not pin down which contains the wanted content). The assistant
    inspects each capture, then calls screen_select_latest with the chosen path before annotating
    or exporting.

    Selection precedence: explicit window_ids > title_contains/process_name filter > all_windows.
    """
    try:
        settings = _require_screen_enabled(cfg, "window")
    except ScreenPolicyError as e:
        return {"ok": False, "error": str(e)}

    available = _windows_windows()
    if not include_empty_titles:
        available = [w for w in available if str(w.get("title", "")).strip()]

    if window_ids:
        wanted = {str(w).strip() for w in window_ids if str(w).strip()}
        candidates = [w for w in available if str(w.get("window_id")) in wanted]
        missing = sorted(wanted - {str(w.get("window_id")) for w in candidates})
    elif title_contains or process_name:
        title_needle = (title_contains or "").strip().lower()
        proc_needle = (process_name or "").strip().lower()
        candidates = [
            w for w in available
            if (not title_needle or title_needle in str(w.get("title", "")).lower())
            and (not proc_needle or proc_needle in str(w.get("process_name", "")).lower())
        ]
        missing = []
    elif all_windows:
        candidates = list(available)
        missing = []
    else:
        return {"ok": False, "error": "Provide window_ids, title_contains/process_name, or all_windows=true."}

    if not candidates:
        return {"ok": False, "error": "No windows matched the selection.", "missing_window_ids": missing}

    cap = max(1, min(int(max_captures), 24))
    if len(candidates) > cap:
        truncated = candidates[cap:]
        candidates = candidates[:cap]
    else:
        truncated = []

    ImageGrab, error = _load_imagegrab()
    if error:
        return {"ok": False, "error": f"Pillow ImageGrab is unavailable: {error}"}

    captures: list[dict[str, Any]] = []
    errors: list[dict[str, Any]] = []
    for index, window in enumerate(candidates):
        bounds = window.get("bounds") or {}
        left = int(bounds.get("left", 0))
        top = int(bounds.get("top", 0))
        right = int(bounds.get("right", 0))
        bottom = int(bounds.get("bottom", 0))
        if right <= left or bottom <= top:
            errors.append({"window_id": window.get("window_id"), "title": window.get("title"), "error": "Invalid window bounds."})
            continue
        try:
            image = _grab_image(ImageGrab, bbox=(left, top, right, bottom))
        except Exception as e:
            errors.append({"window_id": window.get("window_id"), "title": window.get("title"), "error": f"Capture failed: {e}"})
            continue
        metadata = {
            "scope": "window_batch",
            "platform": platform.system(),
            "bounds": bounds,
            "all_screens": platform.system().lower() == "windows",
            "window": window,
        }
        saved = _save_capture_batch_member(image, "window_batch", metadata, settings, index)
        if saved.get("ok"):
            captures.append({
                "window_id": window.get("window_id"),
                "title": window.get("title"),
                "process_name": window.get("process_name"),
                "bounds": bounds,
                "path": saved.get("path"),
                "metadata_path": saved.get("metadata_path"),
                "image": saved.get("image"),
            })
        else:
            errors.append({"window_id": window.get("window_id"), "title": window.get("title"), "error": saved.get("error")})

    return {
        "ok": True,
        "captures": captures,
        "count": len(captures),
        "errors": errors,
        "missing_window_ids": missing,
        "truncated": [{"window_id": w.get("window_id"), "title": w.get("title")} for w in truncated],
        "next_step": "Inspect each capture's pixels (not just titles). Call screen_select_latest with the chosen capture path to make it the active frame for annotation/export.",
        "privacy_note": "Each capture is stored locally with a sidecar JSON. Old batch captures will be cleared on the next single screen_capture_* call when retention_latest_only is true.",
    }


def screen_select_latest(cfg: dict[str, Any], capture_path: str) -> dict[str, Any]:
    """Promote one capture from a batch (by path) to be the active 'latest' frame for annotation/export."""
    try:
        _require_screen_enabled(cfg, "list")
    except ScreenPolicyError as e:
        return {"ok": False, "error": str(e)}
    if not capture_path:
        return {"ok": False, "error": "capture_path is required (use a path returned by screen_capture_windows)."}
    target = Path(capture_path)
    if not target.exists() or not target.is_file():
        return {"ok": False, "error": f"Capture file does not exist: {target}"}
    try:
        target_resolved = target.resolve()
        screen_dir_resolved = SCREEN_DIR.resolve()
        target_resolved.relative_to(screen_dir_resolved)
    except Exception:
        return {"ok": False, "error": f"Capture path is outside the screenshots directory: {target}"}
    sidecar = target.with_suffix(".json")
    if not sidecar.exists():
        return {"ok": False, "error": f"Sidecar metadata not found for capture: {sidecar}"}
    try:
        payload = json.loads(sidecar.read_text(encoding="utf-8"))
    except Exception as e:
        return {"ok": False, "error": f"Could not read sidecar metadata: {e}"}
    payload["ok"] = True
    payload["selected_at"] = datetime.now(timezone.utc).isoformat()
    payload["privacy_note"] = "This capture is now the active latest frame. screen_annotate_latest_image and screen_export_latest_image will operate on it."
    LATEST_METADATA_PATH.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    return payload


def screen_get_latest_frame(cfg: dict[str, Any]) -> dict[str, Any]:
    try:
        _require_screen_enabled(cfg, "list")
    except ScreenPolicyError as e:
        return {"ok": False, "error": str(e)}
    if not LATEST_METADATA_PATH.exists():
        return {"ok": False, "error": "No approved screen capture exists yet."}
    try:
        payload = json.loads(LATEST_METADATA_PATH.read_text(encoding="utf-8"))
    except Exception as e:
        return {"ok": False, "error": str(e)}
    payload["ok"] = True
    payload["privacy_note"] = "Latest screenshot metadata only. Use the returned local path intentionally if you need to inspect the image."
    return payload


def _export_image_payload(
    path: Path,
    image_payload: dict[str, Any],
    metadata: dict[str, Any],
    *,
    include_data_url: bool,
    max_bytes: int,
    thumbnail_max_width: int = 0,
    summary_only: bool = False,
    suggested_filename: str,
    privacy_note: str,
    extra: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Return a bounded screenshot payload, optionally downscaled or metadata-only."""
    if not path.exists() or not path.is_file():
        return {"ok": False, "error": f"Screenshot file does not exist: {path}"}

    original_size = path.stat().st_size
    raw = path.read_bytes()
    mime = "image/jpeg" if path.suffix.lower() in {".jpg", ".jpeg"} else "application/octet-stream"
    filename = path.name
    image_out = dict(image_payload or {})
    thumb_width = max(0, min(int(thumbnail_max_width or 0), 4096))

    if thumb_width > 0:
        try:
            from PIL import Image  # type: ignore
            with Image.open(path) as source_image:
                source_image = source_image.convert("RGB")
                source_width, source_height = source_image.size
                if source_width > thumb_width:
                    ratio = thumb_width / float(source_width)
                    source_image = source_image.resize((thumb_width, max(1, int(source_height * ratio))))
                buffer = io.BytesIO()
                source_image.save(buffer, format="JPEG", quality=80)
                raw = buffer.getvalue()
                width, height = source_image.size
            mime = "image/jpeg"
            filename = f"{path.stem}_preview_{width}.jpg"
            image_out = {
                "width": width,
                "height": height,
                "format": "JPEG",
                "source_width": int((image_payload or {}).get("width", 0) or source_width),
                "source_height": int((image_payload or {}).get("height", 0) or source_height),
                "thumbnail_max_width": thumb_width,
            }
        except Exception as e:
            return {"ok": False, "error": f"Could not create screenshot thumbnail export: {e}", "path": str(path), "original_size": original_size}

    size = len(raw)
    limit = max(1, min(int(max_bytes), 20_000_000))
    if size > limit:
        return {"ok": False, "error": f"Screenshot export is {size} bytes, above max_bytes={limit}.", "path": str(path), "size": size, "original_size": original_size, "thumbnail_max_width": thumb_width}

    base_result: dict[str, Any] = {
        "ok": True,
        "path": str(path),
        "filename": filename,
        "suggested_filename": suggested_filename,
        "size": size,
        "original_size": original_size,
        "mime_type": mime,
        "image": image_out,
        "metadata": metadata,
        "privacy_note": privacy_note,
        "usage_note": "Use thumbnail_max_width for a smaller inline preview, or summary_only=true to verify transport fields without returning screenshot pixels.",
    }
    if extra:
        base_result.update(extra)

    if bool(summary_only):
        base_result.update({
            "data_base64_present": True,
            "data_base64_length": ((len(raw) + 2) // 3) * 4,
            "base64_present": True,
            "data_url_present": bool(include_data_url),
            "payload_note": "summary_only=true omits data_base64/base64/data_url so the tool result stays small.",
        })
        return base_result

    encoded = base64.b64encode(raw).decode("ascii")
    base_result["data_base64"] = encoded
    base_result["base64"] = encoded
    if include_data_url:
        base_result["data_url"] = f"data:{mime};base64,{encoded}"
    return base_result


def screen_export_latest_image(
    cfg: dict[str, Any],
    include_data_url: bool = True,
    max_bytes: int = 5_000_000,
    thumbnail_max_width: int = 0,
    summary_only: bool = False,
) -> dict[str, Any]:
    """Return the latest approved screenshot bytes as base64 for inline display/use."""
    try:
        _require_screen_enabled(cfg, "list")
    except ScreenPolicyError as e:
        return {"ok": False, "error": str(e)}
    meta = screen_get_latest_frame(cfg)
    if not meta.get("ok"):
        return meta
    path = Path(str(meta.get("path", "")))
    return _export_image_payload(
        path,
        meta.get("image", {}),
        meta.get("metadata", {}),
        include_data_url=include_data_url,
        max_bytes=max_bytes,
        thumbnail_max_width=thumbnail_max_width,
        summary_only=summary_only,
        suggested_filename="latest-screen.jpg",
        privacy_note="Base64 contains the screenshot pixels unless summary_only=true. Share/display intentionally. One-shot export: if the caller cannot display this payload, it should not retry this same frame export in a loop.",
    )


def _safe_artifact_filename(name: str, default: str) -> str:
    """Return a conservative filename suitable for /mnt/data artifacts."""
    raw = str(name or "").strip() or default
    raw = raw.replace("\\", "_").replace("/", "_").replace(":", "_")
    safe = "".join(ch if ch.isalnum() or ch in {"-", "_", "."} else "_" for ch in raw)
    safe = safe.strip("._") or default
    if not safe.lower().endswith((".jpg", ".jpeg", ".png", ".webp")):
        safe += ".jpg"
    return safe[:180]


def _artifact_code_from_export(exported: dict[str, Any], artifact_filename: str, default_filename: str) -> dict[str, Any]:
    """Convert an export payload into copy-ready Python that writes /mnt/data.

    MCP cannot directly write ChatGPT sandbox files. This bridge gives the
    assistant a deterministic python_user_visible snippet containing the image
    bytes. The assistant should execute that snippet, then return the sandbox
    link it prints/creates.
    """
    if not exported.get("ok"):
        return exported
    encoded = str(exported.get("data_base64") or exported.get("base64") or "")
    if not encoded:
        return {"ok": False, "error": "Export did not include data_base64/base64; cannot build ChatGPT artifact bridge code.", "source": exported}
    filename = _safe_artifact_filename(artifact_filename, default_filename)
    sandbox_path = f"/mnt/data/{filename}"
    sandbox_link = f"sandbox:{sandbox_path}"
    code = (
        "from pathlib import Path\n"
        "import base64\n\n"
        f"out = Path({sandbox_path!r})\n"
        f"data = base64.b64decode({encoded!r})\n"
        "out.write_bytes(data)\n"
        "print(f'Wrote {out} ({len(data)} bytes)')\n"
        "out.as_posix()\n"
    )
    summary = dict(exported)
    for key in ("data_base64", "base64", "data_url"):
        summary.pop(key, None)
    summary.update({
        "ok": True,
        "artifact_filename": filename,
        "sandbox_path": sandbox_path,
        "sandbox_link": sandbox_link,
        "python_user_visible_code": code,
        "workflow": [
            "Run python_user_visible.exec with python_user_visible_code exactly once.",
            f"Return [Open image]({sandbox_link}) or embed ![image]({sandbox_link}).",
            "Do not use MCP HTTP/ngrok URLs for this final display path.",
        ],
        "bridge_note": "This is the ChatGPT artifact bridge: MCP returns bytes as Python code; ChatGPT Python writes /mnt/data; final response uses sandbox:/mnt/data link.",
    })
    return summary



def screen_export_latest_artifact_code(
    cfg: dict[str, Any],
    artifact_filename: str = "latest-screen.jpg",
    max_bytes: int = 5_000_000,
    thumbnail_max_width: int = 0,
) -> dict[str, Any]:
    """Return Python code that writes the latest screenshot into ChatGPT /mnt/data."""
    exported = screen_export_latest_image(
        cfg,
        include_data_url=False,
        max_bytes=max_bytes,
        thumbnail_max_width=thumbnail_max_width,
        summary_only=False,
    )
    return _artifact_code_from_export(exported, artifact_filename, "latest-screen.jpg")



def screen_annotate_latest_image(cfg: dict[str, Any], marks: list[dict[str, Any]] | None = None) -> dict[str, Any]:
    """Create an annotated copy of the latest approved screenshot.

    Marks are simple local overlays: rectangles and labels. Coordinates are
    normalized 0..1 relative to image size unless values are larger than 1,
    in which case they are treated as pixels.
    """
    try:
        _require_screen_enabled(cfg, "list")
    except ScreenPolicyError as e:
        return {"ok": False, "error": str(e)}
    meta = screen_get_latest_frame(cfg)
    if not meta.get("ok"):
        return meta
    source = Path(str(meta.get("path", "")))
    if not source.exists() or not source.is_file():
        return {"ok": False, "error": f"Latest screenshot file does not exist: {source}"}
    try:
        from PIL import Image, ImageDraw, ImageFont  # type: ignore
    except Exception as e:
        return {"ok": False, "error": f"Pillow drawing support is unavailable: {e}"}

    image = Image.open(source).convert("RGB")
    width, height = image.size
    draw = ImageDraw.Draw(image)
    try:
        font = ImageFont.truetype("arial.ttf", max(18, width // 90))
        small_font = ImageFont.truetype("arial.ttf", max(14, width // 120))
    except Exception:
        font = ImageFont.load_default()
        small_font = ImageFont.load_default()

    default_marks = [
        {"kind": "rect", "x1": 0.00, "y1": 0.00, "x2": 1.00, "y2": 0.08, "label": "Browser tabs / current active window", "color": "orange"},
        {"kind": "rect", "x1": 0.00, "y1": 0.08, "x2": 0.14, "y2": 1.00, "label": "Chat sidebar", "color": "cyan"},
        {"kind": "rect", "x1": 0.36, "y1": 0.09, "x2": 0.77, "y2": 0.47, "label": "Conversation content area", "color": "lime"},
        {"kind": "rect", "x1": 0.36, "y1": 0.87, "x2": 0.77, "y2": 0.97, "label": "Message composer / Developer Mode", "color": "red"},
    ]
    palette = {
        "red": (255, 70, 70),
        "orange": (255, 170, 40),
        "yellow": (255, 230, 70),
        "lime": (120, 255, 120),
        "cyan": (60, 220, 255),
        "blue": (90, 150, 255),
        "white": (255, 255, 255),
    }

    def coord(value: Any, max_value: int) -> int:
        v = float(value)
        if -1.0 <= v <= 1.0:
            return int(v * max_value)
        return int(v)

    applied = []
    for item in (marks if isinstance(marks, list) and marks else default_marks):
        try:
            color = palette.get(str(item.get("color", "orange")).lower(), palette["orange"])
            x1 = coord(item.get("x1", 0), width)
            y1 = coord(item.get("y1", 0), height)
            x2 = coord(item.get("x2", width), width)
            y2 = coord(item.get("y2", height), height)
            if x2 < x1:
                x1, x2 = x2, x1
            if y2 < y1:
                y1, y2 = y2, y1
            label = str(item.get("label", "mark"))[:80]
            line_width = max(3, width // 450)
            draw.rectangle((x1, y1, x2, y2), outline=color, width=line_width)
            label_x = max(0, min(x1 + 6, width - 10))
            label_y = max(0, min(y1 + 6, height - 24))
            try:
                bbox = draw.textbbox((label_x, label_y), label, font=small_font)
                draw.rectangle((bbox[0] - 4, bbox[1] - 3, bbox[2] + 4, bbox[3] + 3), fill=(0, 0, 0), outline=color, width=1)
            except Exception:
                pass
            draw.text((label_x, label_y), label, fill=color, font=small_font)
            applied.append({"label": label, "bounds": {"x1": x1, "y1": y1, "x2": x2, "y2": y2}})
        except Exception:
            continue

    title = "Annotated latest screenshot"
    try:
        draw.rectangle((8, 8, 8 + 430, 46), fill=(0, 0, 0), outline=(255, 255, 255), width=1)
        draw.text((18, 17), title, fill=(255, 255, 255), font=font)
    except Exception:
        pass

    _ensure_screen_dir()
    out_path = SCREEN_DIR / f"screen_annotated_{_now_stamp()}_{int(time.time() * 1000) % 100000}.jpg"
    image.save(out_path, format="JPEG", quality=90)
    payload = {
        "ok": True,
        "path": str(out_path),
        "source_path": str(source),
        "metadata_path": str(ANNOTATED_METADATA_PATH),
        "image": {"width": width, "height": height, "format": "JPEG"},
        "marks": applied,
        "metadata": meta.get("metadata", {}),
        "privacy_note": "Annotated screenshot is stored locally and served only when requested.",
    }
    ANNOTATED_METADATA_PATH.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    return payload


def screen_export_annotated_image(
    cfg: dict[str, Any],
    include_data_url: bool = True,
    max_bytes: int = 5_000_000,
    thumbnail_max_width: int = 0,
    summary_only: bool = False,
) -> dict[str, Any]:
    """Return the latest annotated screenshot bytes as base64 for inline display/use."""
    try:
        _require_screen_enabled(cfg, "list")
    except ScreenPolicyError as e:
        return {"ok": False, "error": str(e)}
    if not ANNOTATED_METADATA_PATH.exists():
        return {"ok": False, "error": "No annotated screenshot exists yet. Call screen_annotate_latest_image first."}
    try:
        annotated = json.loads(ANNOTATED_METADATA_PATH.read_text(encoding="utf-8"))
    except Exception as e:
        return {"ok": False, "error": str(e)}
    path = Path(str(annotated.get("path", "")))
    return _export_image_payload(
        path,
        annotated.get("image", {}),
        annotated.get("metadata", {}),
        include_data_url=include_data_url,
        max_bytes=max_bytes,
        thumbnail_max_width=thumbnail_max_width,
        summary_only=summary_only,
        suggested_filename="annotated-screen.jpg",
        privacy_note="Base64 contains the annotated screenshot pixels unless summary_only=true. Share/display intentionally. One-shot export: if the caller cannot display this payload, it should not retry this same annotated frame export in a loop.",
        extra={"source_path": annotated.get("source_path"), "marks": annotated.get("marks", [])},
    )



def screen_export_annotated_artifact_code(
    cfg: dict[str, Any],
    artifact_filename: str = "annotated-screen.jpg",
    max_bytes: int = 5_000_000,
    thumbnail_max_width: int = 0,
) -> dict[str, Any]:
    """Return Python code that writes the latest annotated screenshot into ChatGPT /mnt/data."""
    exported = screen_export_annotated_image(
        cfg,
        include_data_url=False,
        max_bytes=max_bytes,
        thumbnail_max_width=thumbnail_max_width,
        summary_only=False,
    )
    return _artifact_code_from_export(exported, artifact_filename, "annotated-screen.jpg")
