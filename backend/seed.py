"""Idempotent seed: the admin account, default subscription plans, site settings.

Runs on every boot from server.py's lifespan. Safe to run repeatedly — it only
creates what is missing and never overwrites live data.
"""
from __future__ import annotations

import logging
import uuid
from typing import Any, Dict, List

from lib import auth
from lib.db import db

logger = logging.getLogger("seed")

ADMIN_EMAIL = "admin@infinitenxt.com"
ADMIN_USERNAME = "Admin"
ADMIN_PASSWORD = "Harsh@10576"
# Older builds seeded these — migrated in-place to the values above.
LEGACY_ADMIN_EMAILS = ["admin@goldterminal.app"]
LEGACY_ADMIN_USERNAMES = ["admin"]

PLANS: List[Dict[str, Any]] = [
    {
        "id": "monthly",
        "name": "Monthly",
        "price_inr": 999.0,
        "days": 30,
        "features": [
            "Live BTCUSDT scalping signals",
            "Auto paper trading with full risk management",
            "AI explanation on every trade",
            "Voice announcements and market commentary",
            "Strategy backtesting",
        ],
        "is_active": True,
        "highlight": False,
        "product_type": "base",
    },
    {
        "id": "quarterly",
        "name": "Quarterly",
        "price_inr": 2499.0,
        "days": 90,
        "features": [
            "Everything in Monthly",
            "Save 17% versus monthly billing",
            "Editable strategy and risk settings",
            "Session-aware trade filtering",
        ],
        "is_active": True,
        "highlight": True,
        "product_type": "base",
    },
    {
        "id": "yearly",
        "name": "Yearly",
        "price_inr": 7999.0,
        "days": 365,
        "features": [
            "Everything in Quarterly",
            "Best value — 33% off monthly",
            "Priority support",
            "Early access to new strategy modules",
        ],
        "is_active": True,
        "highlight": False,
        "product_type": "base",
    },
    {
        "id": "mt5-live-monthly",
        "name": "MT5 Auto-Trading",
        "price_inr": 1499.0,
        "days": 30,
        "features": [
            "Demo and live MT5 account execution",
            "BTC/USD-only safety allowlist",
            "Confidence-triggered automatic entries",
            "EA-managed SL, TP, break-even, partials, trailing and autocut",
        ],
        "is_active": True,
        "highlight": False,
        "product_type": "mt5_live",
    },
]

SITE: Dict[str, Any] = {
    "id": "main",
    "site_name": "Gold Paper Terminal",
    "tagline": "Educational BTCUSDT scalping intelligence",
    "support_email": "support@goldterminal.app",
    "allow_registration": True,
    "invite_mode_enabled": True,
    "maintenance_mode": False,
    "trial_days": 0,
    "affiliate_commission_pct": 20.0,
    "razorpay_key_id": "",
    "razorpay_key_secret": "",
}


async def run() -> None:
    # --- admin account (create, or migrate the legacy seeded admin in place)
    existing = await db.users.find_one({"email": ADMIN_EMAIL})
    if not existing:
        legacy = await db.users.find_one(
            {"$or": [{"email": {"$in": LEGACY_ADMIN_EMAILS}}, {"username": {"$in": LEGACY_ADMIN_USERNAMES}}]}
        )
        if legacy:
            await db.users.update_one(
                {"id": legacy["id"]},
                {
                    "$set": {
                        "email": ADMIN_EMAIL,
                        "username": ADMIN_USERNAME,
                        "password_hash": auth.hash_password(ADMIN_PASSWORD),
                        "role": "admin",
                        "is_active": True,
                    }
                },
            )
            logger.info("migrated legacy admin account to %s", ADMIN_EMAIL)
        else:
            await db.users.insert_one(
                {
                    "id": str(uuid.uuid4()),
                    "email": ADMIN_EMAIL,
                    "username": ADMIN_USERNAME,
                    "password_hash": auth.hash_password(ADMIN_PASSWORD),
                    "role": "admin",
                    "is_active": True,
                    "created_at": auth.now(),
                    "subscription": {"status": "none"},
                }
            )
            logger.info("seeded admin account %s", ADMIN_EMAIL)
    elif existing.get("role") != "admin":
        await db.users.update_one({"id": existing["id"]}, {"$set": {"role": "admin", "is_active": True}})

    # --- plans
    for plan in PLANS:
        if not await db.plans.find_one({"id": plan["id"]}):
            await db.plans.insert_one(dict(plan))
    # Product migration: the former live-only add-on now covers both demo and
    # live MT5 execution. Preserve any admin-edited price/duration/availability.
    await db.plans.update_one(
        {"id": "mt5-live-monthly"},
        {
            "$set": {
                "name": "MT5 Auto-Trading",
                "features": [
                    "Demo and live MT5 account execution",
                    "BTC/USD-only safety allowlist",
                    "Confidence-triggered automatic entries",
                    "EA-managed SL, TP, break-even, partials, trailing and autocut",
                ],
            }
        },
    )

    # --- site settings
    if not await db.site_settings.find_one({"id": "main"}):
        await db.site_settings.insert_one(dict(SITE))

    # --- indexes
    try:
        await db.users.create_index("id", unique=True)
        await db.users.create_index("email", unique=True)
        await db.sessions.create_index("token", unique=True)
        await db.sessions.create_index("user_id")
        await db.plans.create_index("id", unique=True)
        await db.wallets.create_index("user_id", unique=True)
        await db.trades.create_index([("user_id", 1), ("status", 1)])
        await db.presence.create_index("user_id", unique=True)
        await db.invites.create_index("email", unique=True)
        await db.users.create_index("referral_code", unique=True, sparse=True)
        await db.payments.create_index("order_id", unique=True, sparse=True)
        await db.coupons.create_index("code", unique=True)
        await db.affiliate_accounts.create_index("user_id", unique=True)
        await db.affiliate_earnings.create_index("payment_id", unique=True)
        await db.affiliate_withdrawals.create_index([("user_id", 1), ("created_at", -1)])
        await db.mt5_accounts.create_index("user_id", unique=True)
        await db.mt5_accounts.create_index("token_hash", unique=True, sparse=True)
        await db.mt5_commands.create_index("idempotency_key", unique=True)
        await db.mt5_commands.create_index([("account_id", 1), ("status", 1), ("created_at", 1)])
        await db.mt5_positions.create_index([("account_id", 1), ("ticket", 1)], unique=True)
    except Exception as exc:  # noqa: BLE001
        logger.warning("index creation skipped: %s", exc)
