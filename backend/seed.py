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

ADMIN_EMAIL = "admin@goldterminal.app"
ADMIN_USERNAME = "admin"
ADMIN_PASSWORD = "Harsh@10576"

PLANS: List[Dict[str, Any]] = [
    {
        "id": "monthly",
        "name": "Monthly",
        "price_inr": 999.0,
        "days": 30,
        "features": [
            "Live XAUUSDT scalping signals",
            "Auto paper trading with full risk management",
            "AI explanation on every trade",
            "Voice announcements and market commentary",
            "Strategy backtesting",
        ],
        "is_active": True,
        "highlight": False,
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
    },
]

SITE: Dict[str, Any] = {
    "id": "main",
    "site_name": "Gold Paper Terminal",
    "tagline": "Educational XAUUSDT scalping intelligence",
    "support_email": "support@goldterminal.app",
    "allow_registration": True,
    "maintenance_mode": False,
    "trial_days": 0,
    "razorpay_key_id": "",
    "razorpay_key_secret": "",
}


async def run() -> None:
    # --- admin account
    existing = await db.users.find_one({"username": ADMIN_USERNAME})
    if not existing:
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
        logger.info("seeded admin account %s", ADMIN_USERNAME)
    elif existing.get("role") != "admin":
        await db.users.update_one({"id": existing["id"]}, {"$set": {"role": "admin", "is_active": True}})

    # --- plans
    for plan in PLANS:
        if not await db.plans.find_one({"id": plan["id"]}):
            await db.plans.insert_one(dict(plan))

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
    except Exception as exc:  # noqa: BLE001
        logger.warning("index creation skipped: %s", exc)
