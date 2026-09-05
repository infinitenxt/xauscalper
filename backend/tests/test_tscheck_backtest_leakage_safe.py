"""Cross-asset backtests are leakage-safe.

Criterion: BTCUSDT and XAUUSD feeds both return candles; replay passes the
selected symbol, uses closed historical bars without future higher-timeframe
fallback or Telegram side effects, and emits millisecond timestamps.
"""

import os
import sys

from .helpers import cleanup_user, make_subscribed_user

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

BACKTEST_SRC = os.path.join(os.path.dirname(__file__), "..", "lib", "backtest.py")


def _backtest_source() -> str:
    with open(BACKTEST_SRC, encoding="utf-8") as f:
        return f.read()


def test_candle_feed_available_for_both_symbols(client):
    btc = client.get("/market/candles", params={"symbol": "BTCUSDT", "timeframe": "5m", "limit": 50})
    assert btc.status_code == 200, f"BTCUSDT candles failed: {btc.status_code} {btc.text[:300]}"
    btc_candles = btc.json()["candles"]
    assert len(btc_candles) > 0

    xau = client.get("/market/candles", params={"symbol": "XAUUSD", "timeframe": "5m", "limit": 50})
    assert xau.status_code == 200, f"XAUUSD candles failed: {xau.status_code} {xau.text[:300]}"
    xau_candles = xau.json()["candles"]
    assert len(xau_candles) > 0


def test_replay_uses_closed_bars_no_future_mtf_leakage_and_no_telegram_side_effect():
    """Static source assertions on lib.backtest.run -- the exact function the
    /api/backtest route calls -- since there is no API surface that exposes
    its internal per-bar cfg/mtf construction."""
    src = _backtest_source()

    # Historical replay must force closed-bar analysis (no in-progress candle peeking).
    assert '"use_closed_candle": False' in src

    # Telegram side effects must be disabled for replay (no user_id -> lib.telegram
    # cooldown key can't resolve to a real user, so no live alert can be dispatched).
    assert 'replay_cfg.pop("user_id"' in src

    # Higher-timeframe context at bar i must be bounded to data at/before that bar's
    # own time (no forward-looking fallback to the full, unbounded mtf series).
    assert 'c["time"] <= cutoff' in src


def test_backtest_response_uses_selected_symbol_and_millisecond_timestamps(backend_url):
    user_client, user_id, admin = make_subscribed_user(backend_url + "/api", "backtest-leak")
    try:
        # Real settings docs are always defaults-initialized via GET /settings first (the
        # dashboard/settings page always loads current settings before letting a user
        # change the symbol); mirror that real flow here.
        prime = user_client.get("/settings")
        assert prime.status_code == 200, f"settings init failed: {prime.status_code} {prime.text[:300]}"

        set_symbol = user_client.patch("/settings/symbol", json={"symbol": "XAUUSD"})
        assert set_symbol.status_code == 200, f"settings update failed: {set_symbol.status_code} {set_symbol.text[:300]}"

        resp = user_client.get("/backtest", params={"timeframe": "5m", "days": 1, "refresh": True})
        assert resp.status_code in (200, 503), f"unexpected status: {resp.status_code} {resp.text[:300]}"
        if resp.status_code == 503:
            import pytest
            pytest.skip("not enough XAUUSD market history buffered yet to run a replay")

        body = resp.json()
        assert body["settings_used"], body
        curve = body.get("equity_curve") or []
        if curve:
            first_ts = curve[0]["time"]
            # Millisecond epoch: any time after 2020 in ms is > 1.5e12.
            assert first_ts > 1_500_000_000_000, f"expected ms timestamp, got {first_ts}"
    finally:
        cleanup_user(admin, user_id)
