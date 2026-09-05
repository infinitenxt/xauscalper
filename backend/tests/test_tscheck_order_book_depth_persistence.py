"""Depth snapshots are retained for future backtests.

Criterion: fresh depth is cached for 3 seconds, compact snapshots persist no
more than once per 30 seconds per symbol, and Mongo carries symbol/time plus
a 30-day TTL index on order_book_snapshots; historical candle replay remains
order-book-neutral (covered by test_tscheck_backtest_leakage_safe.py).

The 3s cache and 30s persistence throttle are exercised directly against
lib.market (the module the live route and engine both call) with the module
cache reset first so the assertions are deterministic; the index shape is
read straight off the real local mongod via mongosh (never mocked).
"""

import json
import os
import subprocess
import sys
import time

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from lib import market  # noqa: E402
from .helpers import DB_NAME  # noqa: E402


def _mongo_eval(js: str) -> str:
    out = subprocess.run(
        ["mongosh", DB_NAME, "--quiet", "--eval", js],
        capture_output=True, text=True, timeout=20,
    )
    assert out.returncode == 0, f"mongosh failed: {out.stderr[:400]}"
    return out.stdout.strip()


def test_order_book_snapshot_indexes_are_symbol_time_and_30_day_ttl():
    raw = _mongo_eval("JSON.stringify(db.order_book_snapshots.getIndexes())")
    indexes = json.loads(raw)

    symbol_time_idx = [
        idx for idx in indexes
        if set(idx.get("key", {}).keys()) == {"symbol", "captured_at"}
    ]
    assert symbol_time_idx, f"no symbol+captured_at compound index found: {indexes}"

    ttl_idx = [
        idx for idx in indexes
        if idx.get("key") == {"captured_at": 1} and "expireAfterSeconds" in idx
    ]
    assert ttl_idx, f"no captured_at TTL index found: {indexes}"
    assert ttl_idx[0]["expireAfterSeconds"] == 30 * 24 * 60 * 60, ttl_idx[0]


@pytest.mark.asyncio
async def test_depth_cache_and_persist_throttle():
    """Both scenarios run inside ONE async test / ONE asyncio event loop: the
    shared motor client (used by the 30s persist path) caches the loop of its
    first operation, so splitting these into separate async tests (each get
    their own loop under pytest-asyncio) throws when the second test tries to
    persist -- a known motor/asyncio interaction, not an app bug (same
    constraint documented in test_tscheck_market_reverse_autocut.py)."""
    market._client = None
    market._depth_cache.pop("BTCUSDT", None)
    first = await market.get_order_book("BTCUSDT")
    if first.get("stale"):
        pytest.skip("upstream Binance depth feed unavailable in this environment")

    second = await market.get_order_book("BTCUSDT")
    # Served from the in-process cache: identical captured_at within the 3s window.
    assert second["captured_at"] == first["captured_at"]

    market._depth_cache.pop("XAUUSD", None)
    xau_first = await market.get_order_book("XAUUSD")
    if xau_first.get("stale"):
        pytest.skip("upstream Binance depth feed unavailable in this environment")

    before = market._depth_last_persist.get("XAUUSD")
    assert before is not None, "first live fetch must record a persist timestamp"

    # Force a second live fetch (bypass the 3s cache) immediately after.
    market._depth_cache.pop("XAUUSD", None)
    xau_second = await market.get_order_book("XAUUSD")
    if xau_second.get("stale"):
        pytest.skip("upstream Binance depth feed unavailable in this environment")

    after = market._depth_last_persist.get("XAUUSD")
    # Within the 30s throttle window, the persist timestamp must not advance again.
    assert after == before, "snapshot persisted again inside the 30s throttle window"
