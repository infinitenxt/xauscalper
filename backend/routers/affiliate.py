"""Subscriber affiliate profile, bank details, earnings and withdrawals."""
from __future__ import annotations

import uuid
from typing import Any, Dict, List

from fastapi import APIRouter, HTTPException, Request
from pymongo import ReturnDocument

from lib import affiliate as affiliate_lib, auth
from lib.db import db
from models.accounts import (
    AffiliateEarning,
    AffiliateSummary,
    BankDetailsPatch,
    BankDetailsPublic,
    WithdrawalCreate,
    WithdrawalRow,
)

router = APIRouter(prefix="/affiliate", tags=["affiliate"])


def _clean(doc: Dict[str, Any]) -> Dict[str, Any]:
    return {k: v for k, v in doc.items() if k != "_id"}


def _public_bank(bank: Dict[str, Any]) -> BankDetailsPublic:
    number = str(bank.get("account_number") or "")
    return BankDetailsPublic(
        account_holder=str(bank.get("account_holder") or ""),
        bank_name=str(bank.get("bank_name") or ""),
        account_last4=number[-4:] if number else "",
        ifsc_code=str(bank.get("ifsc_code") or ""),
        configured=all(bank.get(k) for k in ("account_holder", "bank_name", "account_number", "ifsc_code")),
    )


@router.get("/summary", response_model=AffiliateSummary)
async def summary(request: Request) -> AffiliateSummary:
    user = await auth.require_user(request)
    code = await affiliate_lib.ensure_referral_code(user)
    account = await affiliate_lib.ensure_account(user["id"])
    site = await db.site_settings.find_one({"id": "main"}) or {}
    referrals = await db.users.count_documents({"referred_by_user_id": user["id"]})
    paid_referrals = len(await db.affiliate_earnings.distinct("referred_user_id", {"referrer_user_id": user["id"]}))
    return AffiliateSummary(
        referral_code=code,
        referral_path=f"/register?ref={code}",
        commission_pct=float(site.get("affiliate_commission_pct", 20.0)),
        referred_users=referrals,
        paid_referrals=paid_referrals,
        earned_total=round(float(account.get("earned_total") or 0.0), 2),
        available_balance=round(float(account.get("available_balance") or 0.0), 2),
        pending_withdrawal=round(float(account.get("pending_withdrawal") or 0.0), 2),
        withdrawn_total=round(float(account.get("withdrawn_total") or 0.0), 2),
        bank=_public_bank(account.get("bank") or {}),
    )


@router.put("/bank", response_model=BankDetailsPublic)
async def save_bank(body: BankDetailsPatch, request: Request) -> BankDetailsPublic:
    user = await auth.require_user(request)
    account = await affiliate_lib.ensure_account(user["id"])
    bank = dict(account.get("bank") or {})
    for key, value in body.model_dump(exclude_none=True).items():
        bank[key] = value.strip().upper() if key == "ifsc_code" else value.strip()
    if not all(bank.get(k) for k in ("account_holder", "bank_name", "account_number", "ifsc_code")):
        raise HTTPException(status_code=422, detail="complete all bank details before saving")
    await db.affiliate_accounts.update_one(
        {"user_id": user["id"]}, {"$set": {"bank": bank, "bank_updated_at": auth.now()}}
    )
    return _public_bank(bank)


@router.get("/earnings", response_model=List[AffiliateEarning])
async def earnings(request: Request) -> List[AffiliateEarning]:
    user = await auth.require_user(request)
    docs = await db.affiliate_earnings.find({"referrer_user_id": user["id"]}).sort("created_at", -1).to_list(200)
    return [AffiliateEarning(**_clean(d)) for d in docs]


@router.get("/withdrawals", response_model=List[WithdrawalRow])
async def withdrawals(request: Request) -> List[WithdrawalRow]:
    user = await auth.require_user(request)
    docs = await db.affiliate_withdrawals.find({"user_id": user["id"]}).sort("created_at", -1).to_list(100)
    return [WithdrawalRow(**_clean(d)) for d in docs]


@router.post("/withdrawals", response_model=WithdrawalRow, status_code=201)
async def request_withdrawal(body: WithdrawalCreate, request: Request) -> WithdrawalRow:
    user = await auth.require_user(request)
    amount = round(float(body.amount_inr), 2)
    account = await db.affiliate_accounts.find_one_and_update(
        {
            "user_id": user["id"],
            "available_balance": {"$gte": amount},
            "bank.account_number": {"$exists": True, "$ne": ""},
        },
        {"$inc": {"available_balance": -amount, "pending_withdrawal": amount}},
        return_document=ReturnDocument.AFTER,
    )
    if not account:
        raise HTTPException(status_code=400, detail="insufficient balance or bank details are incomplete")
    doc = {
        "id": str(uuid.uuid4()),
        "user_id": user["id"],
        "user_email": user.get("email", ""),
        "amount_inr": amount,
        "status": "pending",
        "bank": dict(account.get("bank") or {}),
        "note": "",
        "created_at": auth.now(),
        "updated_at": auth.now(),
    }
    try:
        await db.affiliate_withdrawals.insert_one(dict(doc))
    except Exception:
        await db.affiliate_accounts.update_one(
            {"user_id": user["id"]},
            {"$inc": {"available_balance": amount, "pending_withdrawal": -amount}},
        )
        raise
    return WithdrawalRow(**doc)