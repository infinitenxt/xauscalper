"""Hard disconnect with an open MT5 trade.

Criterion: disconnect succeeds immediately, revokes the bridge, cancels
in-flight commands, marks the known position "detached", and returns a
message mentioning the broker-managed SL/TP plus the local EA continuing to
manage the trade.
"""

import uuid

from .helpers import DB_NAME, cleanup_user, make_subscribed_user
import subprocess


def _mongo_eval(js: str) -> str:
    out = subprocess.run(
        ["mongosh", DB_NAME, "--quiet", "--eval", js],
        capture_output=True, text=True, timeout=20,
    )
    assert out.returncode == 0, f"mongosh failed: {out.stderr[:400]}"
    return out.stdout


def _connect(user_client, login="77321", server="Tscheck-Disc"):
    resp = user_client.post(
        "/mt5/account",
        json={"mode": "demo", "account_login": login, "broker_server": server, "lot_size": 0.01},
    )
    assert resp.status_code == 200, resp.text[:300]
    account = resp.json()["account"]
    token = resp.json()["bridge_token"]
    return account["id"], token


def test_disconnect_with_open_position_detaches_and_cancels_commands(client, backend_url):
    api_url = f"{backend_url}/api"
    user_client, user_id, admin = make_subscribed_user(
        api_url, "disc", days=3, live_plan_id="mt5-live-monthly"
    )
    try:
        account_id, token = _connect(user_client)

        # Heartbeat one open broker position onto this account.
        ticket = f"tscheck-{uuid.uuid4().hex[:8]}"
        hb = user_client.post(
            "/mt5/bridge/heartbeat",
            headers={"Authorization": f"Bearer {token}"},
            json={
                "account_login": "77321", "broker_server": "Tscheck-Disc", "is_demo": True,
                "resolved_symbol": "BTCUSDT", "ea_version": "1.10",
                "balance": 5000.0, "equity": 5000.0, "free_margin": 5000.0,
                "volume_min": 0.01, "volume_max": 50.0, "volume_step": 0.01,
                "trade_allowed": True, "algo_trading": True,
                "positions": [{
                    "ticket": ticket, "symbol": "BTCUSDT", "direction": "BUY", "volume": 0.01,
                    "entry_price": 60000.0, "current_price": 60100.0, "sl": 59500.0, "tp": 61000.0,
                    "profit": 1.0,
                }],
            },
        )
        assert hb.status_code == 200, hb.text[:300]

        # A dangling pending command should be cancelled by the disconnect.
        cid = str(uuid.uuid4())
        _mongo_eval(
            f'db.mt5_commands.insertOne({{id: "{cid}", idempotency_key: "{cid}", '
            f'account_id: "{account_id}", user_id: "{user_id}", action: "CLOSE", '
            f'status: "pending", symbol: "BTCUSDT", created_at: new Date()}})'
        )

        resp = user_client.delete("/mt5/account")
        assert resp.status_code == 200, resp.text[:300]
        body = resp.json()
        message = body.get("message", "")
        assert "broker" in message.lower() and ("sl" in message.lower() or "tp" in message.lower()), body
        assert "ea" in message.lower() or "local" in message.lower(), body

        account_after = _mongo_eval(
            f'JSON.stringify(db.mt5_accounts.findOne({{id: "{account_id}"}}, '
            f'{{_id:0, revoked:1, auto_trade_enabled:1, status:1}}))'
        )
        assert '"revoked":true' in account_after.replace(" ", "")
        assert '"status":"revoked"' in account_after.replace(" ", "")

        position_after = _mongo_eval(
            f'JSON.stringify(db.mt5_positions.findOne({{account_id: "{account_id}", ticket: "{ticket}"}}, '
            f'{{_id:0, detached:1}}))'
        )
        assert '"detached":true' in position_after.replace(" ", "")

        command_after = _mongo_eval(
            f'JSON.stringify(db.mt5_commands.findOne({{id: "{cid}"}}, {{_id:0, status:1}}))'
        )
        assert '"status":"cancelled"' in command_after.replace(" ", "")
    finally:
        cleanup_user(admin, user_id)


def test_disconnect_without_open_position_still_succeeds(client, backend_url):
    api_url = f"{backend_url}/api"
    user_client, user_id, admin = make_subscribed_user(
        api_url, "discnop", days=3, live_plan_id="mt5-live-monthly"
    )
    try:
        _connect(user_client, login="77322", server="Tscheck-Disc2")
        resp = user_client.delete("/mt5/account")
        assert resp.status_code == 200, resp.text[:300]
        assert "disconnected" in resp.json()["message"].lower()
    finally:
        cleanup_user(admin, user_id)
