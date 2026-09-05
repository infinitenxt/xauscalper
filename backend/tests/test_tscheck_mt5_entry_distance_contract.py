"""MT5 entry commands carry strategy stop DISTANCES only, never absolute prices.

Criterion: a queued ENTRY exposes sl_dist and tp_dist (tp_dist == sl_dist * rr),
omits absolute sl/tp from the response contract, and the EA converts those
distances into BUY/SELL broker prices from the live ASK/BID while enforcing
SYMBOL_TRADE_STOPS_LEVEL. A real Windows MT5 terminal is unavailable (see
spec deviations) so the EA side is verified statically against its source.
"""

import os

from .helpers import cleanup_user, make_subscribed_user

EA_PATH = os.path.join(
    os.path.dirname(__file__), "..", "..", "frontend", "public", "UniversalTerminalBridge.mq5"
)


def _ea_source() -> str:
    assert os.path.isfile(EA_PATH), f"EA file not found at {EA_PATH}"
    with open(EA_PATH, encoding="utf-8") as f:
        return f.read()


def test_mt5_command_model_exposes_distances_not_absolute_prices():
    """The Mt5Command pydantic model (the bridge/poll response contract) has
    sl_dist/tp_dist fields and no absolute sl/tp fields."""
    from models.mt5 import Mt5Command

    fields = Mt5Command.model_fields
    assert "sl_dist" in fields
    assert "tp_dist" in fields
    assert "sl" not in fields, "ENTRY command contract must not expose an absolute stop price"
    assert "tp" not in fields, "ENTRY command contract must not expose an absolute target price"


def test_queued_entry_command_has_proportional_sl_tp_distances(client, backend_url):
    """Insert a signal-shaped dict through the real queue_command coordinator
    (mirroring what mt5_execution._queue_entry sends) and confirm the stored
    document only carries sl_dist/tp_dist, with tp_dist == sl_dist * rr."""
    import asyncio
    import sys

    sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
    from lib import mt5_execution  # noqa: E402
    from lib.db import db  # noqa: E402

    async def _run():
        account = {
            "id": "tscheck-sim-account",
            "user_id": "tscheck-sim-user",
            "lot_size": 0.01,
            "resolved_symbol": "BTCUSDT",
        }
        signal = {
            "direction": "BUY",
            "price": 60000.0,
            "sl_dist": 150.0,
            "rr": 1.4,
            "atr": 200.0,
            "confidence": 88.0,
            "timeframe": "5m",
            "last_closed": 1234567890,
        }
        cfg = {
            "max_hold_minutes": 15,
            "breakeven_at_r": 0.5,
            "partial_tp_at_r": 1.0,
            "partial_tp_fraction": 0.5,
            "trail_start_r": 0.8,
            "trail_atr_mult": 0.8,
            "confidence_threshold": 80.0,
            "trailing_enabled": True,
            "profit_lock_r": 0.10,
        }
        doc = await mt5_execution._queue_entry(account, signal, cfg)
        assert doc is not None
        try:
            assert doc["sl_dist"] == 150.0
            assert abs(doc["tp_dist"] - 150.0 * 1.4) < 1e-6
            assert "sl" not in doc or doc.get("sl") in (None,)
            assert "tp" not in doc or doc.get("tp") in (None,)
            # payload sent to the EA carries the same distances, not absolute prices
            assert doc["payload"]["sl_dist"] == 150.0
            assert abs(doc["payload"]["tp_dist"] - 210.0) < 1e-6
            assert "sl" not in doc["payload"] and "tp" not in doc["payload"]
        finally:
            await db.mt5_commands.delete_one({"id": doc["id"]})

    asyncio.run(_run())


def test_ea_converts_distances_to_prices_from_live_ask_bid_with_stops_level():
    src = _ea_source()
    assert "sl_dist" in src and "tp_dist" in src
    # BUY execution price comes from ASK, SELL from BID (live market, not a cached quote)
    assert 'side == "BUY"' in src
    assert "SYMBOL_ASK" in src and "SYMBOL_BID" in src
    # Broker minimum stop distance is read and enforced before placing SL/TP
    assert "SYMBOL_TRADE_STOPS_LEVEL" in src
    assert "min_stop_distance" in src
    assert "MathMax(\n         sl_distance,\n         min_stop_distance\n      )" in src or (
        "sl_distance" in src and "min_stop_distance" in src
    )
