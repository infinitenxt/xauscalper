"""Shared helpers for auth-based tscheck backend tests."""

import httpx

ADMIN_EMAIL = "admin@infinitenxt.com"
ADMIN_PASSWORD = "Harsh@10576"


def login_admin(api_url: str) -> httpx.Client:
    """Return an httpx.Client with a valid admin session cookie set.

    The server issues the session cookie with the `Secure` attribute (correct
    for the real https ingress). httpx's cookie jar honours that flag and
    silently drops it on the plain-http localhost connection this suite runs
    against, so the cookie is pulled out of the login response and attached
    as an explicit header instead of relying on the jar.
    """
    c = httpx.Client(base_url=api_url, timeout=30.0)
    resp = c.post("/auth/login", json={"email": ADMIN_EMAIL, "password": ADMIN_PASSWORD})
    assert resp.status_code == 200, f"admin login failed: {resp.status_code} {resp.text[:300]}"
    session_cookie = resp.cookies.get("gt_session")
    assert session_cookie, f"no gt_session cookie in login response: {resp.headers}"
    c.headers["Cookie"] = f"gt_session={session_cookie}"
    return c
