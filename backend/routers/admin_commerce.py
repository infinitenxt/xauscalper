"""Admin coupon, affiliate-ledger and withdrawal management."""
from __future__ import annotations

import uuid
from typing import Any, Dict, List

from fastapi import APIRouter, Depends, HTTPException
from pymongo import ReturnDocument

from lib import auth
from lib.db import db
from models.accounts import AffiliateEarning, Coupon, CouponCreate, CouponPatch, WithdrawalAction, WithdrawalRow

router = APIRouter(prefix="/admin", tags=["admin-commerce"], dependencies=[Depends(auth.require_admin)])


def _clean(doc: Dict[str, Any]) -> Dict[str, Any]:
    return {k: v for k, v in doc.items() if k != "_id"}


@router.get("/coupons", response_model=List[Coupon])
async def list_coupons() -> List[Coupon]:
    docs = await db.coupons.find({}).sort("created_at", -1).to_list(500)
    return [Coupon(**_clean(d)) for d in docs]


@router.post("/coupons", response_model=Coupon, status_code=201)
async def create_coupon(body: CouponCreate) -> Coupon:
    code = body.code.strip().upper()
    if await db.coupons.find_one({"code": code}):
        raise HTTPException(status_code=409, detail="coupon code already exists")
    if auth.aware(body.expires_at) <= auth.now():
        raise HTTPException(status_code=422, detail="coupon expiry must be in the future")
    doc = {
        "id": str(uuid.uuid4()),
        **body.model_dump(),
        "code": code,
        "claims_used": 0,
        "claims_reserved": 0,
        "created_at": auth.now(),
    }
    await db.coupons.insert_one(dict(doc))
    return Coupon(**doc)


@router.patch("/coupons/{coupon_id}", response_model=Coupon)
async def patch_coupon(coupon_id: str, body: CouponPatch) -> Coupon:
    updates = body.model_dump(exclude_none=True)
    current = await db.coupons.find_one({"id": coupon_id})
    if not current:
        raise HTTPException(status_code=404, detail="coupon not found")
    if "claim_limit" in updates and int(updates["claim_limit"]) < int(current.get("claims_used") or 0) + int(current.get("claims_reserved") or 0):
        raise HTTPException(status_code=422, detail="claim limit cannot be below used and reserved claims")
    if updates:
        await db.coupons.update_one({"id": coupon_id}, {"$set": updates})
    fresh = await db.coupons.find_one({"id": coupon_id}) or current
    return Coupon(**_clean(fresh))


@router.delete("/coupons/{coupon_id}")
async def delete_coupon(coupon_id: str) -> Dict[str, str]:
    coupon = await db.coupons.find_one({"id": coupon_id})
    if not coupon:
        raise HTTPException(status_code=404, detail="coupon not found")
    if int(coupon.get("claims_used") or 0) or int(coupon.get("claims_reserved") or 0):
        await db.coupons.update_one({"id": coupon_id}, {"$set": {"active": False}})
        return {"message": "coupon has history and was deactivated"}
    await db.coupons.delete_one({"id": coupon_id})
    return {"message": "coupon deleted"}


@router.get("/affiliate/earnings", response_model=List[AffiliateEarning])
async def list_affiliate_earnings() -> List[AffiliateEarning]:
    docs = await db.affiliate_earnings.find({}).sort("created_at", -1).to_list(500)
    return [AffiliateEarning(**_clean(d)) for d in docs]


@router.get("/affiliate/withdrawals", response_model=List[WithdrawalRow])
async def list_withdrawals() -> List[WithdrawalRow]:
    docs = await db.affiliate_withdrawals.find({}).sort("created_at", -1).to_list(500)
    return [WithdrawalRow(**_clean(d)) for d in docs]


@router.patch("/affiliate/withdrawals/{withdrawal_id}", response_model=WithdrawalRow)
async def update_withdrawal(withdrawal_id: str, body: WithdrawalAction) -> WithdrawalRow:
    current = await db.affiliate_withdrawals.find_one({"id": withdrawal_id})
    if not current:
        raise HTTPException(status_code=404, detail="withdrawal not found")
    action = body.action
    old_status = str(current.get("status"))
    allowed = {
        "approve": old_status == "pending",
        "reject": old_status in ("pending", "approved"),
        "paid": old_status == "approved",
    }
    if not allowed[action]:
        raise HTTPException(status_code=409, detail=f"cannot {action} a {old_status} withdrawal")
    new_status = "approved" if action == "approve" else action
    updated = await db.affiliate_withdrawals.find_one_and_update(
        {"id": withdrawal_id, "status": old_status},
        {"$set": {"status": new_status, "note": body.note.strip(), "updated_at": auth.now()}},
        return_document=ReturnDocument.AFTER,
    )
    if not updated:
        raise HTTPException(status_code=409, detail="withdrawal changed; refresh and retry")
    amount = float(updated.get("amount_inr") or 0.0)
    if action == "reject":
        await db.affiliate_accounts.update_one(
            {"user_id": updated["user_id"]},
            {"$inc": {"available_balance": amount, "pending_withdrawal": -amount}},
        )
    elif action == "paid":
        await db.affiliate_accounts.update_one(
            {"user_id": updated["user_id"]},
            {"$inc": {"pending_withdrawal": -amount, "withdrawn_total": amount}},
        )
    return WithdrawalRow(**_clean(updated))