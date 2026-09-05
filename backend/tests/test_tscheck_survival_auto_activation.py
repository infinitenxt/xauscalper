"""Pending Survival activation starts automatically once the broker feed syncs.

Flow: request Survival activation while the feed is stale (activation_requested
stays true, session waiting). Then push a valid market-data payload that
crosses the 60-bar primary-timeframe threshold. That ingest path must clear
activation_requested, flip the session to active, and set the MT5 account's
auto_trade_enabled to true -- all without any further user action.
"""
from .helpers import cleanup_user, make_subscribed_user


def _bar(ts: int, tf_seconds: int = 300) -> dict:
    return {
        "timeframe": "5m",
        "open_time": ts,
        "duration_seconds": tf_seconds,
        "open": 61000.0,
        "high": 61050.0,
        "low": 60950.0,
        "close": 61010.0,
        "tick_volume": 20.0,
        "spread_points": 5,
    }


def test_pending_activation_auto_starts_after_broker_sync(client, backend_url):
    api_url = f"{backend_url}/api"
    user_client, user_id, admin = make_subscribed_user(
        api_url, "survivalauto", days=3, live_plan_id="mt5-live-monthly"
    )
    try:
        connect = user_client.post(
            "/mt5/account",
            json={"mode": "demo", "account_login": "800200", "broker_server": "Tscheck-SurvivalAuto", "lot_size": 0.01},
        )
        assert connect.status_code == 200, connect.text[:300]
        token = connect.json()["bridge_token"]

        patch = user_client.patch(
            "/mt5/survival",
            json={
                "enabled": True,
                "daily_profit_target_usd": 30.0,
                "daily_drawdown_limit_pct": 3.0,
                "max_drawdown_limit_pct": 10.0,
            },
        )
        assert patch.status_code == 200, patch.text[:300]
        assert patch.json()["activation_requested"] is True, patch.json()
        assert patch.json()["status"] == "waiting_broker", patch.json()

        base_ts = 1_700_000_000
        payload = {
            "symbol": "BTCUSD",
            "bid": 61000.0,
            "ask": 61001.0,
            "tick_time": base_ts + 60 * 300,
            "point": 0.01,
            "digits": 2,
            "trade_stops_level": 0,
            "contract_size": 1.0,
            "spread_points": 5,
            "bars": [_bar(base_ts + i * 300) for i in range(60)],
        }
        headers = {"Authorization": f"Bearer {token}"}
        ingest = user_client.post("/mt5/bridge/market-data", headers=headers, json=payload)
        assert ingest.status_code == 200, ingest.text[:400]
        assert ingest.json()["broker_data_ready"] is True, ingest.json()

        status = user_client.get("/mt5/survival")
        assert status.status_code == 200, status.text[:300]
        s = status.json()
        assert s["activation_requested"] is False, s
        assert s["enabled"] is True, s
        assert s["status"] == "active", s
        assert s["broker_feed_ready"] is True, s

        account = user_client.get("/mt5/account")
        assert account.status_code == 200, account.text[:300]
        assert account.json()["auto_trade_enabled"] is True, account.json()
    finally:
        cleanup_user(admin, user_id)
