"""MT5 account routes are tenant-authenticated and subscription-gated.

Unauthenticated requests to the account/command endpoints must be rejected,
and a subscribed user must be able to read their own (initially empty)
account state without errors.
"""

from .helpers import cleanup_user, make_subscribed_user


def test_mt5_account_requires_auth(client):
    resp = client.get("/mt5/account")
    assert resp.status_code == 401, f"expected 401, got {resp.status_code} {resp.text[:300]}"

    resp2 = client.post(
        "/mt5/account",
        json={"mode": "demo", "account_login": "12345", "broker_server": "Broker-Demo", "lot_size": 0.01},
    )
    assert resp2.status_code == 401, f"expected 401, got {resp2.status_code} {resp2.text[:300]}"

    resp3 = client.get("/mt5/commands")
    assert resp3.status_code == 401, f"expected 401, got {resp3.status_code} {resp3.text[:300]}"


def test_subscribed_user_reads_empty_mt5_account_state(client, backend_url):
    api_url = f"{backend_url}/api"
    user_client, user_id, admin = make_subscribed_user(api_url, "authgate", days=3)
    try:
        resp = user_client.get("/mt5/account")
        assert resp.status_code == 200, f"expected 200, got {resp.status_code} {resp.text[:300]}"
        assert resp.json() is None, f"expected empty account state, got {resp.text[:300]}"

        cmds = user_client.get("/mt5/commands")
        assert cmds.status_code == 200
        assert cmds.json() == []
    finally:
        cleanup_user(admin, user_id)


def test_unsubscribed_user_is_gated_from_mt5(client, backend_url):
    api_url = f"{backend_url}/api"
    # days=0 with no plan_id/revoke should fail the grant call itself (400); instead
    # verify the gate directly: a freshly registered (unsubscribed) user gets 402.
    from .helpers import AdminSession
    import uuid

    admin = AdminSession(api_url)
    suffix = uuid.uuid4().hex[:10]
    email = f"tscheck-nosub-{suffix}@example.com"
    username = f"tscheck-nosub-{suffix}"[:24]
    inv = admin.post("/admin/invites", json={"email": email, "note": "tscheck-nosub"})
    assert inv.status_code == 201
    import httpx

    user_client = httpx.Client(base_url=api_url, timeout=30.0)
    reg = user_client.post(
        "/auth/register", json={"email": email, "username": username, "password": "Tscheck!12345"}
    )
    assert reg.status_code == 201
    session_cookie = reg.cookies.get("gt_session")
    user_client.headers["Cookie"] = f"gt_session={session_cookie}"
    user_id = reg.json()["user"]["id"]
    try:
        resp = user_client.get("/mt5/account")
        assert resp.status_code == 402, f"expected 402 for unsubscribed user, got {resp.status_code} {resp.text[:300]}"
    finally:
        cleanup_user(admin, user_id)
