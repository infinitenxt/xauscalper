"""Pure-python technical indicators. No state, easy to unit test and extend."""
from __future__ import annotations

from typing import Dict, List, Optional, Sequence

Candle = Dict[str, float]


def closes(candles: Sequence[Candle]) -> List[float]:
    return [c["close"] for c in candles]


def sma(values: Sequence[float], period: int) -> Optional[float]:
    if len(values) < period or period <= 0:
        return None
    return sum(values[-period:]) / period


def ema_series(values: Sequence[float], period: int) -> List[Optional[float]]:
    out: List[Optional[float]] = [None] * len(values)
    if len(values) < period or period <= 0:
        return out
    k = 2 / (period + 1)
    prev = sum(values[:period]) / period
    out[period - 1] = prev
    for i in range(period, len(values)):
        prev = values[i] * k + prev * (1 - k)
        out[i] = prev
    return out


def ema(values: Sequence[float], period: int) -> Optional[float]:
    s = ema_series(values, period)
    return s[-1] if s else None


def rsi(values: Sequence[float], period: int = 14) -> Optional[float]:
    if len(values) < period + 1:
        return None
    gains, losses = 0.0, 0.0
    for i in range(1, period + 1):
        d = values[i] - values[i - 1]
        gains += max(d, 0.0)
        losses += max(-d, 0.0)
    avg_gain, avg_loss = gains / period, losses / period
    for i in range(period + 1, len(values)):
        d = values[i] - values[i - 1]
        avg_gain = (avg_gain * (period - 1) + max(d, 0.0)) / period
        avg_loss = (avg_loss * (period - 1) + max(-d, 0.0)) / period
    if avg_loss == 0:
        return 100.0
    rs = avg_gain / avg_loss
    return 100 - (100 / (1 + rs))


def macd(values: Sequence[float], fast: int = 12, slow: int = 26, signal: int = 9) -> Dict[str, Optional[float]]:
    fast_s, slow_s = ema_series(values, fast), ema_series(values, slow)
    line: List[float] = []
    for f, s in zip(fast_s, slow_s):
        if f is not None and s is not None:
            line.append(f - s)
    if len(line) < signal + 1:
        return {"macd": None, "signal": None, "hist": None, "hist_prev": None}
    sig_s = ema_series(line, signal)
    sig = sig_s[-1]
    sig_prev = sig_s[-2]
    hist = (line[-1] - sig) if sig is not None else None
    hist_prev = (line[-2] - sig_prev) if sig_prev is not None else None
    return {"macd": line[-1], "signal": sig, "hist": hist, "hist_prev": hist_prev}


def bollinger(values: Sequence[float], period: int = 20, mult: float = 2.0) -> Dict[str, Optional[float]]:
    if len(values) < period:
        return {"upper": None, "middle": None, "lower": None, "width_pct": None, "percent_b": None}
    window = values[-period:]
    mid = sum(window) / period
    var = sum((v - mid) ** 2 for v in window) / period
    sd = var ** 0.5
    upper, lower = mid + mult * sd, mid - mult * sd
    rng = upper - lower
    return {
        "upper": upper,
        "middle": mid,
        "lower": lower,
        "width_pct": (rng / mid * 100) if mid else None,
        "percent_b": ((values[-1] - lower) / rng) if rng else 0.5,
    }


def true_ranges(candles: Sequence[Candle]) -> List[float]:
    trs: List[float] = []
    for i in range(1, len(candles)):
        h, l, pc = candles[i]["high"], candles[i]["low"], candles[i - 1]["close"]
        trs.append(max(h - l, abs(h - pc), abs(l - pc)))
    return trs


def atr(candles: Sequence[Candle], period: int = 14) -> Optional[float]:
    trs = true_ranges(candles)
    if len(trs) < period:
        return None
    val = sum(trs[:period]) / period
    for tr in trs[period:]:
        val = (val * (period - 1) + tr) / period
    return val


