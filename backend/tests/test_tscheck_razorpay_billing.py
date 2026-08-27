"""Razorpay billing: config exposure via /billing/status and order creation via /billing/order.

Covers:
  - Admin-authenticated GET /billing/status returns razorpay_enabled=true with an
    rzp_live_ key id, and never leaks the secret.
  - POST /billing/order for the monthly plan returns 200 with a real Razorpay
    order_id, amount 99900 paise, and matching plan metadata (no more 502).

Any payment order created here is cleaned up directly against Mongo in a finally
block so no lingering `created` payment rows are left behind by this check.
"""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path

import pytest

from tests.helpers import login_admin

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

BACKEND_URL = "http://localhost:8001"
API_URL = f"{BACKEND_URL}/api"


def _delete_payment_by_order_id(order_id: str) -> None:
    from lib.db import db

    async def _run() -> None:
        await db.payments.delete_one({"order_id": order_id})

    asyncio.run(_run())


def test_billing_status_exposes_active_razorpay_config_without_secret():
    client = login_admin(API_URL)
    try:
        resp = client.get("/billing/status")
        assert resp.status_code == 200, resp.text
        body = resp.json()
        assert body["razorpay_enabled"] is True
        key_id = body.get("razorpay_key_id")
        assert key_id and key_id.startswith("rzp_live_"), body
        assert "razorpay_key_secret" not in body
        assert "key_secret" not in body
        raw = resp.text
        assert "secret" not in raw.lower()
        # sanity: monthly plan present at the documented price/duration
        plans = {p["id"]: p for p in body["plans"]}
        assert plans["monthly"]["price_inr"] == 999.0
        assert plans["monthly"]["days"] == 30
    finally:
        client.close()


def test_billing_order_creates_razorpay_order_for_monthly_plan():
    client = login_admin(API_URL)
    order_id = None
    try:
        resp = client.post("/billing/order", json={"plan_id": "monthly"})
        assert resp.status_code == 200, resp.text
        body = resp.json()
        order_id = body["order_id"]
        assert order_id and order_id.startswith("order_")
        assert body["amount"] == 99900
        assert body["currency"] == "INR"
        assert body["key_id"].startswith("rzp_live_")
        assert body["plan"]["id"] == "monthly"
        assert body["plan"]["price_inr"] == 999.0
        assert body["plan"]["days"] == 30
        assert body["original_amount_inr"] == 999.0
        assert body["discount_inr"] == 0.0
    finally:
        client.close()
        if order_id:
            _delete_payment_by_order_id(order_id)


def test_billing_order_requires_auth():
    import httpx

    with httpx.Client(base_url=API_URL, timeout=30.0) as anon:
        resp = anon.post("/billing/order", json={"plan_id": "monthly"})
        assert resp.status_code == 401
