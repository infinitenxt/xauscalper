"""Historical replay of the live scalping rules."""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Dict, List

from lib import market_sessions, strategy
from lib.market import INTERVAL_MINUTES

WARMUP = 210
START_EQUITY = 10_000.0


def _empty(reason: str) -> Dict[str, Any]:
    return {
        "trades": 0, "wins": 0, "losses": 0, "win_rate": 0.0, "net_pnl": 0.0,
        "return_pct": 0.0, "profit_factor": 0.0, "avg_r": 0.0, "best": 0.0,
        "worst": 0.0, "max_drawdown_pct": 0.0, "avg_hold_minutes": 0.0,
        "exit_reasons": {}, "equity_curve": [], "trade_list": [], "note": reason,
        "session_breakdown": [], "best_session": "", "worst_session": "",
    }


def run(
    candles: List[Dict[str, float]],
    timeframe: str,
    cfg: Dict[str, Any],
    mtf: Dict[str, List[Dict[str, float]]] | None = None,
) -> Dict[str, Any]:
    n = len(candles)
    if n < WARMUP + 30:
        return _empty(f"need at least {WARMUP + 30} candles, got {n}")

    tf_min = INTERVAL_MINUTES.get(timeframe, 1)
    max_bars = max(1, int(float(cfg["max_hold_minutes"]) / tf_min))
    cooldown_bars = max(1, int(float(cfg["cooldown_seconds"]) / 60 / tf_min))
    risk_pct = float(cfg["risk_per_trade_pct"]) / 100
    be_at = float(cfg["breakeven_at_r"])
    partial_at = float(cfg["partial_tp_at_r"])
    fraction = float(cfg["partial_tp_fraction"])
    trail_start = float(cfg["trail_start_r"])
    trail_mult = float(cfg["trail_atr_mult"])

    equity = START_EQUITY
    peak = equity
    max_dd = 0.0
    curve: List[Dict[str, Any]] = [{"time": candles[WARMUP]["time"], "equity": round(equity, 2)}]
    trades: List[Dict[str, Any]] = []
    reasons: Dict[str, int] = {}
    gross_win = 0.0
    gross_loss = 0.0

    i = WARMUP
    while i < n - 2:
        window = candles[: i + 1]
        by_tf: Dict[str, List[Dict[str, float]]] = {timeframe: window}
        if mtf:
            cutoff = candles[i]["time"]
            for tf, series in mtf.items():
                if tf != timeframe:
                    by_tf[tf] = [c for c in series if c["time"] <= cutoff] or series
        price = window[-1]["close"]
        signal = strategy.analyze(timeframe, by_tf, price, cfg)
        if not signal.get("tradeable"):
            i += 1
            continue

        direction = str(signal["direction"])
        long = direction == "BUY"
        entry = price
        sl = float(signal["sl"])
        tp = float(signal["tp"])
        r = abs(entry - sl)
        if r <= 0:
            i += 1
            continue
        atr = float(signal.get("atr") or r)
        risk_amount = equity * risk_pct
        qty = risk_amount / r
        initial_sl = sl
        partial_pnl = 0.0
        partial_done = False
        breakeven_done = False
        trailing = False

        exit_price = None
        exit_reason = ""
        bars_held = 0
        for j in range(i + 1, min(i + 1 + max_bars, n)):
            bar = candles[j]
            bars_held = j - i
            if (long and bar["low"] <= sl) or (not long and bar["high"] >= sl):
                exit_price = sl
                exit_reason = "TRAILING STOP" if trailing else ("BREAK-EVEN STOP" if breakeven_done else "STOP LOSS")
                break
            if (long and bar["high"] >= tp) or (not long and bar["low"] <= tp):
                exit_price = tp
                exit_reason = "TAKE PROFIT"
                break
            close = bar["close"]
            favorable = (close - entry) * (1 if long else -1)
            r_mult = favorable / r
            if not partial_done and fraction > 0 and r_mult >= partial_at:
                closed_qty = qty * fraction
                partial_pnl += (close - entry) * (1 if long else -1) * closed_qty
                qty -= closed_qty
                partial_done = True
            if not breakeven_done and r_mult >= be_at:
                candidate = entry + 0.05 * r if long else entry - 0.05 * r
                if (long and candidate > sl) or (not long and candidate < sl):
                    sl = candidate
                    breakeven_done = True
            if r_mult >= trail_start:
                candidate = close - trail_mult * atr if long else close + trail_mult * atr
                floor_ = entry + 0.3 * r if long else entry - 0.3 * r
                new_sl = max(candidate, floor_) if long else min(candidate, floor_)
                if (long and new_sl > sl) or (not long and new_sl < sl):
                    sl = new_sl
                    trailing = True
        if exit_price is None:
            last = min(i + max_bars, n - 1)
            exit_price = candles[last]["close"]
            exit_reason = "TIME CAP"
            bars_held = last - i

        pnl = (exit_price - entry) * (1 if long else -1) * qty + partial_pnl
        equity += pnl
        peak = max(peak, equity)
        max_dd = max(max_dd, (peak - equity) / peak * 100 if peak else 0.0)
        if pnl >= 0:
            gross_win += pnl
        else:
            gross_loss += -pnl
        reasons[exit_reason] = reasons.get(exit_reason, 0) + 1
        trades.append(
            {
                "time": candles[i]["time"], "direction": direction, "entry": round(entry, 2),
                "exit": round(exit_price, 2), "sl": round(initial_sl, 2), "tp": round(tp, 2),
                "pnl": round(pnl, 2), "r_multiple": round(pnl / risk_amount, 2) if risk_amount else 0.0,
                "confidence": signal["confidence"], "exit_reason": exit_reason,
                "hold_minutes": bars_held * tf_min,
                "session": market_sessions.classify(
                    datetime.fromtimestamp(candles[i]["time"] / 1000, tz=timezone.utc)
                ),
            }
        )
        curve.append({"time": candles[i + bars_held]["time"], "equity": round(equity, 2)})
        i = i + bars_held + cooldown_bars

    wins = [t for t in trades if t["pnl"] >= 0]
    losses = [t for t in trades if t["pnl"] < 0]
    total = len(trades)
    if total == 0:
        out = _empty("No setup in this window cleared every gate — that is normal for a quiet stretch of bitcoin.")
        out["equity_curve"] = curve
        out["bars_tested"] = n - WARMUP
        out["timeframe"] = timeframe
        return out

    breakdown = []
    for bucket in market_sessions.BUCKETS:
        rows = [t for t in trades if t["session"] == bucket]
        if not rows:
            continue
        bucket_wins = [t for t in rows if t["pnl"] >= 0]
        bucket_gross_win = sum(t["pnl"] for t in bucket_wins)
        bucket_gross_loss = -sum(t["pnl"] for t in rows if t["pnl"] < 0)
        breakdown.append(
            {
                "session": bucket, "trades": len(rows), "wins": len(bucket_wins),
                "losses": len(rows) - len(bucket_wins),
                "win_rate": round(len(bucket_wins) / len(rows) * 100, 1),
                "net_pnl": round(sum(t["pnl"] for t in rows), 2),
                "avg_r": round(sum(t["r_multiple"] for t in rows) / len(rows), 2),
                "profit_factor": round(bucket_gross_win / bucket_gross_loss, 2) if bucket_gross_loss else round(bucket_gross_win, 2),
                "share_pct": round(len(rows) / total * 100, 1),
            }
        )
    best = max(breakdown, key=lambda row: row["net_pnl"]) if breakdown else None
    worst = min(breakdown, key=lambda row: row["net_pnl"]) if breakdown else None
    return {
        "timeframe": timeframe, "bars_tested": n - WARMUP, "trades": total,
        "wins": len(wins), "losses": len(losses), "win_rate": round(len(wins) / total * 100, 1),
        "net_pnl": round(equity - START_EQUITY, 2),
        "return_pct": round((equity - START_EQUITY) / START_EQUITY * 100, 2),
        "profit_factor": round(gross_win / gross_loss, 2) if gross_loss else round(gross_win, 2),
        "avg_r": round(sum(t["r_multiple"] for t in trades) / total, 2),
        "best": round(max(t["pnl"] for t in trades), 2), "worst": round(min(t["pnl"] for t in trades), 2),
        "max_drawdown_pct": round(max_dd, 2),
        "avg_hold_minutes": round(sum(t["hold_minutes"] for t in trades) / total, 1),
        "exit_reasons": reasons, "session_breakdown": breakdown,
        "best_session": best["session"] if best else "", "worst_session": worst["session"] if worst else "",
        "equity_curve": curve, "trade_list": trades[-40:],
        "note": "Simulation on real bitcoin candles using the live rules. Entries fill at the signal bar close and a bar covering both levels is scored as a stop. Past behaviour is not a prediction.",
    }