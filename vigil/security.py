"""Authentication (JWT in a Bearer header or HttpOnly cookie) and role-based authorisation.

Roles are ordered: viewer < analyst < admin.
- viewer:  read everything, watch live video
- analyst: + acknowledge/verify events, run investigations, manage identities
- admin:   + cameras, zones, rules, users
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import os
import secrets
from datetime import datetime, timedelta, timezone
from pathlib import Path

import jwt
from fastapi import Depends, HTTPException, Request, WebSocket, status
from sqlalchemy import select

from vigil.config import get_settings
from vigil.db import AuditLog, User, session

ROLE_RANK = {"viewer": 0, "analyst": 1, "admin": 2}
COOKIE = "vigil_session"
_SCRYPT = dict(n=2**14, r=8, p=1, dklen=32)


def hash_password(password: str) -> str:
    salt = os.urandom(16)
    dk = hashlib.scrypt(password.encode(), salt=salt, **_SCRYPT)
    return "scrypt$" + base64.b64encode(salt).decode() + "$" + base64.b64encode(dk).decode()


def verify_password(password: str, stored: str) -> bool:
    try:
        scheme, salt_b64, dk_b64 = stored.split("$")
        if scheme != "scrypt":
            return False
        dk = hashlib.scrypt(password.encode(), salt=base64.b64decode(salt_b64), **_SCRYPT)
        return hmac.compare_digest(dk, base64.b64decode(dk_b64))
    except Exception:
        return False


def _secret_file(name: str) -> Path:
    return get_settings().data_dir / name


def jwt_secret() -> str:
    s = get_settings()
    if s.jwt_secret:
        return s.jwt_secret
    f = _secret_file(".jwt_secret")
    if not f.exists():
        f.write_text(secrets.token_urlsafe(48))
        f.chmod(0o600)
    return f.read_text().strip()


def issue_token(user: User) -> str:
    now = datetime.now(timezone.utc)
    payload = {"sub": user.id, "usr": user.username, "role": user.role, "iat": now,
               "exp": now + timedelta(hours=get_settings().jwt_ttl_hours)}
    return jwt.encode(payload, jwt_secret(), algorithm="HS256")


def decode_token(token: str) -> dict:
    return jwt.decode(token, jwt_secret(), algorithms=["HS256"])


class Principal:
    def __init__(self, user_id: str, username: str, role: str):
        self.id, self.username, self.role = user_id, username, role

    def has(self, role: str) -> bool:
        return ROLE_RANK.get(self.role, -1) >= ROLE_RANK[role]


def _token_from(request_headers, cookies, query) -> str | None:
    auth = request_headers.get("authorization", "")
    if auth.lower().startswith("bearer "):
        return auth[7:].strip()
    if cookies.get(COOKIE):
        return cookies[COOKIE]
    return query.get("token")


async def _principal_from_token(token: str | None) -> Principal:
    if not token:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Not authenticated")
    try:
        claims = decode_token(token)
    except jwt.PyJWTError:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Invalid or expired session")
    # Re-check the user row so disabling a user takes effect before token expiry.
    async with session() as db:
        user = await db.get(User, claims["sub"])
    if user is None or user.disabled:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Account disabled")
    return Principal(user.id, user.username, user.role)


async def current_user(request: Request) -> Principal:
    return await _principal_from_token(_token_from(request.headers, request.cookies, {}))


async def media_user(request: Request) -> Principal:
    """Media (<img>/<video>) cannot send headers: accept cookie or ?token=."""
    return await _principal_from_token(_token_from(request.headers, request.cookies, request.query_params))


async def ws_user(ws: WebSocket) -> Principal:
    return await _principal_from_token(_token_from(ws.headers, ws.cookies, ws.query_params))


def require(role: str):
    async def dep(p: Principal = Depends(current_user)) -> Principal:
        if not p.has(role):
            raise HTTPException(status.HTTP_403_FORBIDDEN, f"Requires role '{role}'")
        return p
    return dep


async def audit(actor: str, action: str, target: str | None = None, **details) -> None:
    async with session() as db:
        db.add(AuditLog(actor=actor, action=action, target=target, details=details))
        await db.commit()


async def bootstrap_admin() -> None:
    """Create the first admin. The generated password goes to a 0600 file, never to logs."""
    s = get_settings()
    async with session() as db:
        existing = (await db.execute(select(User).limit(1))).scalar_one_or_none()
        if existing is not None:
            return
        password = s.admin_password or secrets.token_urlsafe(12)
        db.add(User(username=s.admin_username, password_hash=hash_password(password), role="admin"))
        await db.commit()
    if not s.admin_password:
        f = _secret_file("initial_admin_credentials.txt")
        f.write_text(f"username: {s.admin_username}\npassword: {password}\n")
        f.chmod(0o600)
