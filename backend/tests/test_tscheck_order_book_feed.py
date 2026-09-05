"""Live order-book feed supports both assets.

Criterion: GET /api/market/order-book returns validated top depth and bounded
imbalance/spread metrics for BTCUSDT (via BTCUSDT) and XAUUSD (via the public
PAXGUSDT proxy, per spec deviations); an unsupported symbol returns 400; and
a provider failure degrades to stale neutral data (never a hard error / crash).
"""

import pytest

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from lib import market  # noqa: E402


def _assert_shape(body: dict, symbol: str) -> None:
    assert body["symbol"] == symbol
    assert isinstance(body["imbalance"], (int, float))
    assert -1.0 <= float(body["imbalance"]) <= 1.0
    assert isinstance(body["near_imbalance"], (int, float))
    assert -1.0 <= float(body["near_imbalance"]) <= 1.0
    if body["spread_bps"] is not None:
        assert float(body["spread_bps"]) >= 0.0
    assert isinstance(body["bids"], list)
    assert isinstance(body["asks"], list)


def test_order_book_supports_btc_and_xau(client):
    btc = client.get("/market/order-book", params={"symbol": "BTCUSDT"})
    assert btc.status_code == 200, f"BTCUSDT order-book failed: {btc.status_code} {btc.text[:300]}"
    btc_body = btc.json()
    _assert_shape(btc_body, "BTCUSDT")

    xau = client.get("/market/order-book", params={"symbol": "XAUUSD"})
    assert xau.status_code == 200, f"XAUUSD order-book failed: {xau.status_code} {xau.text[:300]}"
    xau_body = xau.json()
    _assert_shape(xau_body, "XAUUSD")
    # XAU is proxied through the public Binance PAXGUSDT feed, not broker-native depth.
    assert xau_body["provider_symbol"] == "PAXGUSDT", xau_body

    if not xau_body["stale"]:
        assert len(xau_body["bids"]) > 0 and len(xau_body["asks"]) > 0
        # top-of-book sanity: best ask must be >= best bid
        assert xau_body["asks"][0][0] >= xau_body["bids"][0][0]


def test_order_book_rejects_unsupported_symbol(client):
    resp = client.get("/market/order-book", params={"symbol": "DOGEUSDT"})
    assert resp.status_code == 400, f"expected 400, got {resp.status_code} {resp.text[:300]}"


@pytest.mark.asyncio
async def test_order_book_degrades_to_stale_neutral_on_provider_failure(monkeypatch):
    """Force the upstream depth fetch to fail and confirm lib.market.get_order_book
    (the function the /market/order-book route and strategy engine both call)
    degrades to the documented neutral/stale shape instead of raising.

    Exercised as a direct async call against the real lib.market module (same
    pattern as the paper-trading reverse-exit checks) because the failure has
    to be injected inside the process that owns the httpx client / depth
    cache; the live backend is a separate supervisor-managed process so an
    HTTP-level fault can't be induced from the test process.
    """

    async def _boom(*args, **kwargs):
        raise RuntimeError("simulated provider outage")

    market._depth_cache.pop("BTCUSDT", None)
    monkeypatch.setattr(market, "_rest_get", _boom)

    body = await market.get_order_book("BTCUSDT")
    assert body["stale"] is True
    assert body["imbalance"] == 0.0
    assert body["near_imbalance"] == 0.0
    assert body["bids"] == [] and body["asks"] == []
    assert body["error"]
