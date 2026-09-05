"""Subscription plans and Razorpay checkout.

Razorpay credentials are entered by an admin at runtime and stored in the
``site_settings`` document, so the client is constructed per request from the DB
rather than from environment variables. With no keys configured the paid flow is
cleanly disabled and an admin can still grant access manually.
"""
from __future__ import annotations

import asyncio
import logging
import os
import uuid
from datetime import timedelta
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, HTTPException, Request
from pymongo import ReturnDocument

from lib import affiliate as affiliate_lib, auth
from lib.db import db
from models.accounts import (
    BillingStatus,
    CouponPreview,
    CouponPreviewRequest,
    OrderRequest,
    OrderResponse,
    Plan,
    Mt5LiveEntitlement,
    SubscriptionInfo,
    VerifyRequest,
)

router = APIRouter(prefix="/billing", tags=["billing"])
logger = logging.getLogger("billing")


async def site_doc() -> Dict[str, Any]:
    return await db.site_settings.find_one({"id": "main"}) or {}


def razorpay_ready(site: Dict[str, Any]) -> bool:
    return bool(site.get("razorpay_key_id") and site.get("razorpay_key_secret"))


async def active_plans() -> List[Dict[str, Any]]:
    docs = await db.plans.find(
        {"is_active": True, "$or": [{"product_type": "base"}, {"product_type": {"$exists": False}}]}
    ).sort("price_inr", 1).to_list(20)
    return [{k: v for k, v in d.items() if k != "_id"} for d in docs]


async def get_plan(plan_id: str) -> Dict[str, Any]:
    doc = await db.plans.find_one({"id": plan_id, "is_active": True})
    if not doc:
        raise HTTPException(status_code=404, detail="plan not found")
    return {k: v for k, v in doc.items() if k != "_id"}


async def _release_expired_coupon_reservations() -> None:
    expired = await db.payments.find(
        {
            "status": "created",
            "coupon_reserved": True,
            "reservation_expires_at": {"$lte": auth.now()},
        }
    ).to_list(200)
    for payment in expired:
        released = await db.payments.update_one(
            {"id": payment["id"], "status": "created", "coupon_reserved": True},
            {"$set": {"status": "expired", "coupon_reserved": False}},
        )
        if released.modified_count and payment.get("coupon_id"):
            await db.coupons.update_one(
                {"id": payment["coupon_id"], "claims_reserved": {"$gt": 0}},
                {"$inc": {"claims_reserved": -1}},
            )


async def _coupon(code: str, plan_id: Optional[str] = None) -> Dict[str, Any]:
    normalized = code.strip().upper()
    doc = await db.coupons.find_one({"code": normalized})
    if not doc or not doc.get("active", True):
        raise HTTPException(status_code=400, detail="coupon is invalid or inactive")
    expires = auth.aware(doc.get("expires_at"))
    if not expires or expires <= auth.now():
        raise HTTPException(status_code=400, detail="coupon has expired")
    eligible = list(doc.get("eligible_plan_ids") or [])
    if plan_id and eligible and plan_id not in eligible:
        raise HTTPException(status_code=400, detail="coupon is not valid for this plan")
    used = int(doc.get("claims_used") or 0)
    reserved = int(doc.get("claims_reserved") or 0)
    if used + reserved >= int(doc.get("claim_limit") or 0):
        raise HTTPException(status_code=409, detail="coupon claim limit has been reached")
    return doc


async def _reserve_coupon(code: str, plan_id: str) -> Dict[str, Any]:
    await _release_expired_coupon_reservations()
    for _ in range(3):
        doc = await _coupon(code, plan_id)
        used = int(doc.get("claims_used") or 0)
        reserved = int(doc.get("claims_reserved") or 0)
        result = await db.coupons.find_one_and_update(
            {
                "id": doc["id"],
                "active": True,
                "$expr": {
                    "$lt": [
                        {"$add": [{"$ifNull": ["$claims_used", 0]}, {"$ifNull": ["$claims_reserved", 0]}]},
                        "$claim_limit",
                    ]
                },
            },
            {"$inc": {"claims_reserved": 1}},
            return_document=ReturnDocument.AFTER,
        )
        if result:
            return result
        if used + reserved >= int(doc.get("claim_limit") or 0):
            break
    raise HTTPException(status_code=409, detail="coupon claim limit has been reached")


async def _release_coupon(coupon_id: Optional[str]) -> None:
    if coupon_id:
        await db.coupons.update_one(
            {"id": coupon_id, "claims_reserved": {"$gt": 0}},
            {"$inc": {"claims_reserved": -1}},
        )


