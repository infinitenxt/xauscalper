"""Admin-session-dependent criteria, kept in ONE module on purpose.

The app enforces a single active session per account (a new login on the
same account invalidates any other session's cookie). pytest-xdist runs
different modules on different workers concurrently, so any two modules
that each log in as admin would race and knock each other's cookie out.
Keeping all admin-login flows in one module pins them to a single xdist
worker (loadscope) and lets them run in a safe, deterministic order:

1. test_1_admin_wallet_and_trades_scoped_to_user  - per-user wallet + private history
2. test_2_backtest_session_breakdown_fields       - backtest API session fields
3. test_3_new_admin_credentials_work              - new admin creds 200, old admin creds 401
4. test_4_invite_only_registration_flow           - invite required, used flag, 409 on repeat
5. test_5_self_service_password_change            - wrong current 401, valid change works, revert
6. test_6_admin_force_password_reset              - >=8 char reset works, <8 char is 422
9. test_9_presence_lapses_but_engine_keeps_running - presence lapse (must run
   last: it needs a >30s window with NO /dashboard or /presence calls, so
   nothing earlier in this file is allowed to touch presence afterwards)
"""

import time
import uuid

from .conftest import api_url
from .helpers import ADMIN_EMAIL, ADMIN_PASSWORD, login_admin
import httpx

REQUIRED_SESSION_FIELDS = (
    "session",
    "trades",
    "wins",
    "losses",
    "win_rate",
    "net_pnl",
    "avg_r",
    "profit_factor",
    "share_pct",
)


def test_1_admin_wallet_and_trades_scoped_to_user():
    c = login_admin(api_url())
    try:
        dash_resp = c.get("/dashboard")
        assert dash_resp.status_code == 200, f"GET /dashboard -> {dash_resp.status_code}: {dash_resp.text[:300]}"
        dash = dash_resp.json()
        assert dash["wallet"]["starting_balance"] == 10000.0, dash["wallet"]

        wallet_resp = c.get("/wallet")
        assert wallet_resp.status_code == 200, f"GET /wallet -> {wallet_resp.status_code}: {wallet_resp.text[:300]}"
        wallet = wallet_resp.json()
        assert wallet["starting_balance"] == 10000.0, wallet
        admin_user_id = wallet["id"]

        trades_resp = c.get("/trades")
        assert trades_resp.status_code == 200, f"GET /trades -> {trades_resp.status_code}: {trades_resp.text[:300]}"
        trades = trades_resp.json()
        assert isinstance(trades, list), trades
        for t in trades:
            assert t.get("user_id") == admin_user_id, (
                f"trade {t.get('id')} has user_id={t.get('user_id')} != signed-in user {admin_user_id}"
            )
    finally:
        c.close()


def test_2_backtest_session_breakdown_fields():
    c = login_admin(api_url())
    try:
        resp = c.get("/backtest", params={"timeframe": "5m", "days": 1})
        assert resp.status_code == 200, f"GET /backtest -> {resp.status_code}: {resp.text[:300]}"
        body = resp.json()

        assert "best_session" in body and isinstance(body["best_session"], str), body.get("best_session")
        assert "worst_session" in body and isinstance(body["worst_session"], str), body.get("worst_session")

        breakdown = body["session_breakdown"]
        assert isinstance(breakdown, list) and len(breakdown) > 0, f"expected non-empty session_breakdown: {breakdown}"
        for entry in breakdown:
            for field in REQUIRED_SESSION_FIELDS:
                assert field in entry, f"session_breakdown entry missing '{field}': {entry}"
    finally:
        c.close()


def test_3_new_admin_credentials_work():
    with httpx.Client(base_url=api_url(), timeout=30.0) as c:
        resp = c.post("/auth/login", json={"email": ADMIN_EMAIL, "password": ADMIN_PASSWORD})
        assert resp.status_code == 200, f"POST /auth/login (new admin) -> {resp.status_code}: {resp.text[:300]}"
        body = resp.json()
        assert body["user"]["username"] == "Admin", body["user"]
        assert body["user"]["role"] == "admin", body["user"]

        old = c.post("/auth/login", json={"email": "admin@goldterminal.app", "password": ADMIN_PASSWORD})
        assert old.status_code == 401, f"POST /auth/login (old admin) -> expected 401, got {old.status_code}: {old.text[:300]}"


