"""Survival settings persist while the broker feed is stale.

A subscribed+entitled user with a connected MT5 account (never having sent
market-data yet, so broker_data_ready is false) can change the daily target
and drawdown percentages and request activation. The PATCH must accept it,
report status waiting_broker with activation_requested=true, and a follow-up
GET must return the exact saved values (not silently discarded / defaulted).
"""
from .helpers import cleanup_user, make_subscribed_user


def test_survival_settings_persist_while_feed_stale(client, backend_url):
    api_url = f"{backend_url}/api"
    user_client, user_id, admin = make_subscribed_user(
        api_url, "survivalstale", days=3, live_plan_id="mt5-live-monthly"
    )
    try:
        connect = user_client.post(
            "/mt5/account",
            json={"mode": "demo", "account_login": "800100", "broker_server": "Tscheck-Survival", "lot_size": 0.01},
        )
        assert connect.status_code == 200, connect.text[:300]

        patch = user_client.patch(
            "/mt5/survival",
            json={
                "enabled": True,
                "daily_profit_target_usd": 42.5,
                "daily_drawdown_limit_pct": 4.5,
                "max_drawdown_limit_pct": 12.5,
            },
        )
        assert patch.status_code == 200, f"expected 200, got {patch.status_code} {patch.text[:400]}"
        body = patch.json()
        assert body["status"] == "waiting_broker", body
        assert body["activation_requested"] is True, body
        assert body["enabled"] is False, body  # not enabled until broker feed is ready
        assert body["daily_profit_target_usd"] == 42.5, body
        assert body["daily_drawdown_limit_pct"] == 4.5, body
        assert body["max_drawdown_limit_pct"] == 12.5, body

        reload_resp = user_client.get("/mt5/survival")
        assert reload_resp.status_code == 200, reload_resp.text[:300]
        reloaded = reload_resp.json()
        assert reloaded["status"] == "waiting_broker", reloaded
        assert reloaded["activation_requested"] is True, reloaded
        assert reloaded["daily_profit_target_usd"] == 42.5, reloaded
        assert reloaded["daily_drawdown_limit_pct"] == 4.5, reloaded
        assert reloaded["max_drawdown_limit_pct"] == 12.5, reloaded
        assert reloaded["broker_feed_ready"] is False, reloaded
    finally:
        cleanup_user(admin, user_id)


def test_survival_settings_require_auth(client, backend_url):
    resp = client.patch(
        "/mt5/survival",
        json={
            "enabled": True,
            "daily_profit_target_usd": 10.0,
            "daily_drawdown_limit_pct": 3.0,
            "max_drawdown_limit_pct": 10.0,
        },
    )
    assert resp.status_code in (401, 403), f"expected auth rejection, got {resp.status_code} {resp.text[:300]}"
