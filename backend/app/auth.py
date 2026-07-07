"""Minimal auth: PBKDF2 password hashing + HMAC-signed opaque bearer tokens.

No JWT/passlib dependency — everything here is Python stdlib (hashlib, hmac,
base64, json). This is intentionally minimal for the driver-only scope of this
pass; the PRD's OAuth2/OIDC (Auth0/Keycloak) + full RBAC-from-JWT-claims model
is the production target once the operator/fleet modules are built.
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import json
import os
import time
from pathlib import Path

from fastapi import Depends, Header, HTTPException

from . import db

SECRET_PATH = Path(__file__).resolve().parent.parent / "data" / "secret.key"
SECRET_ENV_VAR = "EVPLATFORM_SECRET_KEY"
TOKEN_TTL_SECONDS = 60 * 60 * 24 * 7  # 7 days

_secret_cache: bytes | None = None


def _get_secret() -> bytes:
    """A real deployment must set EVPLATFORM_SECRET_KEY (urlsafe-base64,
    32+ random bytes) so every instance behind a load balancer validates
    tokens with the same key, and so the secret lives in real secrets
    infra instead of a file on one machine's disk. The locally-generated
    file is a dev-only fallback for running this with zero setup."""
    global _secret_cache
    if _secret_cache is not None:
        return _secret_cache

    env_secret = os.environ.get(SECRET_ENV_VAR)
    if env_secret:
        _secret_cache = base64.urlsafe_b64decode(env_secret + "=" * (-len(env_secret) % 4))
        return _secret_cache

    SECRET_PATH.parent.mkdir(parents=True, exist_ok=True)
    if not SECRET_PATH.exists():
        SECRET_PATH.write_bytes(os.urandom(32))
    _secret_cache = SECRET_PATH.read_bytes()
    return _secret_cache


def hash_password(password: str, salt: str | None = None) -> tuple[str, str]:
    salt = salt or base64.urlsafe_b64encode(os.urandom(16)).decode()
    digest = hashlib.pbkdf2_hmac("sha256", password.encode(), salt.encode(), 200_000)
    return base64.urlsafe_b64encode(digest).decode(), salt


def verify_password(password: str, password_hash: str, salt: str) -> bool:
    computed, _ = hash_password(password, salt)
    return hmac.compare_digest(computed, password_hash)


def _b64(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).decode().rstrip("=")


def _unb64(data: str) -> bytes:
    padding = "=" * (-len(data) % 4)
    return base64.urlsafe_b64decode(data + padding)


def issue_token(user_id: str, role: str) -> str:
    payload = json.dumps({"uid": user_id, "role": role, "exp": time.time() + TOKEN_TTL_SECONDS}).encode()
    sig = hmac.new(_get_secret(), payload, hashlib.sha256).digest()
    return f"{_b64(payload)}.{_b64(sig)}"


def decode_token(token: str) -> dict:
    try:
        payload_b64, sig_b64 = token.split(".", 1)
        payload = _unb64(payload_b64)
        sig = _unb64(sig_b64)
    except Exception:
        raise HTTPException(status_code=401, detail="Malformed token")

    expected_sig = hmac.new(_get_secret(), payload, hashlib.sha256).digest()
    if not hmac.compare_digest(sig, expected_sig):
        raise HTTPException(status_code=401, detail="Invalid token signature")

    claims = json.loads(payload)
    if claims["exp"] < time.time():
        raise HTTPException(status_code=401, detail="Token expired")
    return claims


def get_current_user(authorization: str = Header(default="")) -> dict:
    if not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Missing bearer token")
    claims = decode_token(authorization.removeprefix("Bearer ").strip())
    conn = db.get_conn()
    user = db.row_to_dict(conn.execute("SELECT * FROM users WHERE id = ?", (claims["uid"],)).fetchone())
    if user is None:
        raise HTTPException(status_code=401, detail="User not found")

    # Checked on every request, not just at login — a super_admin suspending
    # an operator (routers/admin.py) needs to take effect immediately, not
    # just block the next fresh login while an existing 7-day token still works.
    if user["operator_id"]:
        operator = db.row_to_dict(conn.execute("SELECT status FROM operators WHERE id=?", (user["operator_id"],)).fetchone())
        if operator and operator["status"] == "suspended":
            raise HTTPException(status_code=403, detail="This operator account has been suspended")

    return user


def require_role(*roles: str):
    """RBAC, enforced server-side from the authenticated user's row — never
    trust a client-asserted role. Use as Depends(require_role("station_admin"))."""
    def check(user: dict = Depends(get_current_user)) -> dict:
        if user["role"] not in roles:
            raise HTTPException(status_code=403, detail="Insufficient role")
        return user
    return check
