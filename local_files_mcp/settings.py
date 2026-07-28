from __future__ import annotations

from typing import Any
from urllib.request import urlopen
from urllib.parse import urlparse, urlunparse
import ipaddress
import json


def normalize_public_base_url(raw: str | None) -> str:
    """Return a clean public BASE URL, never the /mcp endpoint.

    Users often paste the full ChatGPT MCP URL into the GUI field. The config field
    is intentionally the base public URL, so this strips one or more trailing /mcp
    segments and removes query/fragment data.
    """
    value = (raw or "").strip().strip('"').strip("'")
    if not value:
        return ""
    if "://" not in value:
        value = "https://" + value
    parsed = urlparse(value)
    path = (parsed.path or "").rstrip("/")
    while path == "/mcp" or path.endswith("/mcp"):
        path = path[: -len("/mcp")].rstrip("/")
    cleaned = parsed._replace(path=path, params="", query="", fragment="")
    return urlunparse(cleaned).rstrip("/")


def _host_is_unsafe(host: str | None) -> str | None:
    if not host:
        return "missing hostname"
    h = host.lower().strip("[]")
    if h in {"localhost", "0.0.0.0", "::1"}:
        return "localhost/loopback is not reachable by ChatGPT"
    if h.endswith(".local"):
        return ".local hostnames are not public internet HTTPS URLs"
    try:
        ip = ipaddress.ip_address(h)
        if ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_reserved or ip.is_multicast:
            return "private/loopback IP addresses are not accepted by ChatGPT"
    except ValueError:
        pass
    return None


def validate_chatgpt_url(url: str | None) -> tuple[bool, str, str]:
    """Validate the value ChatGPT should receive: the final /mcp HTTPS endpoint."""
    final = (url or "").strip()
    if not final:
        return False, "No public MCP URL yet. Start a tunnel or deploy the server, then set the HTTPS URL.", ""
    parsed = urlparse(final)
    if parsed.scheme != "https":
        return False, "Unsafe URL: ChatGPT Developer Mode requires a public https:// URL, not http:// or localhost.", final
    if parsed.query or parsed.fragment:
        return False, "Unsafe URL: remove query strings and #fragments. The URL should end with /mcp.", final
    host_issue = _host_is_unsafe(parsed.hostname)
    if host_issue:
        return False, f"Unsafe URL: {host_issue}. Use ngrok, Cloudflare Tunnel, or a real deployed HTTPS domain.", final
    if not parsed.path.rstrip("/").endswith("/mcp"):
        return False, "The ChatGPT connector URL must be the HTTPS endpoint ending in /mcp.", final.rstrip("/") + "/mcp"
    if "/mcp/mcp" in parsed.path:
        return False, "The URL has /mcp twice. Put the base tunnel URL in the GUI; ChatGPT should receive exactly one /mcp.", final.replace("/mcp/mcp", "/mcp")
    return True, "Ready: this looks like a valid public HTTPS MCP URL for ChatGPT Developer Mode.", final


def base_url(cfg: dict[str, Any]) -> str:
    public = normalize_public_base_url(cfg.get("server", {}).get("public_url") or "")
    if public:
        return public
    host = cfg.get("server", {}).get("host", "127.0.0.1")
    port = cfg.get("server", {}).get("port", 8765)
    return f"http://{host}:{port}"


def mcp_url(cfg: dict[str, Any]) -> str:
    return base_url(cfg).rstrip("/") + "/mcp"


def app_settings(cfg: dict[str, Any]) -> dict[str, str]:
    auth_mode = cfg.get("server", {}).get("auth_mode", "noauth")
    url = mcp_url(cfg)
    ok, message, corrected = validate_chatgpt_url(url)
    return {
        "name": cfg.get("server", {}).get("name", "Local Files MCP"),
        "description": cfg.get("server", {}).get("description", "Local document access for folders you explicitly configure. Search/read files; writes require local approval."),
        "connector_url": corrected or url,
        "authentication": "OAuth" if auth_mode == "oauth" else "No authentication",
        "url_ready": "yes" if ok else "no",
        "url_status": message,
        "notes": "ChatGPT Developer Mode requires a public HTTPS /mcp URL. For local testing, use ngrok or Cloudflare Tunnel.",
    }


def format_settings(cfg: dict[str, Any]) -> str:
    s = app_settings(cfg)
    ready = s.get("url_ready") == "yes"
    lines = [
        "ChatGPT Developer Mode App/Connector settings",
        "=============================================",
        "",
        "COPY THESE FIELDS EXACTLY:",
        f"Name: {s['name']}",
        f"Description: {s['description']}",
        f"MCP URL / Connector URL: {s['connector_url']}",
        f"Authentication: {s['authentication']}",
        "",
        "URL status:",
        ("✅ " if ready else "⚠️  ") + s["url_status"],
        "",
        "ChatGPT path:",
        "Settings → Apps & Connectors → Advanced settings → Developer mode: ON",
        "Settings → Apps & Connectors → Create",
        "",
    ]
    if not ready:
        lines += [
            "Fix for 'unsafe URL':",
            "1. Click Start MCP Server in this GUI.",
            "2. Click Start Tunnel in this GUI. No separate terminal is required.",
            "3. If ngrok is missing, click Download ngrok, install it, then click Auto-Find.",
            "4. The GUI fills Public HTTPS URL automatically after the tunnel starts.",
            "5. Do NOT use http://127.0.0.1, http://localhost, a private IP, or a self-signed HTTPS URL.",
            "6. Do NOT add /mcp in the Public HTTPS URL field; the GUI adds /mcp for ChatGPT.",
            "",
        ]
    if s["authentication"] == "OAuth":
        lines += [
            "OAuth pairing:",
            "1. Click Generate Pairing Code in this GUI.",
            "2. Create/link the app in ChatGPT.",
            "3. When the auth page opens, enter the local pairing code.",
            "",
        ]
    return "\n".join(lines)


def detect_ngrok() -> str | None:
    try:
        with urlopen("http://127.0.0.1:4040/api/tunnels", timeout=2) as resp:
            data = json.loads(resp.read().decode("utf-8"))
        for t in data.get("tunnels", []):
            url = t.get("public_url", "")
            if url.startswith("https://"):
                return normalize_public_base_url(url)
    except Exception:
        return None
    return None
