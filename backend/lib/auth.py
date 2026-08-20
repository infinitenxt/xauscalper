"""Auth: bcrypt passwords, httpOnly cookie sessions, one active session per user.

"One login per device only" is enforced by deleting every existing session for a
user when they log in — the previous device is signed out immediately.
"""
from __future__ import annotations

import secrets
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, Optional

from fastapi import HTTPException, Request, Response
from passlib.context import CryptContext

from lib.db import db

COOKIE_NAME = "gt_session"
SESSION_DAYS = 14
_pwd = CryptContext(schemes=["bcrypt"], deprecated="auto")


def now() -> datetime:
    return datetime.now(timezone.utc)


def aware(dt: Any) -> Optional[datetime]:
    if isinstance(dt, datetime):
        return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)
    return None


def hash_password(raw: str) -> str:
    return _pwd.hash(raw)


def verify_password(raw: str, hashed: str) -> bool:
    try:
        return _pwd.verify(raw, hashed)
    except Exception:  # noqa: BLE001
        return False


def clean(doc: Optional[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    if not doc:
        return None
    return {k: v for k, v in doc.items() if k != "_id"}


# ------------------------------------------------------------------ sessions
async def create_session(user_id: str, request: Request) -> str:
    """Issue a session and revoke every other one for this user (single device)."""
    await db.sessions.delete_many({"user_id": user_id})
    token = secrets.token_urlsafe(32)
    ua = request.headers.get("user-agent", "")[:220]
    await db.sessions.insert_one(
        {
            "id": str(uuid.uuid4()),
            "token": token,
            "user_id": user_id,
            "user_agent": ua,
            "ip": request.client.host if request.client else "",
            "created_at": now(),
            "expires_at": now() + timedelta(days=SESSION_DAYS),
        }
    )
    return token


def set_cookie(response: Response, token: str) -> None:
    response.set_cookie(
        COOKIE_NAME,
        token,
        httponly=True,
        samesite="lax",
        secure=True,
        max_age=SESSION_DAYS * 24 * 3600,
        path="/",
    )


def clear_cookie(response: Response) -> None:
    response.delete_cookie(COOKIE_NAME, path="/")


async def destroy_session(token: Optional[str]) -> None:
    if token:
        await db.sessions.delete_many({"token": token})


# --------------------------------------------------------------------- users
def is_subscribed(user: Optional[Dict[str, Any]]) -> bool:
    if not user:
        return False
    if user.get("role") == "admin":
        return True
    sub = user.get("subscription") or {}
    if sub.get("status") != "active":
        return False
    exp = aware(sub.get("expires_at"))
    return bool(exp and exp > now())


def public_user(user: Dict[str, Any]) -> Dict[str, Any]:
    sub = user.get("subscription") or {}
    exp = aware(sub.get("expires_at"))
    days_left = max(0, int((exp - now()).total_seconds() // 86400)) if exp else 0
    return {
        "id": user["id"],
        "email": user["email"],
        "username": user.get("username") or user["email"].split("@")[0],
        "role": user.get("role", "user"),
        "is_active": bool(user.get("is_active", True)),
        "created_at": user.get("created_at"),
        "subscribed": is_subscribed(user),
        "subscription": {
            "plan_id": sub.get("plan_id"),
            "plan_name": sub.get("plan_name"),
            "status": sub.get("status", "none"),
            "source": sub.get("source"),
            "started_at": sub.get("started_at"),
            "expires_at": sub.get("expires_at"),
            "days_left": days_left,
        },
    }


async def current_user(request: Request) -> Optional[Dict[str, Any]]:
    token = request.cookies.get(COOKIE_NAME)
    if not token:
        return None
    session = await db.sessions.find_one({"token": token})
    if not session:
        return None
    exp = aware(session.get("expires_at"))
    if exp and exp < now():
        await db.sessions.delete_many({"token": token})
        return None
    user = await db.users.find_one({"id": session["user_id"]})
    if not user or not user.get("is_active", True):
        return None
    return clean(user)


async def require_user(request: Request) -> Dict[str, Any]:
    user = await current_user(request)
    if not user:
        raise HTTPException(status_code=401, detail="not signed in")
    return user


async def require_admin(request: Request) -> Dict[str, Any]:
    user = await require_user(request)
    if user.get("role") != "admin":
        raise HTTPException(status_code=403, detail="admin access required")
    return user


async def require_subscription(request: Request) -> Dict[str, Any]:
    """Gate the trading terminal. 402 tells the frontend to show the paywall."""
    user = await require_user(request)
    if not is_subscribed(user):
        raise HTTPException(status_code=402, detail="an active subscription is required")
    return user
