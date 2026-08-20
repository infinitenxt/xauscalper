"""Backend coverage for the signal engine criterion:
signal direction, confidence, 11 weighted confirmations, and risk gates.
"""


def test_signal_returns_11_confirmations_and_valid_direction(client):
    resp = client.get("/signal", params={"timeframe": "15m"})
    assert resp.status_code == 200, f"GET /signal?timeframe=15m -> {resp.status_code}: {resp.text[:300]}"
    body = resp.json()

    assert body["direction"] in ("BUY", "SELL", "WAIT"), body["direction"]
    assert isinstance(body["confidence"], (int, float))

    confirmations = body["confirmations"]
    assert len(confirmations) == 11, f"expected 11 confirmations, got {len(confirmations)}: {confirmations}"
    for c in confirmations:
        assert "name" in c and "weight" in c and "direction" in c and "detail" in c
        assert c["direction"] in ("BULLISH", "BEARISH", "NEUTRAL")

    total_weight = sum(c["weight"] for c in confirmations)
    assert total_weight > 0, f"confirmation weights should be positive, got {total_weight}"

    risk_checks = body["risk_checks"]
    assert len(risk_checks) == 5, f"expected 5 risk gates, got {len(risk_checks)}: {risk_checks}"
    for gate in risk_checks:
        assert "name" in gate and "passed" in gate and "detail" in gate
        assert isinstance(gate["passed"], bool)


def test_signal_invalid_timeframe_rejected(client):
    resp = client.get("/signal", params={"timeframe": "7m"})
    assert resp.status_code == 400, f"GET /signal?timeframe=7m -> expected 400, got {resp.status_code}: {resp.text[:300]}"


def test_dashboard_includes_signal_and_wallet(client):
    resp = client.get("/dashboard", params={"timeframe": "15m"})
    assert resp.status_code == 200, f"GET /dashboard?timeframe=15m -> {resp.status_code}: {resp.text[:300]}"
    body = resp.json()
    for field in ("feed", "ticker", "signal", "wallet", "open_trade", "history"):
        assert field in body, f"missing field {field} in dashboard response: {list(body.keys())}"
    assert len(body["signal"]["risk_checks"]) == 5
