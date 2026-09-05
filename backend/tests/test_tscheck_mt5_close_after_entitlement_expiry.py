"""MT5 commercial gating: existing positions stay managed after entitlement expiry.

Criterion: both demo/live require normal plus MT5 Auto-Trading subscriptions
for NEW entries (covered by test_tscheck_mt5_command_gates.py's ENTRY-gate
tests and test_tscheck_razorpay_billing.py's plan/billing coverage), existing
positions stay managed after expiry, and hard disconnect with an open trade
revokes/cancels immediately while marking the position detached (covered by
test_tscheck_mt5_hard_disconnect.py). This file covers the remaining,
previously-uncovered half: a CLOSE command for an already-open position must
still be dispatched to the EA even after the account's mt5_live entitlement
has expired -- the bridge poll's entitlement gate only applies to ENTRY.
"""

import json
import subprocess
import uuid
from datetime import datetime, timedelta, timezone

from .helpers import DB_NAME, cleanup_user, make_subscribed_user

HEARTBEAT_BASE = {
    "balance": 5000.0, "equity": 5000.0, "free_margin": 5000.0,
    "volume_min": 0.01, "volume_max": 50.0, "volume_step": 0.01,
    "trade_allowed": True, "algo_trading": True,
}


def _mongo_eval(js: str) -> str:
    out = subprocess.run(
        ["mongosh", DB_NAME, "--quiet", "--eval", js],
        capture_output=True, text=True, timeout=20,
    )
    assert out.returncode == 0, f"mongosh failed: {out.stderr[:400]}"
    return out.stdout


def _insert_close_command(account_id: str, user_id: str, ticket: str) -> str:
    cid = str(uuid.uuid4())
    expires_epoch = int((datetime.now(timezone.utc) + timedelta(seconds=30)).timestamp())
    js = f"""
    db.mt5_commands.insertOne({{
      id: "{cid}", idempotency_key: "{cid}", account_id: "{account_id}", user_id: "{user_id}",
      action: "CLOSE", status: "pending", symbol: "BTCUSDT", ticket: "{ticket}", reason: "tscheck-close",
      payload: {{}}, attempts: 0, created_at: new Date(),
      expires_at: new Date(Date.now() + 30000), expires_epoch: {expires_epoch},
      execution_result: "", broker_retcode: null, completed_at: null
    }})
    """
    _mongo_eval(js)
    return cid


def _command_status(cid: str) -> str:
    out = _mongo_eval(f'JSON.stringify(db.mt5_commands.findOne({{id: "{cid}"}}, {{_id:0,status:1}}))')
    return json.loads(out.strip())["status"]


def test_close_command_dispatches_after_live_entitlement_expires(client, backend_url):
    api_url = f"{backend_url}/api"
    user_client, user_id, admin = make_subscribed_user(
        api_url, "closeafterexpiry", days=3, live_plan_id="mt5-live-monthly"
    )
    try:
        connect = user_client.post(
            "/mt5/account",
            json={"mode": "live", "account_login": "77002", "broker_server": "Tscheck-CloseExpiry", "lot_size": 0.01},
        )
        assert connect.status_code == 200, connect.text[:300]
        account_id = connect.json()["account"]["id"]
        token = connect.json()["bridge_token"]

        ticket = "5551234"
        hb = user_client.post(
            "/mt5/bridge/heartbeat", headers={"Authorization": f"Bearer {token}"},
            json={
                "account_login": "77002", "broker_server": "Tscheck-CloseExpiry", "is_demo": False,
                "resolved_symbol": "BTCUSDT", "ea_version": "1.10",
                "positions": [{
                    "ticket": ticket, "symbol": "BTCUSDT", "direction": "BUY", "volume": 0.01,
                    "entry_price": 60000.0, "current_price": 60050.0, "sl": 59500.0, "tp": 61000.0,
                    "profit": 5.0,
                }],
                **HEARTBEAT_BASE,
            },
        )
        assert hb.status_code == 200, hb.text[:300]

        patch = user_client.patch("/mt5/account", json={"auto_trade_enabled": True})
        assert patch.status_code == 200, patch.text[:300]
        presence = user_client.post("/presence")
        assert presence.status_code == 200, presence.text[:300]

        # Expire the live entitlement while the position is already open.
        _mongo_eval(
            f'db.users.updateOne({{id: "{user_id}"}}, '
            f'{{$set: {{"mt5_live_subscription.status": "expired"}}}})'
        )

        # A brand-new ENTRY is still correctly blocked (regression guard for the gate itself).
        entry_cid = str(uuid.uuid4())
        _mongo_eval(f"""
        db.mt5_commands.insertOne({{
          id: "{entry_cid}", idempotency_key: "{entry_cid}", account_id: "{account_id}", user_id: "{user_id}",
          action: "ENTRY", status: "pending", symbol: "BTCUSDT", direction: "BUY", lots: 0.01,
          sl: 0, tp: 0, reason: "tscheck-entry-guard", payload: {{}}, attempts: 0,
          created_at: new Date(), expires_at: new Date(Date.now() + 30000),
          expires_epoch: {int((datetime.now(timezone.utc) + timedelta(seconds=30)).timestamp())},
          execution_result: "", broker_retcode: null, completed_at: null
        }})
        """)
        poll_entry = user_client.post("/mt5/bridge/poll", headers={"Authorization": f"Bearer {token}"}, json={})
        assert poll_entry.status_code == 200, poll_entry.text[:300]
        assert _command_status(entry_cid) == "cancelled", (
            f"expected the new ENTRY to still be blocked, got {_command_status(entry_cid)}"
        )

        # But a CLOSE for the already-open position must still be dispatched.
        close_cid = _insert_close_command(account_id, user_id, ticket)
        poll_close = user_client.post("/mt5/bridge/poll", headers={"Authorization": f"Bearer {token}"}, json={})
        assert poll_close.status_code == 200, poll_close.text[:300]
        body = poll_close.json()
        assert body.get("command") is not None, "CLOSE command was not returned to the EA at all"
        assert body["command"]["id"] == close_cid
        assert body["command"]["action"] == "CLOSE"
        assert _command_status(close_cid) == "dispatched", (
            f"expected the CLOSE to be dispatched despite expired entitlement, got {_command_status(close_cid)}"
        )
    finally:
        cleanup_user(admin, user_id)
