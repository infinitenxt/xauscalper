"""One-level affiliate attribution and commission ledger helpers."""
from __future__ import annotations

import re
import secrets
import uuid
from typing import Any, Dict

from pymongo.errors import DuplicateKeyError

from lib import auth
from lib.db import db


def _base_code(username: str) -> str:
    clean = re.sub(r"[^A-Z0-9]", "", username.upper())[:5]
    return clean or "bitcoin"


async def new_referral_code(username: str) -> str:
    """Generate a short, unique code without exposing a user's id."""
    base = _base_code(username)
    for _ in range(20):
        code = f"{base}{secrets.token_hex(3).upper()}"
        if not await db.users.find_one({"referral_code": code}, {"_id": 1}):
            return code
    return uuid.uuid4().hex[:12].upper()


async def ensure_referral_code(user: Dict[str, Any]) -> str:
    current = str(user.get("referral_code") or "").strip().upper()
    if current:
        return current
    for _ in range(5):
        code = await new_referral_code(str(user.get("username") or "bitcoin"))
        try:
            result = await db.users.update_one(
                {"id": user["id"], "$or": [{"referral_code": {"$exists": False}}, {"referral_code": ""}]},
                {"$set": {"referral_code": code}},
            )
        except DuplicateKeyError:
            continue
        if result.modified_count:
            return code
        fresh = await db.users.find_one({"id": user["id"]}, {"referral_code": 1})
        if fresh and fresh.get("referral_code"):
            return str(fresh["referral_code"])
    raise RuntimeError("could not allocate a unique referral code")


async def ensure_account(user_id: str) -> Dict[str, Any]:
    await db.affiliate_accounts.update_one(
        {"user_id": user_id},
        {
            "$setOnInsert": {
                "id": str(uuid.uuid4()),
                "user_id": user_id,
                "earned_total": 0.0,
                "available_balance": 0.0,
                "pending_withdrawal": 0.0,
                "withdrawn_total": 0.0,
                "bank": {},
                "created_at": auth.now(),
            }
        },
        upsert=True,
    )
    return await db.affiliate_accounts.find_one({"user_id": user_id}) or {}


async def credit_payment(payment: Dict[str, Any], buyer: Dict[str, Any], commission_pct: float) -> float:
    """Credit the permanent one-level referrer once per verified payment."""
    referrer_id = buyer.get("referred_by_user_id")
    if not referrer_id or referrer_id == buyer.get("id"):
        return 0.0
    pct = max(0.0, min(100.0, float(commission_pct)))
    commission = round(float(payment.get("amount_inr") or 0.0) * pct / 100, 2)
    if commission <= 0:
        return 0.0
    earning = {
        "id": str(uuid.uuid4()),
        "referrer_user_id": referrer_id,
        "referred_user_id": buyer["id"],
        "referred_user_email": buyer.get("email", ""),
        "plan_id": payment.get("plan_id", ""),
        "plan_name": payment.get("plan_name", ""),
        "purchase_amount_inr": float(payment.get("amount_inr") or 0.0),
        "commission_pct": pct,
        "commission_inr": commission,
        "payment_id": payment.get("payment_id") or payment.get("order_id"),
        "order_id": payment.get("order_id"),
        "created_at": auth.now(),
    }
    try:
        await db.affiliate_earnings.insert_one(earning)
    except DuplicateKeyError:
        return 0.0
    await ensure_account(str(referrer_id))
    await db.affiliate_accounts.update_one(
        {"user_id": referrer_id},
        {"$inc": {"earned_total": commission, "available_balance": commission}},
    )
    await db.payments.update_one(
        {"id": payment["id"]},
        {"$set": {"affiliate_commission_inr": commission, "referrer_user_id": referrer_id}},
    )
    return commission