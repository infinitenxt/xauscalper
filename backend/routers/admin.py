"""Admin panel API: users, subscriptions, plans, Razorpay keys, site settings."""
from __future__ import annotations

import uuid
from datetime import timedelta
from typing import Any, Dict, List

from fastapi import APIRouter, Depends, HTTPException, Query, Request

from lib import auth
from lib.db import db
from models.accounts import (
    AdminPasswordReset,
    AdminStats,
    GrantRequest,
    InviteCreate,
    InviteRow,
    PaymentRow,
    Plan,
    PlanPatch,
    RazorpayKeysPatch,
    SessionRow,
    SiteSettings,
    SiteSettingsPatch,
    UserPatch,
    UserPublic,
)
from routers.billing import activate, activate_mt5_live, activate_mt5_managed

router = APIRouter(prefix="/admin", tags=["admin"], dependencies=[Depends(auth.require_admin)])

SITE_DEFAULTS: Dict[str, Any] = {
    "id": "main",
    "site_name": "Bitcoin Paper Terminal",
    "tagline": "Educational BTCUSDT scalping intelligence",
    "support_email": "",
    "allow_registration": True,
    "invite_mode_enabled": True,
    "maintenance_mode": False,
    "trial_days": 0,
    "affiliate_commission_pct": 20.0,
    "razorpay_key_id": "",
    "razorpay_key_secret": "",
}


async def site_raw() -> Dict[str, Any]:
    doc = await db.site_settings.find_one({"id": "main"})
    if not doc:
        await db.site_settings.insert_one(dict(SITE_DEFAULTS))
        return dict(SITE_DEFAULTS)
    return {**SITE_DEFAULTS, **{k: v for k, v in doc.items() if k != "_id"}}


def site_public(raw: Dict[str, Any]) -> SiteSettings:
    return SiteSettings(
        site_name=raw.get("site_name", ""),
        tagline=raw.get("tagline", ""),
        support_email=raw.get("support_email", ""),
        allow_registration=bool(raw.get("allow_registration", True)),
        invite_mode_enabled=bool(raw.get("invite_mode_enabled", True)),
        maintenance_mode=bool(raw.get("maintenance_mode", False)),
        trial_days=int(raw.get("trial_days") or 0),
        affiliate_commission_pct=float(raw.get("affiliate_commission_pct", 20.0)),
        razorpay_key_id=raw.get("razorpay_key_id", ""),
        razorpay_key_secret_set=bool(raw.get("razorpay_key_secret")),
        razorpay_enabled=bool(raw.get("razorpay_key_id") and raw.get("razorpay_key_secret")),
    )


# ------------------------------------------------------------------- overview
@router.get("/stats", response_model=AdminStats)
async def stats() -> AdminStats:
    week = auth.now() - timedelta(days=7)
    users = await db.users.find({}).to_list(10_000)
    paid = await db.payments.find({"status": "paid"}).to_list(2000)
    return AdminStats(
        users_total=len(users),
        users_active=sum(1 for u in users if u.get("is_active", True)),
        subscribers=sum(1 for u in users if auth.is_subscribed(u)),
        admins=sum(1 for u in users if u.get("role") == "admin"),
        signed_in_now=await db.sessions.count_documents({}),
        new_users_7d=sum(1 for u in users if (auth.aware(u.get("created_at")) or auth.now()) >= week),
        revenue_inr=round(sum(float(p.get("amount_inr") or 0) for p in paid), 2),
        payments=len(paid),
        plans=await db.plans.count_documents({}),
        invites_pending=await db.invites.count_documents({"used": {"$ne": True}}),
    )


# -------------------------------------------------------------------- invites
@router.get("/invites", response_model=List[InviteRow])
async def list_invites(limit: int = Query(200, ge=1, le=500)) -> List[InviteRow]:
    docs = await db.invites.find({}).sort("created_at", -1).to_list(limit)
    return [InviteRow(**{k: v for k, v in d.items() if k not in ("_id", "user_id")}) for d in docs]


@router.post("/invites", response_model=InviteRow, status_code=201)
async def create_invite(body: InviteCreate, request: Request) -> InviteRow:
    """Only invited emails can register an account."""
    me = await auth.require_admin(request)
    email = body.email.lower().strip()
    if await db.users.find_one({"email": email}):
        raise HTTPException(status_code=409, detail="that email already has an account")
    if await db.invites.find_one({"email": email}):
        raise HTTPException(status_code=409, detail="that email is already invited")
    doc = {
        "email": email,
        "note": body.note.strip(),
        "used": False,
        "invited_by": me.get("email", ""),
        "created_at": auth.now(),
        "used_at": None,
    }
    await db.invites.insert_one(dict(doc))
    return InviteRow(**doc)