def adx(candles: Sequence[Candle], period: int = 14) -> Dict[str, Optional[float]]:
    if len(candles) < period * 2 + 2:
        return {"adx": None, "plus_di": None, "minus_di": None}
    plus_dm: List[float] = []
    minus_dm: List[float] = []
    trs = true_ranges(candles)
    for i in range(1, len(candles)):
        up = candles[i]["high"] - candles[i - 1]["high"]
        down = candles[i - 1]["low"] - candles[i]["low"]
        plus_dm.append(up if (up > down and up > 0) else 0.0)
        minus_dm.append(down if (down > up and down > 0) else 0.0)

    def wilder(seq: List[float]) -> List[float]:
        out: List[float] = []
        val = sum(seq[:period])
        out.append(val)
        for i in range(period, len(seq)):
            val = val - (val / period) + seq[i]
            out.append(val)
        return out

    tr_s, p_s, m_s = wilder(trs), wilder(plus_dm), wilder(minus_dm)
    dxs: List[float] = []
    for tr_v, p_v, m_v in zip(tr_s, p_s, m_s):
        if tr_v == 0:
            continue
        pdi, mdi = 100 * p_v / tr_v, 100 * m_v / tr_v
        denom = pdi + mdi
        if denom:
            dxs.append(100 * abs(pdi - mdi) / denom)
    if len(dxs) < period:
        return {"adx": None, "plus_di": None, "minus_di": None}
    adx_val = sum(dxs[:period]) / period
    for dx in dxs[period:]:
        adx_val = (adx_val * (period - 1) + dx) / period
    tr_last = tr_s[-1] or 1.0
    return {
        "adx": adx_val,
        "plus_di": 100 * p_s[-1] / tr_last,
        "minus_di": 100 * m_s[-1] / tr_last,
    }


def vwap(candles: Sequence[Candle], period: int = 60) -> Optional[float]:
    window = candles[-period:]
    tot_v = sum(c["volume"] for c in window)
    if tot_v <= 0:
        return None
    return sum(((c["high"] + c["low"] + c["close"]) / 3) * c["volume"] for c in window) / tot_v


def swing_points(candles: Sequence[Candle], left: int = 2, right: int = 2) -> Dict[str, List[Dict[str, float]]]:
    highs: List[Dict[str, float]] = []
    lows: List[Dict[str, float]] = []
    for i in range(left, len(candles) - right):
        window = candles[i - left : i + right + 1]
        c = candles[i]
        if c["high"] == max(w["high"] for w in window):
            highs.append({"index": float(i), "price": c["high"]})
        if c["low"] == min(w["low"] for w in window):
            lows.append({"index": float(i), "price": c["low"]})
    return {"highs": highs, "lows": lows}


def support_resistance(candles: Sequence[Candle], lookback: int = 120) -> Dict[str, List[float]]:
    """Cluster recent swing points into support / resistance levels."""
    window = list(candles[-lookback:])
    if len(window) < 20:
        return {"support": [], "resistance": []}
    sw = swing_points(window)
    price = window[-1]["close"]
    tol = max(price * 0.0008, 0.01)

    def cluster(points: List[Dict[str, float]]) -> List[float]:
        levels: List[List[float]] = []
        for p in sorted(pt["price"] for pt in points):
            if levels and abs(p - levels[-1][-1]) <= tol * 2:
                levels[-1].append(p)
            else:
                levels.append([p])
        return [sum(g) / len(g) for g in levels]

    res = [lv for lv in cluster(sw["highs"]) if lv > price]
    sup = [lv for lv in cluster(sw["lows"]) if lv < price]
    res.sort()
    sup.sort(reverse=True)
    return {"support": sup[:4], "resistance": res[:4]}


