"""Legacy EA (v4.3-style) market-data sync must not be blocked.

A token-authenticated market-data payload that omits broker_day and uses
unquoted MQL datetime tokens for tick_time/open_time (instead of JSON
numbers) is repaired server-side, accepted, stores broker candles/tick, and
flips broker_data_source from "syncing" to "broker" once 60 primary-timeframe
bars exist.
"""
import subprocess

from .helpers import DB_NAME, cleanup_user, make_subscribed_user


def _account_field(account_id: str, field: str) -> str:
    script = "db.mt5_accounts.findOne({id: '%s'}, {%s: 1, _id: 0})" % (account_id, field)
    out = subprocess.run(
        ["mongosh", DB_NAME, "--quiet", "--eval", script],
        capture_output=True, text=True, timeout=20,
    )
    return out.stdout


def _legacy_payload(bars_text: str, tick_dt: str) -> str:
    # Raw text body: broker_day omitted entirely (v4.3 had no such field), and
    # tick_time uses an unquoted MQL "YYYY.MM.DD HH:MM:SS" token instead of a
    # JSON epoch int -- this is what makes json.loads() fail on the fast path
    # and forces the legacy-datetime repair regex in routers/mt5.py.
    return (
        '{"symbol":"BTCUSD","bid":60000.5,"ask":60001.0,'
        '"tick_time":%s,"point":0.01,"digits":2,"trade_stops_level":0,'
        '"contract_size":1.0,"spread_points":5,"bars":[%s]}'
    ) % (tick_dt, bars_text)


def test_legacy_v43_market_data_accepted_and_becomes_broker_source(client, backend_url):
    api_url = f"{backend_url}/api"
    user_client, user_id, admin = make_subscribed_user(
        api_url, "legacymd", days=3, live_plan_id="mt5-live-monthly"
    )
    try:
        connect = user_client.post(
            "/mt5/account",
            json={"mode": "demo", "account_login": "700100", "broker_server": "Tscheck-Legacy", "lot_size": 0.01},
        )
        assert connect.status_code == 200, connect.text[:300]
        token = connect.json()["bridge_token"]
        account_id = connect.json()["account"]["id"]
        headers = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}

        # First batch: fewer than 60 bars -> accepted, but source stays "syncing".
        first_bars = ",".join(
            (
                '{"timeframe":"5m","open_time":%s.01.01 00:%02d:00,"duration_seconds":300,'
                '"open":60000,"high":60010,"low":59990,"close":60005,"tick_volume":12,"spread_points":5}'
            ) % ("2024", i)
            for i in range(30)
        )
        body1 = _legacy_payload(first_bars, "2024.01.01 00:30:05")
        r1 = user_client.post("/mt5/bridge/market-data", content=body1, headers=headers)
        assert r1.status_code == 200, f"legacy payload rejected: {r1.status_code} {r1.text[:400]}"
        j1 = r1.json()
        assert j1["accepted_bars"] == 30, j1
        assert j1["source"] == "syncing", j1
        assert j1["broker_data_ready"] is False, j1

        raw_after_first = _account_field(account_id, "broker_data_source")
        assert "syncing" in raw_after_first, raw_after_first

        # Second batch: 30 more distinct bars -> 60 total -> source flips to "broker".
        second_bars = ",".join(
            (
                '{"timeframe":"5m","open_time":%s.01.01 01:%02d:00,"duration_seconds":300,'
                '"open":60000,"high":60010,"low":59990,"close":60005,"tick_volume":12,"spread_points":5}'
            ) % ("2024", i)
            for i in range(30)
        )
        body2 = _legacy_payload(second_bars, "2024.01.01 01:30:05")
        r2 = user_client.post("/mt5/bridge/market-data", content=body2, headers=headers)
        assert r2.status_code == 200, f"second legacy payload rejected: {r2.status_code} {r2.text[:400]}"
        j2 = r2.json()
        assert j2["accepted_bars"] == 30, j2
        assert j2["source"] == "broker", j2
        assert j2["broker_data_ready"] is True, j2

        raw_after_second = _account_field(account_id, "broker_data_source")
        assert "broker" in raw_after_second and "syncing" not in raw_after_second, raw_after_second

        candle_count_script = "db.broker_candles.countDocuments({account_id: '%s', timeframe: '5m'})" % account_id
        out = subprocess.run(
            ["mongosh", DB_NAME, "--quiet", "--eval", candle_count_script],
            capture_output=True, text=True, timeout=20,
        )
        assert "60" in out.stdout, f"expected 60 stored broker candles, got: {out.stdout}"

        tick_count_script = "db.broker_ticks.countDocuments({account_id: '%s'})" % account_id
        out2 = subprocess.run(
            ["mongosh", DB_NAME, "--quiet", "--eval", tick_count_script],
            capture_output=True, text=True, timeout=20,
        )
        assert "2" in out2.stdout, f"expected 2 stored broker ticks, got: {out2.stdout}"
    finally:
        cleanup_user(admin, user_id)


def test_market_data_rejects_broker_ask_below_bid(client, backend_url):
    api_url = f"{backend_url}/api"
    user_client, user_id, admin = make_subscribed_user(
        api_url, "legacymdbad", days=3, live_plan_id="mt5-live-monthly"
    )
    try:
        connect = user_client.post(
            "/mt5/account",
            json={"mode": "demo", "account_login": "700200", "broker_server": "Tscheck-Legacy2", "lot_size": 0.01},
        )
        assert connect.status_code == 200, connect.text[:300]
        token = connect.json()["bridge_token"]
        headers = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}

        bad_body = '{"symbol":"BTCUSD","bid":60001.0,"ask":60000.5,"tick_time":2024.01.01 00:00:05,' \
                    '"point":0.01,"digits":2,"trade_stops_level":0,"contract_size":1.0,"spread_points":5,"bars":[]}'
        resp = user_client.post("/mt5/bridge/market-data", content=bad_body, headers=headers)
        assert resp.status_code == 400, f"expected 400 for ask<bid, got {resp.status_code} {resp.text[:300]}"
    finally:
        cleanup_user(admin, user_id)
