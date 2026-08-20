"""Criterion: trading routes require auth.

Without a session cookie, /dashboard, /wallet, /trades and /backtest must
return 401 (not 500/422).
"""

from .conftest import api_url
import httpx


def test_unauthenticated_requests_get_401():
    with httpx.Client(base_url=api_url(), timeout=30.0) as c:
        for path, params in (
            ("/dashboard", None),
            ("/wallet", None),
            ("/trades", None),
            ("/backtest", {"timeframe": "5m", "days": 1}),
        ):
            resp = c.get(path, params=params)
            assert resp.status_code == 401, (
                f"GET {path} without auth -> expected 401, got {resp.status_code}: {resp.text[:300]}"
            )