def market_structure(candles: Sequence[Candle]) -> Dict[str, object]:
    """Higher-high/higher-low vs lower-high/lower-low structure read."""
    sw = swing_points(list(candles[-120:]))
    highs = [p["price"] for p in sw["highs"]][-3:]
    lows = [p["price"] for p in sw["lows"]][-3:]
    if len(highs) < 2 or len(lows) < 2:
        return {"label": "UNCLEAR", "bias": 0.0, "detail": "not enough swing points to read structure"}
    hh = highs[-1] > highs[-2]
    hl = lows[-1] > lows[-2]
    lh = highs[-1] < highs[-2]
    ll = lows[-1] < lows[-2]
    if hh and hl:
        return {"label": "UPTREND", "bias": 1.0, "detail": "higher highs and higher lows"}
    if lh and ll:
        return {"label": "DOWNTREND", "bias": -1.0, "detail": "lower highs and lower lows"}
    if hh and ll:
        return {"label": "EXPANSION", "bias": 0.0, "detail": "broadening range, both extremes extending"}
    if hl and lh:
        return {"label": "COMPRESSION", "bias": 0.0, "detail": "contracting range, coiling before expansion"}
    return {"label": "RANGE", "bias": 0.3 if hl else -0.3, "detail": "mixed swings, no clean trend"}


def candle_pattern(candles: Sequence[Candle]) -> Dict[str, object]:
    """Last-candle price action read."""
    if len(candles) < 3:
        return {"label": "NONE", "bias": 0.0, "detail": "insufficient candles"}
    c, p = candles[-1], candles[-2]
    body = abs(c["close"] - c["open"])
    rng = max(c["high"] - c["low"], 1e-9)
    upper = c["high"] - max(c["close"], c["open"])
    lower = min(c["close"], c["open"]) - c["low"]
    bull = c["close"] > c["open"]
    p_body = abs(p["close"] - p["open"])

    if body > p_body and (
        (bull and c["close"] > p["open"] and c["open"] < p["close"] and p["close"] < p["open"])
        or (not bull and c["close"] < p["open"] and c["open"] > p["close"] and p["close"] > p["open"])
    ):
        return {
            "label": "BULLISH ENGULFING" if bull else "BEARISH ENGULFING",
            "bias": 1.0 if bull else -1.0,
            "detail": "last candle fully engulfs the prior opposite candle",
        }
    if lower > body * 2 and upper < body:
        return {"label": "HAMMER / LONG LOWER WICK", "bias": 0.7, "detail": "sellers rejected at the lows"}
    if upper > body * 2 and lower < body:
        return {"label": "SHOOTING STAR / LONG UPPER WICK", "bias": -0.7, "detail": "buyers rejected at the highs"}
    if body / rng > 0.7:
        return {
            "label": "STRONG BULL MARUBOZU" if bull else "STRONG BEAR MARUBOZU",
            "bias": 0.8 if bull else -0.8,
            "detail": "wide-range candle closing near its extreme",
        }
    if body / rng < 0.15:
        return {"label": "DOJI / INDECISION", "bias": 0.0, "detail": "tiny body, buyers and sellers balanced"}
    return {
        "label": "MINOR BULL CANDLE" if bull else "MINOR BEAR CANDLE",
        "bias": 0.25 if bull else -0.25,
        "detail": "ordinary candle, no strong price-action signal",
    }


def snapshot(candles: Sequence[Candle]) -> Dict[str, object]:
    """Everything the strategy needs for one timeframe."""
    cl = closes(candles)
    vols = [c["volume"] for c in candles]
    m = macd(cl)
    bb = bollinger(cl)
    dmi = adx(candles)
    return {
        "price": cl[-1] if cl else None,
        "ema9": ema(cl, 9),
        "ema20": ema(cl, 20),
        "ema50": ema(cl, 50),
        "ema200": ema(cl, 200),
        "rsi": rsi(cl),
        "macd": m["macd"],
        "macd_signal": m["signal"],
        "macd_hist": m["hist"],
        "macd_hist_prev": m["hist_prev"],
        "bb_upper": bb["upper"],
        "bb_middle": bb["middle"],
        "bb_lower": bb["lower"],
        "bb_width_pct": bb["width_pct"],
        "percent_b": bb["percent_b"],
        "atr": atr(candles),
        "adx": dmi["adx"],
        "plus_di": dmi["plus_di"],
        "minus_di": dmi["minus_di"],
        "vwap": vwap(candles),
        "volume": vols[-1] if vols else None,
        "volume_avg": sma(vols, 20),
        "levels": support_resistance(candles),
        "structure": market_structure(candles),
        "pattern": candle_pattern(candles),
    }