@router.delete("/invites/{email}")
async def delete_invite(email: str) -> Dict[str, str]:
    result = await db.invites.delete_one({"email": email.lower().strip()})
    if not result.deleted_count:
        raise HTTPException(status_code=404, detail="invite not found")
    return {"message": "invite revoked"}


# ---------------------------------------------------------------------- users
@router.get("/users", response_model=List[UserPublic])
async def list_users(
    q: str = Query("", max_length=80), limit: int = Query(200, ge=1, le=500)
) -> List[UserPublic]:
    query: Dict[str, Any] = {}
    if q:
        query = {"$or": [{"email": {"$regex": q, "$options": "i"}}, {"username": {"$regex": q, "$options": "i"}}]}
    docs = await db.users.find(query).sort("created_at", -1).to_list(limit)
    return [UserPublic(**auth.public_user({k: v for k, v in d.items() if k != "_id"})) for d in docs]


@router.patch("/users/{user_id}", response_model=UserPublic)
async def patch_user(user_id: str, body: UserPatch, request: Request) -> UserPublic:
    target = await db.users.find_one({"id": user_id})
    if not target:
        raise HTTPException(status_code=404, detail="user not found")
    me = await auth.require_admin(request)
    updates: Dict[str, Any] = {}
    if body.is_active is not None:
        if user_id == me["id"] and not body.is_active:
            raise HTTPException(status_code=400, detail="you cannot disable your own account")
        updates["is_active"] = body.is_active
    if body.role is not None:
        if body.role not in ("user", "admin"):
            raise HTTPException(status_code=400, detail="role must be 'user' or 'admin'")
        if user_id == me["id"] and body.role != "admin":
            raise HTTPException(status_code=400, detail="you cannot demote your own account")
        updates["role"] = body.role
    if updates:
        await db.users.update_one({"id": user_id}, {"$set": updates})
    if updates.get("is_active") is False:
        await db.sessions.delete_many({"user_id": user_id})
    fresh = await db.users.find_one({"id": user_id})
    return UserPublic(**auth.public_user({k: v for k, v in (fresh or {}).items() if k != "_id"}))


@router.delete("/users/{user_id}")
async def delete_user(user_id: str, request: Request) -> Dict[str, str]:
    me = await auth.require_admin(request)
    if user_id == me["id"]:
        raise HTTPException(status_code=400, detail="you cannot delete your own account")
    result = await db.users.delete_one({"id": user_id})
    if not result.deleted_count:
        raise HTTPException(status_code=404, detail="user not found")
    await db.sessions.delete_many({"user_id": user_id})
    return {"message": "user deleted"}


@router.post("/users/{user_id}/subscription", response_model=UserPublic)
async def manage_subscription(user_id: str, body: GrantRequest) -> UserPublic:
    target = await db.users.find_one({"id": user_id})
    if not target:
        raise HTTPException(status_code=404, detail="user not found")

    if body.revoke:
        await db.users.update_one({"id": user_id}, {"$set": {"subscription": {"status": "none"}}})
    elif body.plan_id:
        plan = await db.plans.find_one({"id": body.plan_id})
        if not plan:
            raise HTTPException(status_code=404, detail="plan not found")
        clean_plan = {k: v for k, v in plan.items() if k != "_id"}
        if plan.get("product_type") in ("mt5_live", "mt5_basic"):
            await activate_mt5_live(user_id, clean_plan, "admin_grant")
        elif plan.get("product_type") == "mt5_managed":
            await activate_mt5_managed(user_id, clean_plan, "admin_grant")
        else:
            await activate(user_id, clean_plan, "admin_grant")
    elif body.days:
        await activate(
            user_id,
            {"id": "manual", "name": f"{body.days}-day manual access", "days": int(body.days)},
            "admin_grant",
        )
    else:
        raise HTTPException(status_code=400, detail="provide plan_id, days, or revoke=true")

    fresh = await db.users.find_one({"id": user_id})
    return UserPublic(**auth.public_user({k: v for k, v in (fresh or {}).items() if k != "_id"}))


