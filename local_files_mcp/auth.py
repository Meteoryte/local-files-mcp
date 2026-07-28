from __future__ import annotations

from typing import Any
import base64
import hashlib
import json
import secrets
import time

from .paths import SESSION_PATH, ensure_dirs

DEFAULT_PAIRING_TTL_SECONDS = 3600          # 1 hour, enough for a local pairing flow
DEFAULT_AUTH_CODE_TTL_SECONDS = 600        # 10 minutes
DEFAULT_ACCESS_TOKEN_TTL_SECONDS = 2592000 # 30 days
DEFAULT_REFRESH_TOKEN_TTL_SECONDS = 31536000 # 1 year


def _sha256(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _hash_with_salt(value: str, salt: str) -> str:
    return _sha256(salt + value)


def _now() -> int:
    return int(time.time())


def _never_or_future(expires_at: int | None) -> bool:
    # expires_at <= 0 means intentionally non-expiring local-development token.
    return expires_at is not None and (expires_at <= 0 or _now() <= expires_at)


def load_session() -> dict[str, Any]:
    if not SESSION_PATH.exists():
        return {}
    try:
        return json.loads(SESSION_PATH.read_text(encoding="utf-8"))
    except Exception:
        return {}


def save_session(session: dict[str, Any]) -> None:
    ensure_dirs()
    SESSION_PATH.write_text(json.dumps(session, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def clear_session() -> None:
    if SESSION_PATH.exists():
        SESSION_PATH.unlink()


def _base_session(existing: dict[str, Any] | None = None) -> dict[str, Any]:
    s = existing or {}
    s.setdefault("active", True)
    s.setdefault("clients", {})
    s.setdefault("authorization_codes", {})
    s.setdefault("access_tokens", {})
    s.setdefault("refresh_tokens", {})
    return s


def create_pairing_session(ttl_seconds: int = DEFAULT_PAIRING_TTL_SECONDS) -> str:
    """Create or rotate only the short pairing code.

    v1.7 important fix: generating a new pairing code no longer wipes existing
    dynamic client registrations or bearer tokens. The old implementation reset
    the whole session file, which made ChatGPT links appear to time out whenever
    pairing was regenerated.
    """
    code = "-".join(secrets.token_urlsafe(3).upper() for _ in range(3))
    salt = secrets.token_hex(16)
    now = _now()
    s = _base_session(load_session())
    s.update({
        "active": True,
        "created_at": s.get("created_at", now),
        "pairing_created_at": now,
        "expires_at": now + int(ttl_seconds),
        "pairing_salt": salt,
        "pairing_code_hash": _hash_with_salt(code, salt),
    })
    save_session(s)
    return code


def verify_pairing_code(code: str) -> bool:
    s = load_session()
    if not s.get("active"):
        return False
    # Pairing expiration applies only to the code, not to existing tokens.
    if int(s.get("expires_at", 0)) > 0 and _now() > int(s.get("expires_at", 0)):
        return False
    return secrets.compare_digest(_hash_with_salt(code.strip(), s.get("pairing_salt", "")), s.get("pairing_code_hash", ""))


def register_client(data: dict[str, Any]) -> dict[str, Any]:
    s = _base_session(load_session())
    client_id = "lfmcp_" + secrets.token_urlsafe(18)
    s.setdefault("clients", {})[client_id] = {
        "client_id": client_id,
        "client_name": data.get("client_name", "ChatGPT"),
        "redirect_uris": data.get("redirect_uris", []),
        "created_at": _now(),
    }
    save_session(s)
    return {
        "client_id": client_id,
        "client_id_issued_at": _now(),
        "redirect_uris": data.get("redirect_uris", []),
        "grant_types": ["authorization_code", "refresh_token"],
        "response_types": ["code"],
        "token_endpoint_auth_method": "none",
    }


def create_authorization_code(
    client_id: str,
    redirect_uri: str,
    code_challenge: str | None,
    scope: str | None,
    ttl_seconds: int = DEFAULT_AUTH_CODE_TTL_SECONDS,
) -> str:
    s = _base_session(load_session())
    code = secrets.token_urlsafe(32)
    s.setdefault("authorization_codes", {})[code] = {
        "client_id": client_id,
        "redirect_uri": redirect_uri,
        "code_challenge": code_challenge,
        "scope": scope or "files:metadata files:search files:read files:write",
        "expires_at": _now() + int(ttl_seconds),
    }
    save_session(s)
    return code


def _pkce_s256(verifier: str) -> str:
    digest = hashlib.sha256(verifier.encode("ascii")).digest()
    return base64.urlsafe_b64encode(digest).decode("ascii").rstrip("=")


def _issue_access_token(s: dict[str, Any], client_id: str, scope: str | None, ttl_seconds: int) -> tuple[str, int]:
    token = secrets.token_urlsafe(36)
    salt = secrets.token_hex(16)
    token_hash = _hash_with_salt(token, salt)
    ttl = int(ttl_seconds)
    expires_at = 0 if ttl <= 0 else _now() + ttl
    s.setdefault("access_tokens", {})[token_hash] = {
        "salt": salt,
        "client_id": client_id,
        "scope": scope,
        "created_at": _now(),
        "expires_at": expires_at,
    }
    return token, ttl


def _issue_refresh_token(s: dict[str, Any], client_id: str, scope: str | None, ttl_seconds: int) -> tuple[str, int]:
    token = secrets.token_urlsafe(48)
    salt = secrets.token_hex(16)
    token_hash = _hash_with_salt(token, salt)
    ttl = int(ttl_seconds)
    expires_at = 0 if ttl <= 0 else _now() + ttl
    s.setdefault("refresh_tokens", {})[token_hash] = {
        "salt": salt,
        "client_id": client_id,
        "scope": scope,
        "created_at": _now(),
        "expires_at": expires_at,
    }
    return token, ttl


def exchange_code(
    code: str,
    client_id: str,
    redirect_uri: str,
    code_verifier: str | None,
    ttl_seconds: int = DEFAULT_ACCESS_TOKEN_TTL_SECONDS,
    refresh_ttl_seconds: int = DEFAULT_REFRESH_TOKEN_TTL_SECONDS,
) -> dict[str, Any]:
    s = _base_session(load_session())
    meta = s.setdefault("authorization_codes", {}).pop(code, None)
    if not meta:
        save_session(s)
        raise ValueError("invalid_grant")
    if int(meta.get("expires_at", 0)) > 0 and _now() > int(meta.get("expires_at", 0)):
        save_session(s)
        raise ValueError("expired_grant")
    if meta.get("client_id") != client_id or meta.get("redirect_uri") != redirect_uri:
        save_session(s)
        raise ValueError("invalid_grant")
    challenge = meta.get("code_challenge")
    if challenge and code_verifier and _pkce_s256(code_verifier) != challenge:
        save_session(s)
        raise ValueError("invalid_grant_pkce")

    scope = meta.get("scope")
    access_token, access_ttl = _issue_access_token(s, client_id, scope, ttl_seconds)
    refresh_token, refresh_ttl = _issue_refresh_token(s, client_id, scope, refresh_ttl_seconds)
    save_session(s)
    response = {
        "access_token": access_token,
        "token_type": "Bearer",
        "expires_in": access_ttl,
        "scope": scope,
        "refresh_token": refresh_token,
    }
    if refresh_ttl > 0:
        response["refresh_token_expires_in"] = refresh_ttl
    return response


def exchange_refresh_token(
    refresh_token: str,
    client_id: str,
    ttl_seconds: int = DEFAULT_ACCESS_TOKEN_TTL_SECONDS,
    sliding_refresh_seconds: int | None = DEFAULT_REFRESH_TOKEN_TTL_SECONDS,
) -> dict[str, Any]:
    s = _base_session(load_session())
    now = _now()
    for token_hash, meta in list(s.get("refresh_tokens", {}).items()):
        expires_at = int(meta.get("expires_at", 0))
        if expires_at > 0 and now > expires_at:
            continue
        if meta.get("client_id") != client_id:
            continue
        if secrets.compare_digest(_hash_with_salt(refresh_token, meta.get("salt", "")), token_hash):
            scope = meta.get("scope")
            access_token, access_ttl = _issue_access_token(s, client_id, scope, ttl_seconds)
            if sliding_refresh_seconds is not None and int(sliding_refresh_seconds) != 0:
                meta["expires_at"] = now + int(sliding_refresh_seconds)
                meta["last_used_at"] = now
            save_session(s)
            return {
                "access_token": access_token,
                "token_type": "Bearer",
                "expires_in": access_ttl,
                "scope": scope,
            }
    save_session(s)
    raise ValueError("invalid_refresh_token")


def verify_bearer(token: str, sliding_ttl_seconds: int | None = None) -> bool:
    s = _base_session(load_session())
    now = _now()
    changed = False
    for token_hash, meta in list(s.get("access_tokens", {}).items()):
        expires_at = int(meta.get("expires_at", 0))
        if expires_at > 0 and now > expires_at:
            continue
        if secrets.compare_digest(_hash_with_salt(token, meta.get("salt", "")), token_hash):
            if sliding_ttl_seconds is not None:
                ttl = int(sliding_ttl_seconds)
                if ttl > 0:
                    meta["expires_at"] = now + ttl
                    meta["last_used_at"] = now
                    changed = True
                elif ttl <= 0:
                    meta["expires_at"] = 0
                    meta["last_used_at"] = now
                    changed = True
            if changed:
                save_session(s)
            return True
    if changed:
        save_session(s)
    return False
