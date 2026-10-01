from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from pydantic import BaseModel, Field
from sqlalchemy import select

from vigil.config import get_settings
from vigil.db import User, get_db, utcnow
from vigil.security import (COOKIE, ROLE_RANK, Principal, audit, current_user, hash_password, issue_token, require,
                            verify_password)

router = APIRouter(prefix="/api", tags=["auth"])
_failures: dict[str, list[float]] = {}


class LoginIn(BaseModel):
    username: str
    password: str


class UserIn(BaseModel):
    username: str = Field(min_length=2, max_length=80)
    password: str = Field(min_length=8, max_length=200)
    role: str = "viewer"


class UserPatch(BaseModel):
    role: str | None = None
    disabled: bool | None = None
    password: str | None = Field(default=None, min_length=8, max_length=200)


def _user(u: User) -> dict:
    return {"id": u.id, "username": u.username, "role": u.role, "disabled": u.disabled,
            "created_at": u.created_at.isoformat() if u.created_at else None,
            "last_login": u.last_login.isoformat() if u.last_login else None}


@router.post("/auth/login")
async def login(body: LoginIn, request: Request, response: Response, db=Depends(get_db)):
    import time
    ip = request.client.host if request.client else "?"
    now = time.time()
    recent = [t for t in _failures.get(ip, []) if now - t < 300]
    if len(recent) >= 10:
        raise HTTPException(429, "Too many failed attempts; try again in a few minutes")
    u = (await db.execute(select(User).where(User.username == body.username))).scalar_one_or_none()
    if u is None or u.disabled or not verify_password(body.password, u.password_hash):
        _failures[ip] = recent + [now]
        await audit(body.username, "auth.login_failed", None, ip=ip)
        raise HTTPException(401, "Invalid username or password")
    _failures.pop(ip, None)
    u.last_login = utcnow()
    await db.commit()
    token = issue_token(u)
    s = get_settings()
    response.set_cookie(COOKIE, token, httponly=True, samesite="strict", secure=s.cookie_secure,
                        max_age=s.jwt_ttl_hours * 3600, path="/")
    await audit(u.username, "auth.login", None, ip=ip)
    return {"token": token, "user": _user(u)}


@router.post("/auth/logout")
async def logout(response: Response):
    response.delete_cookie(COOKIE, path="/")
    return {"ok": True}


@router.get("/auth/me")
async def me(p: Principal = Depends(current_user)):
    return {"id": p.id, "username": p.username, "role": p.role}


@router.get("/users")
async def list_users(_: Principal = Depends(require("admin")), db=Depends(get_db)):
    return [_user(u) for u in (await db.execute(select(User).order_by(User.created_at))).scalars()]


@router.post("/users")
async def create_user(body: UserIn, p: Principal = Depends(require("admin")), db=Depends(get_db)):
    if body.role not in ROLE_RANK:
        raise HTTPException(400, "invalid role")
    if (await db.execute(select(User).where(User.username == body.username))).scalar_one_or_none():
        raise HTTPException(409, "username taken")
    u = User(username=body.username, password_hash=hash_password(body.password), role=body.role)
    db.add(u)
    await db.commit()
    await audit(p.username, "user.create", u.username, role=body.role)
    return _user(u)


@router.patch("/users/{user_id}")
async def patch_user(user_id: str, body: UserPatch, p: Principal = Depends(require("admin")), db=Depends(get_db)):
    u = await db.get(User, user_id)
    if u is None:
        raise HTTPException(404, "not found")
    if body.role is not None:
        if body.role not in ROLE_RANK:
            raise HTTPException(400, "invalid role")
        if u.id == p.id and body.role != "admin":
            raise HTTPException(400, "cannot demote yourself")
        u.role = body.role
    if body.disabled is not None:
        if u.id == p.id and body.disabled:
            raise HTTPException(400, "cannot disable yourself")
        u.disabled = body.disabled
    if body.password:
        u.password_hash = hash_password(body.password)
    await db.commit()
    await audit(p.username, "user.update", u.username, role=u.role, disabled=u.disabled,
                password_changed=bool(body.password))
    return _user(u)


@router.post("/auth/password")
async def change_password(body: dict, p: Principal = Depends(current_user), db=Depends(get_db)):
    u = await db.get(User, p.id)
    if not verify_password(body.get("current", ""), u.password_hash):
        raise HTTPException(400, "current password is wrong")
    new = body.get("new", "")
    if len(new) < 8:
        raise HTTPException(400, "password must be at least 8 characters")
    u.password_hash = hash_password(new)
    await db.commit()
    await audit(p.username, "auth.password_changed", None)
    return {"ok": True}
