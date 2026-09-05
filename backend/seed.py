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
LEGACY_ADMIN_EMAILS = ["admin@bitcointerminal.app"]
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
        "name": "MT5 Basic",
        "price_inr": 1499.0,
        "days": 30,
        "features": [
            "Demo and live MT5 execution with your Windows terminal",
            "BTC/USDT-only safety allowlist",
            "Confidence-triggered automatic entries",
            "EA-managed SL, TP, break-even, partials, trailing and autocut",
        ],
        "is_active": True,
        "highlight": False,
        "product_type": "mt5_basic",
    },
    {
        "id": "mt5-managed-monthly",
        "name": "MT5 Managed",
        "price_inr": 2999.0,
        "days": 30,
        "features": [
            "No Windows terminal or EA setup required",
            "Secure MetaApi cloud connection for demo and live MT5",
            "Broker-matched data and server-managed execution",
            "Dual-agent Survival Mode with deterministic risk shutdowns",
        ],
        "is_active": True,
        "highlight": True,
        "product_type": "mt5_managed",
    },
]

SITE: Dict[str, Any] = {
    "id": "main",
    "site_name": "Bitcoin Paper Terminal",
    "tagline": "Educational BTCUSDT scalping intelligence",
    "support_email": "support@bitcointerminal.app",
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
                "name": "MT5 Basic",
                "product_type": "mt5_basic",
                "features": [
                    "Demo and live MT5 execution with your Windows terminal",
                    "BTC/USDT-only safety allowlist",
                    "Confidence-triggered automatic entries",
                    "EA-managed SL, TP, break-even, partials, trailing and autocut",
                ],
            }
        },
    )
    # Preserve every legacy subscriber's remaining entitlement as MT5 Basic.
    legacy_users = await db.users.find(
        {"mt5_live_subscription": {"$exists": True}, "mt5_basic_subscription": {"$exists": False}}
    ).to_list(10_000)
    for legacy_user in legacy_users:
        await db.users.update_one(
            {"id": legacy_user["id"]},
            {"$set": {"mt5_basic_subscription": legacy_user["mt5_live_subscription"]}},
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
        await db.telegram_alert_cooldowns.create_index("key", unique=True)
        await db.telegram_alert_cooldowns.create_index("expires_at", expireAfterSeconds=0)
        await db.order_book_snapshots.create_index([("symbol", 1), ("captured_at", -1)])
        await db.order_book_snapshots.create_index("captured_at", expireAfterSeconds=2_592_000)
        await db.broker_ticks.create_index([("account_id", 1), ("captured_at", -1)])
        await db.broker_ticks.create_index("captured_at", expireAfterSeconds=604_800)
        await db.broker_candles.create_index([("account_id", 1), ("timeframe", 1), ("open_time", 1)], unique=True)
        await db.mt5_survival.create_index("account_id", unique=True)
        await db.mt5_survival_decisions.create_index("decision_key", unique=True)
        await db.mt5_survival_decisions.create_index([("account_id", 1), ("created_at", -1)])
    except Exception as exc:  # noqa: BLE001
        logger.warning("index creation skipped: %s", exc)
