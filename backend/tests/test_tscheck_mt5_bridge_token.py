"""Secure bridge creation and token handling.

Creating a demo bridge returns exactly one plaintext token and a host-neutral
/api/mt5/bridge path; Mongo stores only token_hash (never the raw token);
wrong or revoked bearer tokens are rejected with 401.
"""

import subprocess
import json

from .helpers import DB_NAME, cleanup_user, make_subscribed_user


def _mongo_find_account(account_id: str):
    """Read the raw mt5_accounts document via the mongo shell to confirm no
    plaintext token is persisted (never import the app / mock the db - this
    goes through the real local mongod the backend itself uses)."""
    script = (
        "db.mt5_accounts.findOne({id: '%s'}, {_id: 0})" % account_id
    )
    out = subprocess.run(
        ["mongosh", DB_NAME, "--quiet", "--eval", script],
        capture_output=True, text=True, timeout=20,
    )
    return out.stdout


def test_bridge_create_returns_one_token_and_hides_it_in_mongo(client, backend_url):
    api_url = f"{backend_url}/api"
    user_client, user_id, admin = make_subscribed_user(api_url, "bridge", days=3, live_plan_id="mt5-live-monthly")
    try:
        resp = user_client.post(
            "/mt5/account",
            json={"mode": "demo", "account_login": "555111", "broker_server": "Tscheck-Demo", "lot_size": 0.01},
        )
        assert resp.status_code == 200, f"expected 200, got {resp.status_code} {resp.text[:300]}"
        body = resp.json()
        assert body["bridge_url"] == "/api/mt5/bridge", body["bridge_url"]
        assert not body["bridge_url"].startswith("http"), "bridge_url must be host-neutral"
        token = body["bridge_token"]
        assert isinstance(token, str) and len(token) > 20

        account_id = body["account"]["id"]
        raw = _mongo_find_account(account_id)
        assert "token_hash" in raw, f"mongo doc missing token_hash field: {raw[:400]}"
        assert token not in raw, "plaintext bridge token must never be persisted in mongo"

        # Wrong token -> 401
        bad = user_client.post(
            "/mt5/bridge/heartbeat",
            headers={"Authorization": "Bearer not-the-real-token"},
            json={
                "account_login": "555111", "broker_server": "Tscheck-Demo", "is_demo": True,
                "resolved_symbol": "BTCUSDT", "balance": 1000, "equity": 1000, "free_margin": 1000,
                "volume_min": 0.01, "volume_max": 50, "volume_step": 0.01,
                "trade_allowed": True, "algo_trading": True, "positions": [],
            },
        )
        assert bad.status_code == 401, f"expected 401 for wrong token, got {bad.status_code} {bad.text[:300]}"

        # Correct token -> 200
        good = user_client.post(
            "/mt5/bridge/heartbeat",
            headers={"Authorization": f"Bearer {token}"},
            json={
                "account_login": "555111", "broker_server": "Tscheck-Demo", "is_demo": True,
                "resolved_symbol": "BTCUSDT", "balance": 1000, "equity": 1000, "free_margin": 1000,
                "volume_min": 0.01, "volume_max": 50, "volume_step": 0.01,
                "trade_allowed": True, "algo_trading": True, "positions": [],
            },
        )
        assert good.status_code == 200, f"expected 200 for correct token, got {good.status_code} {good.text[:300]}"

        # Revoke the account (disconnect) then confirm the same token is rejected
        disc = user_client.delete("/mt5/account")
        assert disc.status_code == 200, disc.text[:300]
        revoked = user_client.post(
            "/mt5/bridge/heartbeat",
            headers={"Authorization": f"Bearer {token}"},
            json={
                "account_login": "555111", "broker_server": "Tscheck-Demo", "is_demo": True,
                "resolved_symbol": "BTCUSDT", "balance": 1000, "equity": 1000, "free_margin": 1000,
                "volume_min": 0.01, "volume_max": 50, "volume_step": 0.01,
                "trade_allowed": True, "algo_trading": True, "positions": [],
            },
        )
        assert revoked.status_code == 401, f"expected 401 for revoked token, got {revoked.status_code} {revoked.text[:300]}"
    finally:
        cleanup_user(admin, user_id)