async def _finalize_coupon(payment: Dict[str, Any]) -> None:
    if not payment.get("coupon_reserved") or not payment.get("coupon_id"):
        return
    claimed = await db.payments.update_one(
        {"id": payment["id"], "coupon_reserved": True},
        {"$set": {"coupon_reserved": False, "coupon_claimed_at": auth.now()}},
    )
    if claimed.modified_count:
        await db.coupons.update_one(
            {"id": payment["coupon_id"]},
            {"$inc": {"claims_reserved": -1, "claims_used": 1}},
        )


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


async def activate_mt5_live(user_id: str, plan: Dict[str, Any], source: str) -> None:
    await activate_mt5_plan(user_id, plan, source, "mt5_basic_subscription")


async def activate_mt5_managed(user_id: str, plan: Dict[str, Any], source: str) -> None:
    await activate_mt5_plan(user_id, plan, source, "mt5_managed_subscription")


async def activate_mt5_plan(user_id: str, plan: Dict[str, Any], source: str, field: str) -> None:
    user = await db.users.find_one({"id": user_id})
    base = auth.now()
    if user:
        legacy = user.get("mt5_live_subscription") if field == "mt5_basic_subscription" else None
        exp = auth.aware((user.get(field) or legacy or {}).get("expires_at"))
        if exp and exp > base:
            base = exp
    await db.users.update_one(
        {"id": user_id},
        {
            "$set": {
                field: {
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
    mt5_basic_doc = await db.plans.find_one({"product_type": {"$in": ["mt5_basic", "mt5_live"]}, "is_active": True})
    mt5_managed_doc = await db.plans.find_one({"product_type": "mt5_managed", "is_active": True})
    basic_plan = Plan(**{k: v for k, v in mt5_basic_doc.items() if k != "_id"}) if mt5_basic_doc else None
    managed_plan = Plan(**{k: v for k, v in mt5_managed_doc.items() if k != "_id"}) if mt5_managed_doc else None
    basic_entitlement = Mt5LiveEntitlement(**auth.mt5_basic_public(user))
    managed_entitlement = Mt5LiveEntitlement(**auth.mt5_managed_public(user))
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
        mt5_live_plan=basic_plan,
        mt5_live_entitlement=basic_entitlement,
        mt5_basic_plan=basic_plan,
        mt5_basic_entitlement=basic_entitlement,
        mt5_managed_plan=managed_plan,
        mt5_managed_entitlement=managed_entitlement,
        metaapi_configured=bool(os.environ.get("METAAPI_TOKEN")),
    )


@router.post("/coupon", response_model=CouponPreview)
async def preview_coupon(body: CouponPreviewRequest, request: Request) -> CouponPreview:
    await auth.require_user(request)
    await _release_expired_coupon_reservations()
    doc = await _coupon(body.coupon_code)
    remaining = int(doc.get("claim_limit") or 0) - int(doc.get("claims_used") or 0) - int(doc.get("claims_reserved") or 0)
    return CouponPreview(
        code=doc["code"],
        discount_pct=float(doc["discount_pct"]),
        eligible_plan_ids=list(doc.get("eligible_plan_ids") or []),
        claims_remaining=max(0, remaining),
        expires_at=auth.aware(doc["expires_at"]),
    )


@router.post("/order", response_model=OrderResponse)
async def create_order(body: OrderRequest, request: Request) -> OrderResponse:
    user = await auth.require_user(request)
    site = await site_doc()
    if not razorpay_ready(site):
        raise HTTPException(status_code=503, detail="online payment is not configured")
    plan = await get_plan(body.plan_id)
    coupon = await _reserve_coupon(body.coupon_code, plan["id"]) if body.coupon_code else None
    original_amount = float(plan["price_inr"])
    discount = round(original_amount * float((coupon or {}).get("discount_pct") or 0.0) / 100, 2)
    final_amount = round(original_amount - discount, 2)
    amount = int(round(final_amount * 100))  # paise

    

    def _create() -> Dict[str, Any]:
        import razorpay

        client = razorpay.Client(auth=(site["razorpay_key_id"], site["razorpay_key_secret"]))
        
        return client.order.create(
            {
                "amount": amount,
                "currency": "INR",
                "payment_capture": 1,
                "receipt": f"gt-{uuid.uuid4().hex[:18]}",  # <= 40 chars
                "notes": {
                    "user_id": user["id"],
                    "plan_id": plan["id"],
                    "coupon_code": (coupon or {}).get("code", ""),
                },
            }
        )

    try:
        order = await asyncio.to_thread(_create)
    except Exception as exc:  # noqa: BLE001
        await _release_coupon((coupon or {}).get("id"))
        raise HTTPException(status_code=502, detail=f"razorpay order failed: {exc}") from exc

    payment = {
            "id": str(uuid.uuid4()),
            "user_id": user["id"],
            "email": user["email"],
            "plan_id": plan["id"],
            "plan_name": plan["name"],
            "product_type": plan.get("product_type", "base"),
            "plan_days": int(plan["days"]),
            "amount_inr": final_amount,
            "original_amount_inr": original_amount,
            "discount_inr": discount,
            "coupon_id": (coupon or {}).get("id"),
            "coupon_code": (coupon or {}).get("code"),
            "coupon_reserved": bool(coupon),
            "reservation_expires_at": auth.now() + timedelta(hours=2) if coupon else None,
            "affiliate_commission_inr": 0.0,
            "status": "created",
            "provider": "razorpay",
            "order_id": order["id"],
            "payment_id": None,
            "created_at": auth.now(),
        }
    try:
        await db.payments.insert_one(payment)
    except Exception:
        await _release_coupon((coupon or {}).get("id"))
        raise
    return OrderResponse(
        order_id=order["id"],
        amount=amount,
        currency="INR",
        key_id=site["razorpay_key_id"],
        plan=Plan(**plan),
        original_amount_inr=original_amount,
        discount_inr=discount,
        coupon_code=(coupon or {}).get("code"),
    )


@router.post("/verify", response_model=SubscriptionInfo)
async def verify(body: VerifyRequest, request: Request) -> SubscriptionInfo:
    user = await auth.require_user(request)
    site = await site_doc()
    if not razorpay_ready(site):
        raise HTTPException(status_code=503, detail="online payment is not configured")
    payment = await db.payments.find_one(
        {"order_id": body.razorpay_order_id, "user_id": user["id"]}
    )
    if not payment:
        raise HTTPException(status_code=404, detail="payment order not found")
    if payment.get("plan_id") != body.plan_id:
        raise HTTPException(status_code=400, detail="payment order does not match this plan")
    if payment.get("status") == "paid":
        fresh = auth.clean(await db.users.find_one({"id": user["id"]}))
        return SubscriptionInfo(**auth.public_user(fresh or user)["subscription"])
    plan = {
        "id": payment["plan_id"],
        "name": payment.get("plan_name", payment["plan_id"]),
        "days": int(payment.get("plan_days") or 0),
        "product_type": payment.get("product_type", "base"),
    }
    if plan["days"] <= 0:
        raise HTTPException(status_code=409, detail="payment order has no valid subscription duration")

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
            {"id": payment["id"]}, {"$set": {"status": "signature_failed"}}
        )
        raise HTTPException(status_code=400, detail="payment signature verification failed") from exc

    processing = await db.payments.find_one_and_update(
        {"id": payment["id"], "status": {"$in": ["created", "signature_failed", "expired"]}},
        {"$set": {"status": "processing", "payment_id": body.razorpay_payment_id, "verified_at": auth.now()}},
        return_document=ReturnDocument.AFTER,
    )
    if not processing:
        fresh_payment = await db.payments.find_one({"id": payment["id"]}) or {}
        if fresh_payment.get("status") == "paid":
            fresh = auth.clean(await db.users.find_one({"id": user["id"]}))
            return SubscriptionInfo(**auth.public_user(fresh or user)["subscription"])
        raise HTTPException(status_code=409, detail="payment verification is already in progress")

    if plan["product_type"] in ("mt5_live", "mt5_basic"):
        await activate_mt5_live(user["id"], plan, "razorpay")
    elif plan["product_type"] == "mt5_managed":
        await activate_mt5_managed(user["id"], plan, "razorpay")
    else:
        await activate(user["id"], plan, "razorpay")
    await _finalize_coupon(processing)
    try:
        await affiliate_lib.credit_payment(
            {**processing, "payment_id": body.razorpay_payment_id},
            user,
            float(site.get("affiliate_commission_pct", 20.0)),
        )
    except Exception as exc:  # noqa: BLE001
        logger.exception("affiliate credit failed for order %s: %s", body.razorpay_order_id, exc)
    await db.payments.update_one(
        {"id": payment["id"]},
        {"$set": {"status": "paid", "paid_at": auth.now()}},
    )
    fresh: Optional[Dict[str, Any]] = auth.clean(await db.users.find_one({"id": user["id"]}))
    return SubscriptionInfo(**auth.public_user(fresh or user)["subscription"])
