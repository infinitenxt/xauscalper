"""Paper positions autocut on market reverse.

Criterion: once the configured minimum hold has elapsed and an opposite
signal reaches reverse_exit_confidence, the paper engine closes the trade
with exit_reason "MARKET REVERSE"; disabling reverse_exit_enabled (or being
under the minimum hold) prevents this. Exercised directly against
lib.paper_trading.manage_open_trade (the real function the background loop
calls) with isolated tscheck-* trade/wallet fixtures over the live local
Mongo.

All three scenarios run inside ONE async test / ONE asyncio event loop:
motor's AsyncIOMotorClient caches the event loop of its first operation, so
splitting these into separate `asyncio.run()`-wrapped test functions (each
getting its own loop) throws "Event loop is closed" on the 2nd+ test in this
module -- a known motor/asyncio interaction, not an app bug.
"""

import os
import sys
import uuid
from datetime import timedelta

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from lib import paper_trading  # noqa: E402
from lib.db import db  # noqa: E402
from lib.settings import DEFAULT_SETTINGS  # noqa: E402


def _make_open_trade(user_id: str, trade_id: str, opened_seconds_ago: float) -> dict:
    return {
        "id": trade_id,
        "user_id": user_id,
        "status": "OPEN",
        "direction": "BUY",
        "entry": 60000.0,
        "sl": 59500.0,
        "initial_sl": 59500.0,
        "tp": 61000.0,
        "qty": 0.001,
        "r_distance": 500.0,
        "risk_amount": 0.5,
        "atr": 200.0,
        "timeframe": "5m",
        "max_hold_minutes": 15,
        "opened_at": paper_trading._now() - timedelta(seconds=opened_seconds_ago),
        "breakeven_done": False,
        "trailing_active": False,
        "partial_pnl": 0.0,
        "best_r": 0.0,
    }


@pytest.mark.asyncio
async def test_market_reverse_autocut_scenarios(monkeypatch):
    # Rebind lib.paper_trading's (and this test's) motor handle to a client freshly
    # created inside *this* test's event loop. motor caches the loop of its first
    # operation, and pytest-asyncio hands each async test its own loop, so re-using the
    # process-wide lib.db singleton (possibly already bound to an earlier async test's
    # now-closed loop, e.g. from another module in this same xdist worker) throws
    # "Event loop is closed" on the first query -- not an app bug.
    from motor.motor_asyncio import AsyncIOMotorClient

    fresh_client = AsyncIOMotorClient(os.environ["MONGO_URL"])
    fresh_db = fresh_client[os.environ["DB_NAME"]]
    monkeypatch.setattr(paper_trading, "db", fresh_db)
    global db
    db = fresh_db

    ids_to_clean = []
    try:
        # ------------------------------------------------------------
        # 1) Past min-hold + confident opposite signal -> closes MARKET REVERSE
        # ------------------------------------------------------------
        user_a = f"tscheck-reverse-{uuid.uuid4().hex[:8]}"
        trade_a = _make_open_trade(user_a, str(uuid.uuid4()), opened_seconds_ago=90)
        ids_to_clean.append((trade_a["id"], user_a))
        await db.trades.insert_one({**trade_a})

        cfg_on = {
            **DEFAULT_SETTINGS,
            "reverse_exit_enabled": True,
            "reverse_exit_confidence": 60.0,
            "reverse_exit_min_hold_minutes": 1.0,  # 60s; trade open 90s
        }
        await paper_trading.manage_open_trade(trade_a, 60100.0, {"direction": "SELL", "confidence": 75.0}, cfg_on)

        fresh_a = await db.trades.find_one({"id": trade_a["id"]})
        assert fresh_a is not None
        assert fresh_a["status"] == "CLOSED", fresh_a
        assert fresh_a["exit_reason"] == "MARKET REVERSE", fresh_a

        # ------------------------------------------------------------
        # 2) Same setup but reverse_exit_enabled=False -> stays open
        # ------------------------------------------------------------
        user_b = f"tscheck-reverse-off-{uuid.uuid4().hex[:8]}"
        trade_b = _make_open_trade(user_b, str(uuid.uuid4()), opened_seconds_ago=90)
        ids_to_clean.append((trade_b["id"], user_b))
        await db.trades.insert_one({**trade_b})

        cfg_off = {**cfg_on, "reverse_exit_enabled": False}
        await paper_trading.manage_open_trade(trade_b, 60100.0, {"direction": "SELL", "confidence": 95.0}, cfg_off)

        fresh_b = await db.trades.find_one({"id": trade_b["id"]})
        assert fresh_b is not None
        assert fresh_b["status"] == "OPEN", (
            f"expected the trade to stay open with reverse_exit_enabled=False, got {fresh_b['status']}"
        )

        # ------------------------------------------------------------
        # 3) Confident opposite signal but UNDER the minimum hold -> stays open
        # ------------------------------------------------------------
        user_c = f"tscheck-reverse-hold-{uuid.uuid4().hex[:8]}"
        trade_c = _make_open_trade(user_c, str(uuid.uuid4()), opened_seconds_ago=0)
        ids_to_clean.append((trade_c["id"], user_c))
        await db.trades.insert_one({**trade_c})

        cfg_hold = {**cfg_on, "reverse_exit_min_hold_minutes": 5.0}
        await paper_trading.manage_open_trade(trade_c, 60100.0, {"direction": "SELL", "confidence": 99.0}, cfg_hold)

        fresh_c = await db.trades.find_one({"id": trade_c["id"]})
        assert fresh_c is not None
        assert fresh_c["status"] == "OPEN", fresh_c
    finally:
        for trade_id, user_id in ids_to_clean:
            await db.trades.delete_many({"id": trade_id})
            await db.wallets.delete_many({"user_id": user_id})