@router.post("/users/{user_id}/password")
async def reset_user_password(user_id: str, body: AdminPasswordReset) -> Dict[str, str]:
    """Force-set any account's password and sign its devices out."""
    target = await db.users.find_one({"id": user_id})
    if not target:
        raise HTTPException(status_code=404, detail="user not found")
    await db.users.update_one(
        {"id": user_id}, {"$set": {"password_hash": auth.hash_password(body.new_password)}}
    )
    await db.sessions.delete_many({"user_id": user_id})
    return {"message": f"password reset for {target.get('email', user_id)}"}


@router.get("/sessions", response_model=List[SessionRow])
async def list_sessions() -> List[SessionRow]:
    rows: List[SessionRow] = []
    for s in await db.sessions.find({}).sort("created_at", -1).to_list(200):
        user = await db.users.find_one({"id": s["user_id"]})
        rows.append(
            SessionRow(
                user_id=s["user_id"],
                email=(user or {}).get("email", "—"),
                username=(user or {}).get("username", "—"),
                user_agent=s.get("user_agent", ""),
                ip=s.get("ip", ""),
                created_at=s.get("created_at"),
                expires_at=s.get("expires_at"),
            )
        )
    return rows


@router.delete("/sessions/{user_id}")
async def revoke_sessions(user_id: str) -> Dict[str, str]:
    await db.sessions.delete_many({"user_id": user_id})
    return {"message": "device signed out"}


# ---------------------------------------------------------------------- plans
@router.get("/plans", response_model=List[Plan])
async def list_plans() -> List[Plan]:
    docs = await db.plans.find({}).sort("price_inr", 1).to_list(50)
    return [Plan(**{k: v for k, v in d.items() if k != "_id"}) for d in docs]


@router.post("/plans", response_model=Plan, status_code=201)
async def create_plan(body: Plan) -> Plan:
    plan = body.model_dump()
    plan["id"] = plan.get("id") or str(uuid.uuid4())
    if await db.plans.find_one({"id": plan["id"]}):
        raise HTTPException(status_code=409, detail="a plan with that id already exists")
    await db.plans.insert_one(dict(plan))
    return Plan(**plan)


@router.patch("/plans/{plan_id}", response_model=Plan)
async def patch_plan(plan_id: str, body: PlanPatch) -> Plan:
    updates = body.model_dump(exclude_none=True)
    if updates:
        await db.plans.update_one({"id": plan_id}, {"$set": updates})
    doc = await db.plans.find_one({"id": plan_id})
    if not doc:
        raise HTTPException(status_code=404, detail="plan not found")
    return Plan(**{k: v for k, v in doc.items() if k != "_id"})


@router.delete("/plans/{plan_id}")
async def delete_plan(plan_id: str) -> Dict[str, str]:
    result = await db.plans.delete_one({"id": plan_id})
    if not result.deleted_count:
        raise HTTPException(status_code=404, detail="plan not found")
    return {"message": "plan deleted"}


# -------------------------------------------------------- settings & payments
@router.get("/site-settings", response_model=SiteSettings)
async def read_site() -> SiteSettings:
    return site_public(await site_raw())


@router.put("/site-settings", response_model=SiteSettings)
async def write_site(body: SiteSettingsPatch) -> SiteSettings:
    updates = body.model_dump(exclude_none=True)
    if updates:
        await db.site_settings.update_one({"id": "main"}, {"$set": updates}, upsert=True)
    return site_public(await site_raw())


@router.put("/payment-keys", response_model=SiteSettings)
async def write_keys(body: RazorpayKeysPatch) -> SiteSettings:
    """Store Razorpay credentials. The secret is write-only — never returned."""
    updates: Dict[str, Any] = {}
    if body.razorpay_key_id is not None:
        updates["razorpay_key_id"] = body.razorpay_key_id.strip()
    if body.razorpay_key_secret is not None and body.razorpay_key_secret.strip():
        updates["razorpay_key_secret"] = body.razorpay_key_secret.strip()
    if updates:
        await db.site_settings.update_one({"id": "main"}, {"$set": updates}, upsert=True)
    return site_public(await site_raw())


@router.delete("/payment-keys", response_model=SiteSettings)
async def clear_keys() -> SiteSettings:
    await db.site_settings.update_one(
        {"id": "main"}, {"$set": {"razorpay_key_id": "", "razorpay_key_secret": ""}}, upsert=True
    )
    return site_public(await site_raw())


@router.get("/payments", response_model=List[PaymentRow])
async def list_payments(limit: int = Query(100, ge=1, le=500)) -> List[PaymentRow]:
    docs = await db.payments.find({}).sort("created_at", -1).to_list(limit)
    return [PaymentRow(**{k: v for k, v in d.items() if k != "_id"}) for d in docs]
