from __future__ import annotations

from urllib.parse import urlencode
from typing import Any
import html

from starlette.requests import Request
from starlette.responses import HTMLResponse, JSONResponse, PlainTextResponse, RedirectResponse, Response
from starlette.routing import Route
from starlette.middleware.base import BaseHTTPMiddleware

from .auth import (
    register_client,
    verify_pairing_code,
    create_authorization_code,
    exchange_code,
    exchange_refresh_token,
    verify_bearer,
    DEFAULT_ACCESS_TOKEN_TTL_SECONDS,
    DEFAULT_AUTH_CODE_TTL_SECONDS,
    DEFAULT_PAIRING_TTL_SECONDS,
    DEFAULT_REFRESH_TOKEN_TTL_SECONDS,
)
from .settings import base_url
from .config import load_config


def _issuer(cfg: dict[str, Any], request: Request | None = None) -> str:
    b = base_url(cfg).rstrip("/")
    if b.startswith("http://") and request is not None:
        b = str(request.base_url).rstrip("/")
    return b


def _oauth_enabled() -> bool:
    return load_config().get("server", {}).get("auth_mode", "noauth") == "oauth"


def _auth_int(current: dict[str, Any], key: str, default: int) -> int:
    try:
        return int(current.get("auth", {}).get(key, default))
    except Exception:
        return default


