"""Command expiry, presence, and entitlement gates protect entries.

An ENTRY command is only dispatched to the EA when it hasn't expired, the
user's browser has recently pinged /presence, auto-trade is enabled on the
account, and (for live accounts) the mt5_live entitlement is currently
active. There is no public API to enqueue an ENTRY command (only the
strategy engine does that) so this test seeds the command document directly
in the same local Mongo the backend uses, then exercises the real
/mt5/bridge/poll HTTP endpoint to verify each gate.
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
        ["mongosh", "bitcoin_terminal", "--quiet", "--eval", js],
        capture_output=True, text=True, timeout=20,
    )
    assert out.returncode == 0, f"mongosh failed: {out.stderr[:400]}"
    return out.stdout


def _insert_entry_command(account_id: str, user_id: str, expires_in_seconds: int | None) -> str:
    cid = str(uuid.uuid4())
    if expires_in_seconds is None:
        expires_at_js = "null"
        expires_epoch = 0
    else:
        expires_at_js = f"new Date(Date.now() + {expires_in_seconds * 1000})"
        expires_epoch = int((datetime.now(timezone.utc) + timedelta(seconds=expires_in_seconds)).timestamp())
    js = f"""
    db.mt5_commands.insertOne({{
      id: "{cid}", idempotency_key: "{cid}", account_id: "{account_id}", user_id: "{user_id}",
      action: "ENTRY", status: "pending", symbol: "BTCUSDT", direction: "BUY", lots: 0.01,
      sl: 2390.0, tp: 2420.0, reason: "tscheck-gate", payload: {{}}, attempts: 0,
      created_at: new Date(), expires_at: {expires_at_js}, expires_epoch: {expires_epoch},
      execution_result: "", broker_retcode: null, completed_at: null
    }})
    """
    _mongo_eval(js)
    return cid


def _command_status(cid: str) -> str:
    out = _mongo_eval(f'JSON.stringify(db.mt5_commands.findOne({{id: "{cid}"}}, {{_id:0,status:1}}))')
    return json.loads(out.strip())["status"]


def _connect_and_heartbeat(user_client, mode="demo", login="88771", server="Tscheck-Gate"):
    resp = user_client.post(
        "/mt5/account", json={"mode": mode, "account_login": login, "broker_server": server, "lot_size": 0.01}
    )
    assert resp.status_code == 200, resp.text[:300]
    account = resp.json()["account"]
    token = resp.json()["bridge_token"]
    hb = user_client.post(
        "/mt5/bridge/heartbeat", headers={"Authorization": f"Bearer {token}"},
        json={
            "account_login": login, "broker_server": server, "is_demo": mode == "demo",
            "resolved_symbol": "BTCUSDT", "ea_version": "1.10", "positions": [], **HEARTBEAT_BASE,
        },
    )
    assert hb.status_code == 200, hb.text[:300]
    return account["id"], token


def test_expired_entry_is_marked_expired(client, backend_url):
    api_url = f"{backend_url}/api"
    user_client, user_id, admin = make_subscribed_user(api_url, "gateexp", days=3)
    try:
        account_id, token = _connect_and_heartbeat(user_client)
        cid = _insert_entry_command(account_id, user_id, expires_in_seconds=-5)
        poll = user_client.post("/mt5/bridge/poll", headers={"Authorization": f"Bearer {token}"}, json={})
        assert poll.status_code == 200, poll.text[:300]
        assert _command_status(cid) == "expired", f"expected expired, got {_command_status(cid)}"
    finally:
        cleanup_user(admin, user_id)


def test_missing_presence_cancels_entry(client, backend_url):
    api_url = f"{backend_url}/api"
    user_client, user_id, admin = make_subscribed_user(api_url, "gatepres", days=3)
    try:
        account_id, token = _connect_and_heartbeat(user_client)
        patch = user_client.patch("/mt5/account", json={"auto_trade_enabled": True})
        assert patch.status_code == 200, patch.text[:300]
        cid = _insert_entry_command(account_id, user_id, expires_in_seconds=30)
        # Deliberately never call POST /presence or GET /dashboard for this user.
        poll = user_client.post("/mt5/bridge/poll", headers={"Authorization": f"Bearer {token}"}, json={})
        assert poll.status_code == 200, poll.text[:300]
        assert _command_status(cid) == "cancelled", f"expected cancelled without presence, got {_command_status(cid)}"
    finally:
        cleanup_user(admin, user_id)


def test_auto_trade_disabled_cancels_entry(client, backend_url):
    api_url = f"{backend_url}/api"
    user_client, user_id, admin = make_subscribed_user(api_url, "gateauto", days=3)
    try:
        account_id, token = _connect_and_heartbeat(user_client)
        presence = user_client.post("/presence")
        assert presence.status_code == 200, presence.text[:300]
        cid = _insert_entry_command(account_id, user_id, expires_in_seconds=30)
        poll = user_client.post("/mt5/bridge/poll", headers={"Authorization": f"Bearer {token}"}, json={})
        assert poll.status_code == 200, poll.text[:300]
        assert _command_status(cid) == "cancelled", f"expected cancelled with auto-trade off, got {_command_status(cid)}"
    finally:
        cleanup_user(admin, user_id)


def test_demo_entry_dispatches_under_base_subscription(client, backend_url):
    api_url = f"{backend_url}/api"
    user_client, user_id, admin = make_subscribed_user(api_url, "gatedemo", days=3)
    try:
        account_id, token = _connect_and_heartbeat(user_client)
        patch = user_client.patch("/mt5/account", json={"auto_trade_enabled": True})
        assert patch.status_code == 200, patch.text[:300]
        presence = user_client.post("/presence")
        assert presence.status_code == 200, presence.text[:300]
        cid = _insert_entry_command(account_id, user_id, expires_in_seconds=30)
        poll = user_client.post("/mt5/bridge/poll", headers={"Authorization": f"Bearer {token}"}, json={})
        assert poll.status_code == 200, poll.text[:300]
        body = poll.json()
        assert body["command"] is not None and body["command"]["id"] == cid
        assert _command_status(cid) == "dispatched", f"expected dispatched demo entry, got {_command_status(cid)}"
    finally:
        cleanup_user(admin, user_id)


def test_live_entry_requires_active_mt5_live_entitlement(client, backend_url):
    api_url = f"{backend_url}/api"
    user_client, user_id, admin = make_subscribed_user(
        api_url, "gatelive", days=3, live_plan_id="mt5-live-monthly"
    )
    try:
        account_id, token = _connect_and_heartbeat(user_client, mode="live", login="99001", server="Tscheck-Live")
        patch = user_client.patch("/mt5/account", json={"auto_trade_enabled": True})
        assert patch.status_code == 200, patch.text[:300]
        presence = user_client.post("/presence")
        assert presence.status_code == 200, presence.text[:300]
        # Expire the live entitlement directly (no admin API revokes mt5_live_subscription
        # specifically; base subscription stays active so the account itself stays gated
        # only by the live add-on, matching the criterion under test).
        _mongo_eval(
            f'db.users.updateOne({{id: "{user_id}"}}, '
            f'{{$set: {{"mt5_live_subscription.status": "expired"}}}})'
        )
        cid = _insert_entry_command(account_id, user_id, expires_in_seconds=30)
        poll = user_client.post("/mt5/bridge/poll", headers={"Authorization": f"Bearer {token}"}, json={})
        assert poll.status_code == 200, poll.text[:300]
        assert _command_status(cid) == "cancelled", f"expected cancelled without live entitlement, got {_command_status(cid)}"
    finally:
        cleanup_user(admin, user_id)
