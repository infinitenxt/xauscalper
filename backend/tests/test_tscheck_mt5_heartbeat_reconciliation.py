"""Heartbeat reconciliation repairs uncertain command outcomes.

An accepted/dispatched ENTRY becomes confirmed once its position appears in
a later heartbeat, and an accepted/dispatched CLOSE becomes confirmed once
that previously-open ticket disappears from a later heartbeat.
"""

import json
import subprocess
import uuid

from .helpers import cleanup_user, make_subscribed_user

HEARTBEAT_BASE = {
    "balance": 5000.0, "equity": 5000.0, "free_margin": 5000.0,
    "volume_min": 0.01, "volume_max": 50.0, "volume_step": 0.01,
    "trade_allowed": True, "algo_trading": True,
}


def _mongo_eval(js: str) -> str:
    out = subprocess.run(
        ["mongosh", "bitcoin_terminal", "--quiet", "--eval", js],
        capture_output=True, text=True, timeout=20,
    )
    assert out.returncode == 0, f"mongosh failed: {out.stderr[:400]}"
    return out.stdout


def _insert_command(account_id: str, user_id: str, action: str, direction: str = "BUY", ticket: str | None = None) -> str:
    cid = str(uuid.uuid4())
    ticket_js = f'"{ticket}"' if ticket else "null"
    payload_js = f'{{ticket: {ticket_js}}}' if action == "CLOSE" else "{}"
    js = f"""
    db.mt5_commands.insertOne({{
      id: "{cid}", idempotency_key: "{cid}", account_id: "{account_id}", user_id: "{user_id}",
      action: "{action}", status: "accepted", symbol: "BTCUSDT", direction: "{direction}", lots: 0.01,
      sl: 0, tp: 0, reason: "tscheck-reconcile", payload: {payload_js}, attempts: 1,
      created_at: new Date(), expires_at: null, expires_epoch: 0,
      broker_ticket: {ticket_js}, execution_result: "", broker_retcode: null, completed_at: null
    }})
    """
    _mongo_eval(js)
    return cid


def _doc(cid: str) -> dict:
    out = _mongo_eval(f'JSON.stringify(db.mt5_commands.findOne({{id: "{cid}"}}, {{_id:0}}))')
    return json.loads(out.strip())


def _connect(user_client, login="31200", server="Tscheck-Recon"):
    resp = user_client.post(
        "/mt5/account", json={"mode": "demo", "account_login": login, "broker_server": server, "lot_size": 0.01}
    )
    assert resp.status_code == 200, resp.text[:300]
    return resp.json()["account"]["id"], resp.json()["bridge_token"]


def _heartbeat(user_client, token, login, server, positions):
    return user_client.post(
        "/mt5/bridge/heartbeat", headers={"Authorization": f"Bearer {token}"},
        json={
            "account_login": login, "broker_server": server, "is_demo": True,
            "resolved_symbol": "BTCUSDT", "ea_version": "1.10", "positions": positions, **HEARTBEAT_BASE,
        },
    )


def test_accepted_entry_confirms_when_position_appears(client, backend_url):
    api_url = f"{backend_url}/api"
    user_client, user_id, admin = make_subscribed_user(api_url, "reconentry", days=3)
    try:
        account_id, token = _connect(user_client, login="31200", server="Tscheck-Recon")
        # Baseline heartbeat with no position, to establish the account as connected.
        base = _heartbeat(user_client, token, "31200", "Tscheck-Recon", [])
        assert base.status_code == 200, base.text[:300]

        cid = _insert_command(account_id, user_id, "ENTRY", direction="BUY")
        assert _doc(cid)["status"] == "accepted"

        with_position = _heartbeat(
            user_client, token, "31200", "Tscheck-Recon",
            [{
                "ticket": "800001", "symbol": "BTCUSDT", "direction": "BUY", "volume": 0.01,
                "entry_price": 2400.0, "current_price": 2401.0, "sl": 2390.0, "tp": 2420.0, "profit": 1.0,
            }],
        )
        assert with_position.status_code == 200, with_position.text[:300]

        stored = _doc(cid)
        assert stored["status"] == "confirmed", f"expected ENTRY to reconcile to confirmed, got {stored['status']}"
        assert stored["broker_ticket"] == "800001"
    finally:
        cleanup_user(admin, user_id)


def test_accepted_close_confirms_when_ticket_disappears(client, backend_url):
    api_url = f"{backend_url}/api"
    user_client, user_id, admin = make_subscribed_user(api_url, "reconclose", days=3)
    try:
        account_id, token = _connect(user_client, login="31201", server="Tscheck-Recon2")
        # Heartbeat with the position open first, so the backend records it as OPEN.
        opened = _heartbeat(
            user_client, token, "31201", "Tscheck-Recon2",
            [{
                "ticket": "800002", "symbol": "BTCUSDT", "direction": "SELL", "volume": 0.01,
                "entry_price": 2400.0, "current_price": 2399.0, "sl": 2410.0, "tp": 2380.0, "profit": 1.0,
            }],
        )
        assert opened.status_code == 200, opened.text[:300]

        cid = _insert_command(account_id, user_id, "CLOSE", direction="SELL", ticket="800002")
        assert _doc(cid)["status"] == "accepted"

        closed = _heartbeat(user_client, token, "31201", "Tscheck-Recon2", [])
        assert closed.status_code == 200, closed.text[:300]

        stored = _doc(cid)
        assert stored["status"] == "confirmed", f"expected CLOSE to reconcile to confirmed, got {stored['status']}"
    finally:
        cleanup_user(admin, user_id)
