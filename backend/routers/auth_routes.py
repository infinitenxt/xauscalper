"""Registration, login (one device at a time), logout, session identity."""
from __future__ import annotations

import uuid
from typing import Any, Dict

from fastapi import APIRouter, HTTPException, Request, Response

from lib import auth
from lib.db import db
from models.accounts import AuthResponse, LoginRequest, RegisterRequest, UserPublic

router = APIRouter(prefix="/auth", tags=["auth"])


async def _site() -> Dict[str, Any]:
    return await db.site_settings.find_one({"id": "main"}) or {}


@router.post("/register", response_model=AuthResponse, status_code=201)
async def register(body: RegisterRequest, request: Request, response: Response) -> AuthResponse:
    site = await _site()
    if site and site.get("allow_registration") is False:
        raise HTTPException(status_code=403, detail="registration is currently closed")

    email = body.email.lower().strip()
    if await db.users.find_one({"email": email}):
        raise HTTPException(status_code=409, detail="that email is already registered")
    if await db.users.find_one({"username": body.username}):
        raise HTTPException(status_code=409, detail="that username is taken")

    trial_days = int(site.get("trial_days") or 0)
    subscription: Dict[str, Any] = {"status": "none"}
    if trial_days > 0:
        from datetime import timedelta

        subscription = {
            "plan_id": "trial",
            "plan_name": f"{trial_days}-day trial",
            "status": "active",
            "source": "trial",
            "started_at": auth.now(),
            "expires_at": auth.now() + timedelta(days=trial_days),
        }

    user = {
        "id": str(uuid.uuid4()),
        "email": email,
        "username": body.username.strip(),
        "password_hash": auth.hash_password(body.password),
        "role": "user",
        "is_active": True,
        "created_at": auth.now(),
        "subscription": subscription,
    }
    await db.users.insert_one(dict(user))
    token = await auth.create_session(user["id"], request)
    auth.set_cookie(response, token)
    return AuthResponse(
        user=UserPublic(**auth.public_user(user)),
        message="Account created. Choose a plan to unlock the terminal."
        if subscription["status"] != "active"
        else f"Account created with a {trial_days}-day trial.",
    )


@router.post("/login", response_model=AuthResponse)
async def login(body: LoginRequest, request: Request, response: Response) -> AuthResponse:
    user = await db.users.find_one({"email": body.email.lower().strip()})
    if not user or not auth.verify_password(body.password, user.get("password_hash", "")):
        raise HTTPException(status_code=401, detail="invalid email or password")
    if not user.get("is_active", True):
        raise HTTPException(status_code=403, detail="this account has been disabled")

    had_session = await db.sessions.count_documents({"user_id": user["id"]})
    token = await auth.create_session(user["id"], request)
    auth.set_cookie(response, token)
    return AuthResponse(
        user=UserPublic(**auth.public_user(auth.clean(user) or {})),
        message=(
            "Signed in. Your previous device has been signed out — one active login per account."
            if had_session
            else "Signed in."
        ),
    )


@router.post("/logout")
async def logout(request: Request, response: Response) -> Dict[str, str]:
    await auth.destroy_session(request.cookies.get(auth.COOKIE_NAME))
    auth.clear_cookie(response)
    return {"message": "signed out"}


@router.get("/me", response_model=UserPublic)
async def me(request: Request) -> UserPublic:
    user = await auth.require_user(request)
    return UserPublic(**auth.public_user(user))
