"""Acknowledgements distinguish acceptance from execution.

An "accepted" ACK leaves the command in the accepted state; an "executed"
ACK confirms it; broker retcode/deal/ticket are persisted; and a terminal
state (confirmed/cancelled/expired) cannot be overwritten by a late ACK.
"""

import json
import subprocess
import uuid
from datetime import datetime, timedelta, timezone

from .helpers import cleanup_user, make_subscribed_user

HEARTBEAT_BASE = {
    "balance": 5000.0, "equity": 5000.0, "free_margin": 5000.0,
    "volume_min": 0.01, "volume_max": 50.0, "volume_step": 0.01,
    "trade_allowed": True, "algo_trading": True,
}


def _mongo_eval(js: str) -> str:
    out = subprocess.run(
        ["mongosh", "gold_terminal", "--quiet", "--eval", js],
        capture_output=True, text=True, timeout=20,
    )
    assert out.returncode == 0, f"mongosh failed: {out.stderr[:400]}"
    return out.stdout


def _insert_command(account_id: str, user_id: str, action: str = "ENTRY", status: str = "dispatched") -> str:
    cid = str(uuid.uuid4())
    js = f"""
    db.mt5_commands.insertOne({{
      id: "{cid}", idempotency_key: "{cid}", account_id: "{account_id}", user_id: "{user_id}",
      action: "{action}", status: "{status}", symbol: "XAUUSD", direction: "BUY", lots: 0.01,
      sl: 2390.0, tp: 2420.0, reason: "tscheck-ack", payload: {{}}, attempts: 1,
      created_at: new Date(), expires_at: new Date(Date.now()+30000), expires_epoch: 0,
      execution_result: "", broker_retcode: null, completed_at: null
    }})
    """
    _mongo_eval(js)
    return cid


def _doc(cid: str) -> dict:
    out = _mongo_eval(f'JSON.stringify(db.mt5_commands.findOne({{id: "{cid}"}}, {{_id:0}}))')
    return json.loads(out.strip())


def _connect_and_heartbeat(user_client) -> tuple[str, str]:
    resp = user_client.post(
        "/mt5/account",
        json={"mode": "demo", "account_login": "44221", "broker_server": "Tscheck-Ack", "lot_size": 0.01},
    )
    assert resp.status_code == 200, resp.text[:300]
    account = resp.json()["account"]
    token = resp.json()["bridge_token"]
    hb = user_client.post(
        "/mt5/bridge/heartbeat", headers={"Authorization": f"Bearer {token}"},
        json={
            "account_login": "44221", "broker_server": "Tscheck-Ack", "is_demo": True,
            "resolved_symbol": "XAUUSD", "ea_version": "1.10", "positions": [], **HEARTBEAT_BASE,
        },
    )
    assert hb.status_code == 200, hb.text[:300]
    return account["id"], token


def test_accepted_ack_leaves_command_accepted_then_executed_confirms(client, backend_url):
    api_url = f"{backend_url}/api"
    user_client, user_id, admin = make_subscribed_user(api_url, "ackflow", days=3)
    try:
        account_id, token = _connect_and_heartbeat(user_client)
        cid = _insert_command(account_id, user_id)

        accepted = user_client.post(
            "/mt5/bridge/ack", headers={"Authorization": f"Bearer {token}"},
            json={"command_id": cid, "result": "accepted"},
        )
        assert accepted.status_code == 200, accepted.text[:300]
        assert accepted.json()["status"] == "accepted"
        assert _doc(cid)["status"] == "accepted"

        executed = user_client.post(
            "/mt5/bridge/ack", headers={"Authorization": f"Bearer {token}"},
            json={
                "command_id": cid, "result": "executed",
                "broker_ticket": "500900", "broker_deal": "600900", "broker_retcode": 10009,
                "broker_message": "TRADE_RETCODE_DONE", "filled_price": 2400.5, "filled_volume": 0.01,
            },
        )
        assert executed.status_code == 200, executed.text[:300]
        body = executed.json()
        assert body["status"] == "confirmed", body
        assert body["broker_ticket"] == "500900"
        assert body["broker_deal"] == "600900"
        assert body["broker_retcode"] == 10009

        stored = _doc(cid)
        assert stored["status"] == "confirmed"
        assert stored["broker_ticket"] == "500900"
        assert stored["broker_retcode"] == 10009
    finally:
        cleanup_user(admin, user_id)


def test_terminal_state_is_not_overwritten_by_late_ack(client, backend_url):
    api_url = f"{backend_url}/api"
    user_client, user_id, admin = make_subscribed_user(api_url, "acklate", days=3)
    try:
        account_id, token = _connect_and_heartbeat(user_client)
        cid = _insert_command(account_id, user_id, status="expired")

        late = user_client.post(
            "/mt5/bridge/ack", headers={"Authorization": f"Bearer {token}"},
            json={"command_id": cid, "result": "executed", "broker_ticket": "999999"},
        )
        assert late.status_code == 200, late.text[:300]
        assert late.json()["status"] == "expired", "a terminal state must not be overwritten by a late ACK"
        stored = _doc(cid)
        assert stored["status"] == "expired"
        assert stored.get("broker_ticket") is None, "late ACK payload must not leak into a terminal command"
    finally:
        cleanup_user(admin, user_id)
