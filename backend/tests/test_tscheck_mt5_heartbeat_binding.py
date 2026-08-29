"""Heartbeat enforces exact account and broker safety binding.

Matching login/server/demo-mode with an BTCUSD/GOLD/short-suffix alias is
accepted; wrong login, wrong server, wrong mode, and non-gold symbols are
rejected. A successful heartbeat also records EA version and (via a broker
position) opened_at.
"""

from datetime import datetime, timezone

from .helpers import cleanup_user, make_subscribed_user

HEARTBEAT_BASE = {
    "balance": 5000.0, "equity": 5000.0, "free_margin": 5000.0,
    "volume_min": 0.01, "volume_max": 50.0, "volume_step": 0.01,
    "trade_allowed": True, "algo_trading": True,
}


def _connect(user_client):
    resp = user_client.post(
        "/mt5/account",
        json={"mode": "demo", "account_login": "9988", "broker_server": "Tscheck-Broker", "lot_size": 0.01},
    )
    assert resp.status_code == 200, resp.text[:300]
    return resp.json()["bridge_token"]


def _heartbeat(user_client, token, **overrides):
    body = {
        "account_login": "9988", "broker_server": "Tscheck-Broker", "is_demo": True,
        "resolved_symbol": "BTCUSD", "ea_version": "1.10", "positions": [], **HEARTBEAT_BASE,
    }
    body.update(overrides)
    return user_client.post(
        "/mt5/bridge/heartbeat", headers={"Authorization": f"Bearer {token}"}, json=body
    )


def test_heartbeat_binding_and_symbol_allowlist(client, backend_url):
    api_url = f"{backend_url}/api"
    user_client, user_id, admin = make_subscribed_user(api_url, "hbind", days=3)
    try:
        token = _connect(user_client)

        wrong_login = _heartbeat(user_client, token, account_login="0000")
        assert wrong_login.status_code == 403, f"wrong login should be rejected, got {wrong_login.status_code} {wrong_login.text[:300]}"

        wrong_server = _heartbeat(user_client, token, broker_server="Other-Broker")
        assert wrong_server.status_code == 403, f"wrong server should be rejected, got {wrong_server.status_code} {wrong_server.text[:300]}"

        wrong_mode = _heartbeat(user_client, token, is_demo=False)
        assert wrong_mode.status_code == 403, f"wrong demo/live mode should be rejected, got {wrong_mode.status_code} {wrong_mode.text[:300]}"

        non_gold = _heartbeat(user_client, token, resolved_symbol="EURUSD")
        assert non_gold.status_code == 422, f"non-gold symbol should be rejected, got {non_gold.status_code} {non_gold.text[:300]}"

        # gold alias with a short broker suffix is accepted
        alias_ok = _heartbeat(user_client, token, resolved_symbol="BTCUSD.a")
        assert alias_ok.status_code == 200, f"gold alias should be accepted, got {alias_ok.status_code} {alias_ok.text[:300]}"
        assert alias_ok.json()["ea_version"] == "1.10"

        opened = datetime.now(timezone.utc).isoformat()
        with_position = _heartbeat(
            user_client, token, resolved_symbol="GOLD",
            positions=[{
                "ticket": "700001", "symbol": "GOLD", "direction": "BUY", "volume": 0.01,
                "entry_price": 2400.0, "current_price": 2401.0, "sl": 2390.0, "tp": 2420.0,
                "profit": 1.0, "opened_at": opened,
            }],
        )
        assert with_position.status_code == 200, with_position.text[:300]
        acct = with_position.json()
        assert acct["position"] is not None, "expected an open broker position to be recorded"
        assert acct["position"]["opened_at"] is not None, "opened_at must be recorded from the broker position"
    finally:
        cleanup_user(admin, user_id)
