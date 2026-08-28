"""Shared helpers for auth-based tscheck backend tests."""

import time
import uuid

import httpx

ADMIN_EMAIL = "admin@infinitenxt.com"
ADMIN_PASSWORD = "Harsh@10576"


def _attach_cookie(c: httpx.Client, resp: httpx.Response) -> None:
    """Pull the session cookie out of a login/register response and attach it as a
    header. The server sets it `Secure`, which httpx's jar silently drops over
    plain-http localhost, so we bypass the jar entirely.
    """
    session_cookie = resp.cookies.get("gt_session")
    assert session_cookie, f"no gt_session cookie in response: {resp.headers}"
    c.headers["Cookie"] = f"gt_session={session_cookie}"


def login_admin(api_url: str) -> httpx.Client:
    """Return an httpx.Client with a valid admin session cookie set."""
    c = httpx.Client(base_url=api_url, timeout=30.0)
    resp = c.post("/auth/login", json={"email": ADMIN_EMAIL, "password": ADMIN_PASSWORD})
    assert resp.status_code == 200, f"admin login failed: {resp.status_code} {resp.text[:300]}"
    _attach_cookie(c, resp)
    return c


class AdminSession:
    """Admin session wrapper that transparently re-authenticates on 401.

    The app enforces one active session per account ("one login per device
    only"), so any *other* pytest-xdist worker logging in as the same admin
    mid-test invalidates this session. Every call retries once after a fresh
    login, which is enough to ride out that cross-worker race without
    touching the app's single-session behaviour.
    """

    def __init__(self, api_url: str):
        self.api_url = api_url
        self.client = login_admin(api_url)

    def _relogin(self) -> None:
        self.client = login_admin(self.api_url)

    def _with_retry(self, method: str, path: str, **kwargs) -> httpx.Response:
        resp = getattr(self.client, method)(path, **kwargs)
        attempts = 0
        while resp.status_code == 401 and attempts < 4:
            time.sleep(0.15 * (attempts + 1))
            self._relogin()
            resp = getattr(self.client, method)(path, **kwargs)
            attempts += 1
        return resp

    def post(self, path: str, **kwargs) -> httpx.Response:
        return self._with_retry("post", path, **kwargs)

    def get(self, path: str, **kwargs) -> httpx.Response:
        return self._with_retry("get", path, **kwargs)

    def delete(self, path: str, **kwargs) -> httpx.Response:
        return self._with_retry("delete", path, **kwargs)


def make_subscribed_user(api_url: str, slug: str, *, days: int = 3, live_plan_id: str | None = None):
    """Create an isolated tscheck-* user, invite+register it, log it in, and
    optionally grant a base subscription (always) and the mt5-live-monthly
    add-on (if live_plan_id is given).

    Returns (user_client, user_id, admin_session) so callers can use the
    admin session for grants/cleanup and the user_client for the actual test
    calls. Caller is responsible for deleting the user via admin_session in
    a finally.
    """
    admin = AdminSession(api_url)
    suffix = uuid.uuid4().hex[:10]
    email = f"tscheck-{slug}-{suffix}@example.com"
    username = f"tscheck-{slug}-{suffix}"[:24]
    password = "Tscheck!12345"

    inv = admin.post("/admin/invites", json={"email": email, "note": f"tscheck-{slug}"})
    assert inv.status_code == 201, f"invite failed: {inv.status_code} {inv.text[:300]}"

    user_client = httpx.Client(base_url=api_url, timeout=30.0)
    reg = user_client.post(
        "/auth/register", json={"email": email, "username": username, "password": password}
    )
    assert reg.status_code == 201, f"register failed: {reg.status_code} {reg.text[:300]}"
    _attach_cookie(user_client, reg)
    user_id = reg.json()["user"]["id"]

    grant = admin.post(f"/admin/users/{user_id}/subscription", json={"days": days})
    assert grant.status_code == 200, f"grant failed: {grant.status_code} {grant.text[:300]}"

    if live_plan_id:
        grant_live = admin.post(f"/admin/users/{user_id}/subscription", json={"plan_id": live_plan_id})
        assert grant_live.status_code == 200, f"live grant failed: {grant_live.status_code} {grant_live.text[:300]}"

    return user_client, user_id, admin


def cleanup_user(admin_session: "AdminSession | httpx.Client", user_id: str) -> None:
    admin_session.delete(f"/admin/users/{user_id}")
