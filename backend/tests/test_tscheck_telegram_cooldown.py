"""Telegram alerts have a durable 10-minute scoped cooldown.

Criterion: concurrent same user+symbol+timeframe+direction alerts issue one
mocked HTTP send; success blocks repeats for 600 seconds, different keys are
independent, failure releases the reservation, and unique/TTL indexes exist
on telegram_alert_cooldowns.

Per the spec deviations, no real Telegram HTTP call may be sent -- httpx is
monkeypatched inside this process (lib.telegram.httpx), and the real
reservation logic (lib.telegram._reserve_alert / _finish_alert /
send_telegram_alert) is exercised directly against the live local Mongo.
"""

import asyncio
import json
import os
import subprocess
import sys
import uuid

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from lib import telegram  # noqa: E402
from .helpers import DB_NAME  # noqa: E402


def _mongo_eval(js: str) -> str:
    out = subprocess.run(
        ["mongosh", DB_NAME, "--quiet", "--eval", js],
        capture_output=True, text=True, timeout=20,
    )
    assert out.returncode == 0, f"mongosh failed: {out.stderr[:400]}"
    return out.stdout.strip()


def _mongo_url_from_env() -> str:
    env_path = os.path.join(os.path.dirname(__file__), "..", ".env")
    with open(env_path) as f:
        for line in f:
            if line.strip().startswith("MONGO_URL="):
                return line.strip().split("=", 1)[1].strip()
    raise RuntimeError("MONGO_URL not found in backend/.env")


class _FakeResponse:
    def __init__(self, status_code: int):
        self.status_code = status_code


class _FakeAsyncClient:
    """Stands in for httpx.AsyncClient so no real Telegram HTTP call is ever made."""

    calls = []
    next_status = 200

    def __init__(self, *args, **kwargs):
        pass

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False

    async def post(self, url, json=None, timeout=None):
        _FakeAsyncClient.calls.append((url, json))
        return _FakeResponse(_FakeAsyncClient.next_status)


def test_telegram_alert_cooldown_indexes_exist():
    raw = _mongo_eval("JSON.stringify(db.telegram_alert_cooldowns.getIndexes())")
    indexes = json.loads(raw)

    unique_key_idx = [
        idx for idx in indexes
        if idx.get("key") == {"key": 1} and idx.get("unique") is True
    ]
    assert unique_key_idx, f"no unique index on 'key' found: {indexes}"

    ttl_idx = [
        idx for idx in indexes
        if idx.get("key") == {"expires_at": 1} and "expireAfterSeconds" in idx
    ]
    assert ttl_idx, f"no expires_at TTL index found: {indexes}"


@pytest.mark.asyncio
async def test_cooldown_concurrency_scoping_and_failure_release(monkeypatch):
    suffix = uuid.uuid4().hex[:10]
    user_id = f"tscheck-tg-{suffix}"
    symbol = "BTCUSDT"
    timeframe = "5m"
    direction = "BUY"
    other_symbol = "XAUUSD"

    monkeypatch.setattr(telegram, "httpx", type("_H", (), {"AsyncClient": _FakeAsyncClient}))
    _FakeAsyncClient.calls = []
    _FakeAsyncClient.next_status = 200

    # Rebind lib.telegram's motor handle to a client freshly created inside *this* test's
    # event loop. motor caches the loop of its first operation, and pytest-asyncio hands
    # each async test its own loop, so re-using the process-wide lib.db singleton here
    # (already bound to whatever loop an earlier async test in this worker used) throws
    # "Event loop is closed" on the very first query -- not an app bug, the same
    # motor/asyncio interaction documented in test_tscheck_market_reverse_autocut.py.
    from motor.motor_asyncio import AsyncIOMotorClient
    fresh_client = AsyncIOMotorClient(os.environ.get("MONGO_URL") or _mongo_url_from_env())
    monkeypatch.setattr(telegram, "db", fresh_client[DB_NAME])

    try:
        # 5 concurrent identical alerts (same user+symbol+timeframe+direction) must
        # collapse into exactly one real (mocked) send; the rest are cooldown misses.
        results = await asyncio.gather(*[
            telegram.send_telegram_alert(
                "fake-token", "fake-channel", symbol, direction,
                entry=100.0, tp=110.0, sl=95.0, confidence=80.0,
                timeframe=timeframe, user_id=user_id,
            )
            for _ in range(5)
        ])
        assert sum(1 for r in results if r is True) == 1, results
        assert len(_FakeAsyncClient.calls) == 1, _FakeAsyncClient.calls

        # An immediate repeat on the exact same key is blocked (still inside 600s).
        again = await telegram.send_telegram_alert(
            "fake-token", "fake-channel", symbol, direction,
            entry=100.0, tp=110.0, sl=95.0, confidence=80.0,
            timeframe=timeframe, user_id=user_id,
        )
        assert again is False
        assert len(_FakeAsyncClient.calls) == 1

        # A different key (different symbol) is independent and sends immediately.
        other = await telegram.send_telegram_alert(
            "fake-token", "fake-channel", other_symbol, direction,
            entry=2000.0, tp=2100.0, sl=1950.0, confidence=80.0,
            timeframe=timeframe, user_id=user_id,
        )
        assert other is True
        assert len(_FakeAsyncClient.calls) == 2

        # Failure (non-200) releases the reservation immediately instead of blocking for 600s.
        fail_symbol = "BTCUSDT"
        fail_timeframe = "1m"
        _FakeAsyncClient.next_status = 500
        failed = await telegram.send_telegram_alert(
            "fake-token", "fake-channel", fail_symbol, direction,
            entry=100.0, tp=110.0, sl=95.0, confidence=80.0,
            timeframe=fail_timeframe, user_id=user_id,
        )
        assert failed is False
        _FakeAsyncClient.next_status = 200
        retried = await telegram.send_telegram_alert(
            "fake-token", "fake-channel", fail_symbol, direction,
            entry=100.0, tp=110.0, sl=95.0, confidence=80.0,
            timeframe=fail_timeframe, user_id=user_id,
        )
        assert retried is True, "failure must release the reservation, allowing an immediate retry"
    finally:
        keys = [
            f"{user_id}|{symbol}|{timeframe}|{direction}",
            f"{user_id}|{other_symbol}|{timeframe}|{direction}",
            f"{user_id}|BTCUSDT|1m|{direction}",
        ]
        keys_js = json.dumps(keys)
        _mongo_eval(f"db.telegram_alert_cooldowns.deleteMany({{key: {{$in: {keys_js}}}}})")