def oauth_routes(cfg: dict[str, Any]) -> list[Route]:
    async def health(request: Request) -> Response:
        current = load_config()
        auth = current.get("auth", {})
        return JSONResponse({
            "ok": True,
            "name": current.get("server", {}).get("name", "Local Files MCP"),
            "mcp_path": "/mcp",
            "auth_mode": current.get("server", {}).get("auth_mode", "noauth"),
            "oauth_ttls": {
                "pairing_code_ttl_seconds": auth.get("pairing_code_ttl_seconds", DEFAULT_PAIRING_TTL_SECONDS),
                "authorization_code_ttl_seconds": auth.get("authorization_code_ttl_seconds", DEFAULT_AUTH_CODE_TTL_SECONDS),
                "access_token_ttl_seconds": auth.get("access_token_ttl_seconds", DEFAULT_ACCESS_TOKEN_TTL_SECONDS),
                "refresh_token_ttl_seconds": auth.get("refresh_token_ttl_seconds", DEFAULT_REFRESH_TOKEN_TTL_SECONDS),
                "sliding_access_tokens": auth.get("sliding_access_tokens", True),
            },
        })

    async def favicon(request: Request) -> Response:
        return Response(status_code=204)

    async def protected_resource(request: Request) -> Response:
        # When GUI is set to No authentication, do not advertise OAuth.
        current = load_config()
        if current.get("server", {}).get("auth_mode", "noauth") != "oauth":
            return JSONResponse({"error": "oauth_disabled", "auth_mode": "noauth"}, status_code=404)
        issuer = _issuer(current, request)
        return JSONResponse({
            "resource": issuer + "/mcp",
            "authorization_servers": [issuer],
            "bearer_methods_supported": ["header"],
            "scopes_supported": current.get("auth", {}).get("token_scopes", []),
        })

    async def auth_server_metadata(request: Request) -> Response:
        current = load_config()
        if current.get("server", {}).get("auth_mode", "noauth") != "oauth":
            return JSONResponse({"error": "oauth_disabled", "auth_mode": "noauth"}, status_code=404)
        issuer = _issuer(current, request)
        return JSONResponse({
            "issuer": issuer,
            "authorization_endpoint": issuer + "/authorize",
            "token_endpoint": issuer + "/token",
            "registration_endpoint": issuer + "/register",
            "response_types_supported": ["code"],
            "grant_types_supported": ["authorization_code", "refresh_token"],
            "code_challenge_methods_supported": ["S256"],
            "token_endpoint_auth_methods_supported": ["none"],
            "scopes_supported": current.get("auth", {}).get("token_scopes", []),
        })

    async def register(request: Request) -> Response:
        if not _oauth_enabled():
            return JSONResponse({"error": "oauth_disabled", "auth_mode": "noauth"}, status_code=404)
        try:
            data = await request.json()
        except Exception:
            data = {}
        return JSONResponse(register_client(data), status_code=201)

    async def authorize_get(request: Request) -> Response:
        if not _oauth_enabled():
            return HTMLResponse("<h1>OAuth disabled</h1><p>The Local Files MCP GUI is set to No authentication.</p>", status_code=404)
        current = load_config()
        qp = dict(request.query_params)
        hidden = "".join(f'<input type="hidden" name="{html.escape(k)}" value="{html.escape(v)}">' for k, v in qp.items())
        pairing_ttl = _auth_int(current, "pairing_code_ttl_seconds", DEFAULT_PAIRING_TTL_SECONDS)
        body = f"""
        <!doctype html><title>Local Files MCP Pairing</title>
        <main style="font-family: system-ui; max-width: 720px; margin: 48px auto; line-height: 1.4">
          <h1>Local Files MCP pairing</h1>
          <p>Click <strong>Generate Pairing Code</strong> in the Local Files MCP GUI, then enter the pairing code here.</p>
          <p>The default pairing-code lifetime is now <strong>{pairing_ttl} seconds</strong>; existing ChatGPT bearer tokens are not erased when you generate a new pairing code.</p>
          <p><strong>Do not paste this code into chat.</strong></p>
          <form method="post" action="/authorize">
            {hidden}
            <label>Pairing code<br><input name="pairing_code" autofocus style="font-size: 20px; width: 100%; padding: 8px"></label>
            <p><button style="font-size: 18px; padding: 8px 12px">Authorize</button></p>
          </form>
        </main>
        """
        return HTMLResponse(body)

    async def authorize_post(request: Request) -> Response:
        if not _oauth_enabled():
            return HTMLResponse("<h1>OAuth disabled</h1><p>The Local Files MCP GUI is set to No authentication.</p>", status_code=404)
        current = load_config()
        form = await request.form()
        pairing_code = str(form.get("pairing_code", ""))
        if not verify_pairing_code(pairing_code):
            return HTMLResponse("<h1>Invalid or expired pairing code</h1><p>Generate a new pairing code in the GUI and try again.</p>", status_code=401)
        client_id = str(form.get("client_id", ""))
        redirect_uri = str(form.get("redirect_uri", ""))
        state = str(form.get("state", ""))
        code_challenge = form.get("code_challenge")
        scope = form.get("scope")
        if not redirect_uri:
            return PlainTextResponse("Missing redirect_uri", status_code=400)
        code = create_authorization_code(
            client_id,
            redirect_uri,
            str(code_challenge) if code_challenge else None,
            str(scope) if scope else None,
            ttl_seconds=_auth_int(current, "authorization_code_ttl_seconds", DEFAULT_AUTH_CODE_TTL_SECONDS),
        )
        sep = "&" if "?" in redirect_uri else "?"
        return RedirectResponse(redirect_uri + sep + urlencode({"code": code, "state": state}), status_code=302)

    async def token(request: Request) -> Response:
        if not _oauth_enabled():
            return JSONResponse({"error": "oauth_disabled", "auth_mode": "noauth"}, status_code=404)
        current = load_config()
        form = await request.form()
        grant_type = str(form.get("grant_type", "authorization_code"))
        try:
            if grant_type == "authorization_code":
                data = exchange_code(
                    code=str(form.get("code", "")),
                    client_id=str(form.get("client_id", "")),
                    redirect_uri=str(form.get("redirect_uri", "")),
                    code_verifier=str(form.get("code_verifier")) if form.get("code_verifier") else None,
                    ttl_seconds=_auth_int(current, "access_token_ttl_seconds", DEFAULT_ACCESS_TOKEN_TTL_SECONDS),
                    refresh_ttl_seconds=_auth_int(current, "refresh_token_ttl_seconds", DEFAULT_REFRESH_TOKEN_TTL_SECONDS),
                )
                return JSONResponse(data)
            if grant_type == "refresh_token":
                data = exchange_refresh_token(
                    refresh_token=str(form.get("refresh_token", "")),
                    client_id=str(form.get("client_id", "")),
                    ttl_seconds=_auth_int(current, "access_token_ttl_seconds", DEFAULT_ACCESS_TOKEN_TTL_SECONDS),
                    sliding_refresh_seconds=_auth_int(current, "refresh_token_ttl_seconds", DEFAULT_REFRESH_TOKEN_TTL_SECONDS),
                )
                return JSONResponse(data)
            return JSONResponse({"error": "unsupported_grant_type"}, status_code=400)
        except Exception as e:
            return JSONResponse({"error": "invalid_grant", "error_description": str(e)}, status_code=400)

    return [
        Route("/health", health, methods=["GET"]),
        Route("/favicon.ico", favicon, methods=["GET"]),
        Route("/.well-known/oauth-protected-resource", protected_resource, methods=["GET"]),
        Route("/.well-known/oauth-protected-resource/mcp", protected_resource, methods=["GET"]),
        Route("/.well-known/oauth-authorization-server", auth_server_metadata, methods=["GET"]),
        Route("/.well-known/openid-configuration", auth_server_metadata, methods=["GET"]),
        Route("/register", register, methods=["POST"]),
        Route("/authorize", authorize_get, methods=["GET"]),
        Route("/authorize", authorize_post, methods=["POST"]),
        Route("/token", token, methods=["POST"]),
    ]


class BearerAuthMiddleware(BaseHTTPMiddleware):
    def __init__(self, app, cfg: dict[str, Any]):
        super().__init__(app)
        self.cfg = cfg

    async def dispatch(self, request: Request, call_next):
        current = load_config()
        if current.get("server", {}).get("auth_mode", "noauth") != "oauth":
            return await call_next(request)
        if not request.url.path.startswith("/mcp"):
            return await call_next(request)
        auth = request.headers.get("authorization", "")
        access_ttl = _auth_int(current, "access_token_ttl_seconds", DEFAULT_ACCESS_TOKEN_TTL_SECONDS)
        sliding = bool(current.get("auth", {}).get("sliding_access_tokens", True))
        sliding_ttl = access_ttl if sliding else None
        if auth.lower().startswith("bearer ") and verify_bearer(auth.split(" ", 1)[1].strip(), sliding_ttl_seconds=sliding_ttl):
            return await call_next(request)
        issuer = _issuer(current, request)
        headers = {"WWW-Authenticate": f'Bearer resource_metadata="{issuer}/.well-known/oauth-protected-resource", error="invalid_token"'}
        return JSONResponse({"error": "authorization_required"}, status_code=401, headers=headers)