def test_4_invite_only_registration_flow():
    suffix = uuid.uuid4().hex[:8]
    email = f"tscheck-invite-{suffix}@example.com"
    username = f"tscheck_{suffix}"
    admin = login_admin(api_url())
    try:
        # register before invite exists -> 403
        with httpx.Client(base_url=api_url(), timeout=30.0) as anon:
            pre = anon.post(
                "/auth/register", json={"email": email, "username": username, "password": "Str0ngPass1"}
            )
            assert pre.status_code == 403, f"POST /auth/register (no invite) -> expected 403, got {pre.status_code}: {pre.text[:300]}"

            invite_resp = admin.post("/admin/invites", json={"email": email, "note": "tscheck fixture"})
            assert invite_resp.status_code == 201, f"POST /admin/invites -> {invite_resp.status_code}: {invite_resp.text[:300]}"
            assert invite_resp.json()["used"] is False, invite_resp.json()

            reg = anon.post(
                "/auth/register", json={"email": email, "username": username, "password": "Str0ngPass1"}
            )
            assert reg.status_code == 201, f"POST /auth/register (with invite) -> {reg.status_code}: {reg.text[:300]}"

            invites = admin.get("/admin/invites")
            assert invites.status_code == 200, invites.text[:300]
            row = next((r for r in invites.json() if r["email"] == email), None)
            assert row is not None and row["used"] is True, f"invite for {email} not flipped to used: {row}"

            again = anon.post(
                "/auth/register", json={"email": email, "username": username + "x", "password": "Str0ngPass1"}
            )
            assert again.status_code == 409, f"POST /auth/register (repeat) -> expected 409, got {again.status_code}: {again.text[:300]}"
    finally:
        try:
            users = admin.get("/admin/users", params={"q": email})
            for u in users.json():
                if u["email"] == email:
                    admin.delete(f"/admin/users/{u['id']}")
        finally:
            admin.delete(f"/admin/invites/{email}")
            admin.close()


def test_5_self_service_password_change():
    c = login_admin(api_url())
    try:
        temp_password = "TempPass9!"
        wrong = c.post("/auth/password", json={"current_password": "definitely-wrong", "new_password": temp_password})
        assert wrong.status_code == 401, f"POST /auth/password (wrong current) -> expected 401, got {wrong.status_code}: {wrong.text[:300]}"

        changed = c.post("/auth/password", json={"current_password": ADMIN_PASSWORD, "new_password": temp_password})
        assert changed.status_code == 200, f"POST /auth/password -> {changed.status_code}: {changed.text[:300]}"

        with httpx.Client(base_url=api_url(), timeout=30.0) as fresh:
            login_new = fresh.post("/auth/login", json={"email": ADMIN_EMAIL, "password": temp_password})
            assert login_new.status_code == 200, f"login with new password -> {login_new.status_code}: {login_new.text[:300]}"
    finally:
        # revert to the documented admin password so later tests / handback stay valid
        with httpx.Client(base_url=api_url(), timeout=30.0) as revert_client:
            login_temp = revert_client.post("/auth/login", json={"email": ADMIN_EMAIL, "password": "TempPass9!"})
            if login_temp.status_code == 200:
                cookie = login_temp.cookies.get("gt_session")
                revert_client.headers["Cookie"] = f"gt_session={cookie}"
                revert_client.post(
                    "/auth/password",
                    json={"current_password": "TempPass9!", "new_password": ADMIN_PASSWORD},
                )
        c.close()


def test_6_admin_force_password_reset():
    suffix = uuid.uuid4().hex[:8]
    email = f"tscheck-reset-{suffix}@example.com"
    username = f"tscheck_r_{suffix}"
    admin = login_admin(api_url())
    user_id = None
    try:
        invite_resp = admin.post("/admin/invites", json={"email": email, "note": "tscheck fixture"})
        assert invite_resp.status_code == 201, invite_resp.text[:300]

        with httpx.Client(base_url=api_url(), timeout=30.0) as anon:
            reg = anon.post(
                "/auth/register", json={"email": email, "username": username, "password": "InitialPass1"}
            )
            assert reg.status_code == 201, f"POST /auth/register -> {reg.status_code}: {reg.text[:300]}"
            user_id = reg.json()["user"]["id"]

        short = admin.post(f"/admin/users/{user_id}/password", json={"new_password": "short"})
        assert short.status_code == 422, f"POST /admin/users/{{id}}/password (short) -> expected 422, got {short.status_code}: {short.text[:300]}"

        new_password = "ForcedReset9!"
        ok = admin.post(f"/admin/users/{user_id}/password", json={"new_password": new_password})
        assert ok.status_code == 200, f"POST /admin/users/{{id}}/password -> {ok.status_code}: {ok.text[:300]}"

        with httpx.Client(base_url=api_url(), timeout=30.0) as anon2:
            login_resp = anon2.post("/auth/login", json={"email": email, "password": new_password})
            assert login_resp.status_code == 200, f"login with forced password -> {login_resp.status_code}: {login_resp.text[:300]}"
    finally:
        if user_id:
            try:
                admin.delete(f"/admin/users/{user_id}")
            except Exception:
                pass
        admin.delete(f"/admin/invites/{email}")
        admin.close()


def test_9_presence_lapses_but_engine_keeps_running():
    c = login_admin(api_url())
    try:
        # Do NOT call /presence or /dashboard during this window - simulate the dashboard being closed.
        time.sleep(31)

        dash = c.get("/dashboard")
        assert dash.status_code == 200, f"GET /dashboard -> {dash.status_code}: {dash.text[:300]}"
        guards = dash.json()["guards"]
        assert "present" in guards, guards
        # Soft per spec ("may be false") - just confirm the field is boolean and coherent.
        assert isinstance(guards["present"], bool), guards

        with httpx.Client(base_url=api_url(), timeout=30.0) as anon:
            health = anon.get("/engine/health")
            assert health.status_code == 200, f"GET /engine/health -> {health.status_code}: {health.text[:300]}"
            assert health.json()["running"] is True, health.json()
    finally:
        c.close()
