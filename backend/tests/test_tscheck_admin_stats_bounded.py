"""Admin stats query remains functional after bounding.

Verifies GET /api/admin/stats returns 200 with the expected shape after
admin login, and that it stays rejected without a session.
"""

import httpx

from .helpers import login_admin

API_URL = "http://localhost:8001/api"


def test_admin_stats_returns_bounded_fields():
    client = login_admin(API_URL)
    try:
        resp = client.get("/admin/stats")
        assert resp.status_code == 200, f"unexpected status: {resp.status_code} {resp.text[:300]}"
        body = resp.json()
        for field in ("users_total", "subscribers", "payments", "plans", "invites_pending"):
            assert field in body, f"missing field {field} in {body}"
            assert isinstance(body[field], int), f"field {field} not int: {body[field]!r}"
    finally:
        client.close()


def test_admin_stats_requires_auth():
    with httpx.Client(base_url=API_URL, timeout=30.0) as c:
        resp = c.get("/admin/stats")
        assert resp.status_code in (401, 403), f"unexpected status: {resp.status_code} {resp.text[:300]}"
