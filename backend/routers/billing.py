"""Subscription plans and Razorpay checkout.

Razorpay credentials are entered by an admin at runtime and stored in the
``site_settings`` document, so the client is constructed per request from the DB
rather than from environment variables. With no keys configured the paid flow is
cleanly disabled and an admin can still grant access manually.
"""
from __future__ import annotations

import asyncio
import uuid
from datetime import timedelta
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, HTTPException, Request

from lib import auth
from lib.db import db
from models.accounts import (
    BillingStatus,
    OrderRequest,
    OrderResponse,
    Plan,
    SubscriptionInfo,
    VerifyRequest,
)

router = APIRouter(prefix="/billing", tags=["billing"])


async def site_doc() -> Dict[str, Any]:
    return await db.site_settings.find_one({"id": "main"}) or {}


def razorpay_ready(site: Dict[str, Any]) -> bool:
    return bool(site.get("razorpay_key_id") and site.get("razorpay_key_secret"))


async def active_plans() -> List[Dict[str, Any]]:
    docs = await db.plans.find({"is_active": True}).sort("price_inr", 1).to_list(20)
    return [{k: v for k, v in d.items() if k != "_id"} for d in docs]


async def get_plan(plan_id: str) -> Dict[str, Any]:
    doc = await db.plans.find_one({"id": plan_id, "is_active": True})
    if not doc:
        raise HTTPException(status_code=404, detail="plan not found")
    return {k: v for k, v in doc.items() if k != "_id"}


async def activate(user_id: str, plan: Dict[str, Any], source: str) -> None:
    """Extend from the current expiry when still active, else start now."""
    user = await db.users.find_one({"id": user_id})
    base = auth.now()
    if user:
        exp = auth.aware((user.get("subscription") or {}).get("expires_at"))
        if exp and exp > base:
            base = exp
    await db.users.update_one(
        {"id": user_id},
        {
            "$set": {
                "subscription": {
                    "plan_id": plan["id"],
                    "plan_name": plan["name"],
                    "status": "active",
                    "source": source,
                    "started_at": auth.now(),
                    "expires_at": base + timedelta(days=int(plan["days"])),
                }
            }
        },
    )


@router.get("/status", response_model=BillingStatus)
async def status(request: Request) -> BillingStatus:
    user = await auth.require_user(request)
    site = await site_doc()
    ready = razorpay_ready(site)
    return BillingStatus(
        plans=[Plan(**p) for p in await active_plans()],
        subscription=SubscriptionInfo(**auth.public_user(user)["subscription"]),
        razorpay_enabled=ready,
        razorpay_key_id=site.get("razorpay_key_id") if ready else None,
        message=(
            "Card and UPI checkout is live."
            if ready
            else "Online payment is not configured yet — ask an admin to enable Razorpay or grant access manually."
        ),
    )


@router.post("/order", response_model=OrderResponse)
async def create_order(body: OrderRequest, request: Request) -> OrderResponse:
    user = await auth.require_user(request)
    site = await site_doc()
    if not razorpay_ready(site):
        raise HTTPException(status_code=503, detail="online payment is not configured")
    plan = await get_plan(body.plan_id)
    amount = int(round(float(plan["price_inr"]) * 100))  # paise

    def _create() -> Dict[str, Any]:
        import razorpay

        client = razorpay.Client(auth=(site["razorpay_key_id"], site["razorpay_key_secret"]))
        return client.order.create(
            {
                "amount": amount,
                "currency": "INR",
                "payment_capture": 1,
                "receipt": f"gt-{uuid.uuid4().hex[:18]}",  # <= 40 chars
                "notes": {"user_id": user["id"], "plan_id": plan["id"]},
            }
        )

    try:
        order = await asyncio.to_thread(_create)
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=502, detail=f"razorpay order failed: {exc}") from exc

    await db.payments.insert_one(
        {
            "id": str(uuid.uuid4()),
            "user_id": user["id"],
            "email": user["email"],
            "plan_id": plan["id"],
            "plan_name": plan["name"],
            "amount_inr": float(plan["price_inr"]),
            "status": "created",
            "provider": "razorpay",
            "order_id": order["id"],
            "payment_id": None,
            "created_at": auth.now(),
        }
    )
    return OrderResponse(
        order_id=order["id"],
        amount=amount,
        currency="INR",
        key_id=site["razorpay_key_id"],
        plan=Plan(**plan),
    )


@router.post("/verify", response_model=SubscriptionInfo)
async def verify(body: VerifyRequest, request: Request) -> SubscriptionInfo:
    user = await auth.require_user(request)
    site = await site_doc()
    if not razorpay_ready(site):
        raise HTTPException(status_code=503, detail="online payment is not configured")
    plan = await get_plan(body.plan_id)

    def _verify() -> None:
        import razorpay

        client = razorpay.Client(auth=(site["razorpay_key_id"], site["razorpay_key_secret"]))
        client.utility.verify_payment_signature(
            {
                "razorpay_order_id": body.razorpay_order_id,
                "razorpay_payment_id": body.razorpay_payment_id,
                "razorpay_signature": body.razorpay_signature,
            }
        )

    try:
        await asyncio.to_thread(_verify)
    except Exception as exc:  # noqa: BLE001
        await db.payments.update_one(
            {"order_id": body.razorpay_order_id}, {"$set": {"status": "signature_failed"}}
        )
        raise HTTPException(status_code=400, detail="payment signature verification failed") from exc

    await db.payments.update_one(
        {"order_id": body.razorpay_order_id},
        {"$set": {"status": "paid", "payment_id": body.razorpay_payment_id, "paid_at": auth.now()}},
    )
    await activate(user["id"], plan, "razorpay")
    fresh: Optional[Dict[str, Any]] = auth.clean(await db.users.find_one({"id": user["id"]}))
    return SubscriptionInfo(**auth.public_user(fresh or user)["subscription"])
