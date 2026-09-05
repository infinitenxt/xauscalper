"""Order-book data improves signals without becoming a hard gate.

Criterion: fresh bullish/bearish books add one weight-8 "Order Book"
confirmation and adjust confidence directionally; stale/missing books add a
zero-weight neutral confirmation and do not change candle-only scoring.

Exercised directly against lib.strategy.c_order_book / lib.strategy.analyze
(the real scoring functions the engine and /dashboard both call) -- there is
no dedicated public endpoint that returns raw confirmation weights, so this
is a direct-import unit check on the scoring module itself, same pattern as
the EA/backtest static+direct checks in this suite.
"""

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from lib import strategy  # noqa: E402


def _candles(n: int = 260, start: float = 60000.0, step: float = 5.0):
    out = []
    price = start
    t = 1_700_000_000
    for i in range(n):
        price += step
        o = price - step
        h = price + 2
        low = price - step - 2
        c = price
        out.append({"time": t, "open": o, "high": h, "low": low, "close": c, "volume": 10.0})
        t += 60
    return out


def test_missing_or_stale_book_is_zero_weight_neutral():
    missing = strategy.c_order_book(None)
    assert missing["weight"] == 0
    assert missing["direction"] == "NEUTRAL"

    stale = strategy.c_order_book({"stale": True, "imbalance": 0.9, "near_imbalance": 0.9, "spread_bps": 1.0})
    assert stale["weight"] == 0
    assert stale["direction"] == "NEUTRAL"


def test_fresh_bullish_book_is_weight_eight_and_bullish():
    bullish = strategy.c_order_book(
        {"stale": False, "imbalance": 0.5, "near_imbalance": 0.5, "spread_bps": 1.0}
    )
    assert bullish["weight"] == 8
    assert bullish["direction"] == "BULLISH"
    assert bullish["vote"] > 0


def test_fresh_bearish_book_is_weight_eight_and_bearish():
    bearish = strategy.c_order_book(
        {"stale": False, "imbalance": -0.5, "near_imbalance": -0.5, "spread_bps": 1.0}
    )
    assert bearish["weight"] == 8
    assert bearish["direction"] == "BEARISH"
    assert bearish["vote"] < 0


def test_candle_only_scoring_unaffected_when_book_absent_and_confidence_shifts_when_present():
    candles = _candles()
    by_tf = {"1m": candles}
    base_cfg = {"use_closed_candle": False}

    baseline = strategy.analyze(
        symbol="BTCUSDT", timeframe="1m", candles_by_tf=by_tf, price=candles[-1]["close"], cfg=dict(base_cfg)
    )
    # No order_book key at all (candle-only / historical replay path).
    assert baseline["tradeable"] in (True, False)

    no_book_cfg = {**base_cfg, "order_book": None}
    no_book = strategy.analyze(
        symbol="BTCUSDT", timeframe="1m", candles_by_tf=by_tf, price=candles[-1]["close"], cfg=no_book_cfg
    )
    # Absent vs explicit-None order_book must score identically (candle-only path untouched).
    assert no_book["confidence"] == baseline["confidence"]
    assert no_book["direction"] == baseline["direction"]

    bullish_book_cfg = {
        **base_cfg,
        "order_book": {"stale": False, "imbalance": 0.9, "near_imbalance": 0.9, "spread_bps": 1.0},
    }
    with_book = strategy.analyze(
        symbol="BTCUSDT", timeframe="1m", candles_by_tf=by_tf, price=candles[-1]["close"], cfg=bullish_book_cfg
    )
    # A fresh, strongly one-sided book must be able to shift confidence relative to the
    # candle-only baseline (it is a confirmation weight, not a no-op).
    assert with_book["confidence"] != baseline["confidence"] or with_book["direction"] != baseline["direction"]
