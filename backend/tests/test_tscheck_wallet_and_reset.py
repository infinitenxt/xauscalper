"""Backend coverage for the paper wallet criterion and the reset-account criterion."""


def test_wallet_shape_and_fields(client):
    resp = client.get("/wallet")
    assert resp.status_code == 200, f"GET /wallet -> {resp.status_code}: {resp.text[:300]}"
    body = resp.json()
    for field in (
        "balance",
        "starting_balance",
        "realized_pnl",
        "unrealized_pnl",
        "equity",
        "win_rate",
        "return_pct",
    ):
        assert field in body, f"missing field {field} in wallet response: {body}"
    assert body["starting_balance"] == 10000.0


def test_reset_account_restores_10000_balance(client):
    resp = client.post("/engine/reset")
    assert resp.status_code == 200, f"POST /engine/reset -> {resp.status_code}: {resp.text[:300]}"

    wallet_resp = client.get("/wallet")
    assert wallet_resp.status_code == 200
    wallet = wallet_resp.json()
    assert wallet["balance"] == 10000.0, f"expected balance 10000.0 after reset, got {wallet['balance']}"
    assert wallet["equity"] == 10000.0, f"expected equity 10000.0 after reset, got {wallet['equity']}"
    assert wallet["realized_pnl"] == 0.0

    trades_resp = client.get("/trades")
    assert trades_resp.status_code == 200
    assert trades_resp.json() == [] or len(trades_resp.json()) == 0


def test_close_nonexistent_trade_returns_404(client):
    resp = client.post("/trades/does-not-exist/close")
    assert resp.status_code == 404, f"expected 404, got {resp.status_code}: {resp.text[:300]}"
