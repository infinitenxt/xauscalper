"""Trading strategy engine - Dynamic + Optimized

Dynamic Configuration:
- All values come from user settings (cfg parameter)
- Fallback values are optimized for small accounts
- User can override any setting via /api/settings

Best Performing Indicators (Proven):
1. EMA Trend - 14 weight
2. MTF Trend - 14 weight  
3. MACD - 11 weight
4. RSI - 10 weight
5. ADX - 10 weight
6. Market Structure - 11 weight
7. Support/Resistance - 10 weight
8. VWAP - 8 weight
9. Bollinger Bands - 8 weight
10. Volume - 6 weight
11. Price Action - 8 weight
12. Breakout Quality - 10 weight

Multi-Symbol Support:
- BTCUSDT
- XAUUSD
"""

from __future__ import annotations

import asyncio
from typing import Any, Callable, Dict, List, Optional, Tuple

from lib import indicators
from lib.market import INTERVAL_MINUTES


# =====================================================================
# FALLBACK CONFIGURATION (Sirf tab use hogi jab user ne set nahi kiya)
# =====================================================================

FALLBACK_CONFIG = {
    # Entry thresholds
    "confidence_threshold": 70.0,
    "min_adx": 18.0,
    "min_rr": 1.50,
    
    # Risk
    "risk_per_trade_pct": 8.0,  # 8%
    
    # SL/TP
    "base_rr": 1.80,
    "atr_sl_mult": 1.00,
    
    # Volatility filter
    "min_atr_pct": 0.005,
    "max_atr_pct": 5.000,
    
    # Trailing
    "trail_start_r": 0.80,
    "trail_atr_mult": 0.60,
    "breakeven_at_r": 0.80,
    "profit_lock_r": 0.10,
    
    # Cooldown
    "cooldown_seconds": 45,
    "max_hold_minutes": 20,
    "daily_loss_limit_pct": 20.0,
    "max_trades_per_hour": 8,
    "consecutive_loss_pause": 4,
    "pause_minutes_after_losses": 15,
    "stale_entry_max_pct": 35,
    "auto_trade_enabled": True,
    "session_filter_enabled": False,
    "primary_timeframe": "1m",
    
    # Partial TP
    "partial_tp_at_r": 1.50,
    "partial_tp_fraction": 0.40,
}


# =====================================================================
# MULTI TIMEFRAME MAP
# =====================================================================

MTF_MAP = {
    "1m": ["1m", "5m", "15m", "30m", "1h"],
    "5m": ["5m", "15m", "30m", "1h"],
    "15m": ["15m", "1h"],
    "30m": ["30m", "1h"],
    "1h": ["1h"],
}


Snapshot = Dict[str, object]


# =====================================================================
# HELPERS
# =====================================================================

def _f(snap: Snapshot, key: str) -> Optional[float]:
    value = snap.get(key)
    if isinstance(value, (int, float)):
        return float(value)
    return None


def _get_cfg(cfg: Optional[Dict[str, Any]], key: str, default: Any) -> Any:
    """User settings se value lo, agar nahi hai toh fallback use karo"""
    if cfg and key in cfg:
        return cfg[key]
    return default


def _vote(
    bias: float,
    weight: float,
    name: str,
    state: str,
    detail: str,
) -> Dict[str, object]:
    bias = max(-1.0, min(1.0, bias))
    return {
        "name": name,
        "weight": weight,
        "vote": round(bias, 3),
        "direction": (
            "BULLISH" if bias > 0.15 else
            "BEARISH" if bias < -0.15 else
            "NEUTRAL"
        ),
        "state": state,
        "detail": detail,
    }


# =====================================================================
# CONFIRMATIONS (12 Best Indicators)
# =====================================================================

def c_ema_trend(
    s: Snapshot,
    mtf: Dict[str, Snapshot],
) -> Dict[str, object]:
    """EMA Trend"""
    price = _f(s, "price")
    ema20 = _f(s, "ema20")
    ema50 = _f(s, "ema50")
    ema200 = _f(s, "ema200")

    if None in (price, ema20, ema50):
        return _vote(0, 14, "EMA Trend", "n/a", "not enough history")

    bias = 0.0
    bias += 0.5 if ema20 > ema50 else -0.5
    bias += 0.3 if price > ema20 else -0.3
    if ema200 is not None:
        bias += 0.2 if price > ema200 else -0.2

    return _vote(
        bias, 14, "EMA Trend",
        f"EMA20 {ema20:.2f} / EMA50 {ema50:.2f}",
        f"Price is {'above' if price > ema20 else 'below'} EMA20, "
        f"EMA20 is {'above' if ema20 > ema50 else 'below'} EMA50."
    )


def c_mtf_trend(
    s: Snapshot,
    mtf: Dict[str, Snapshot],
) -> Dict[str, object]:
    """Multi-Timeframe Trend"""
    votes: List[float] = []
    parts: List[str] = []

    for tf, snap in mtf.items():
        ema20 = _f(snap, "ema20")
        ema50 = _f(snap, "ema50")
        if ema20 is None or ema50 is None:
            continue
        up = ema20 > ema50
        votes.append(1.0 if up else -1.0)
        parts.append(f"{tf} {'UP' if up else 'DOWN'}")

    if not votes:
        return _vote(0, 14, "Multi-Timeframe Trend", "n/a", "higher timeframes unavailable")

    bias = sum(votes) / len(votes)
    agree = abs(bias) == 1.0

    return _vote(
        bias, 14, "Multi-Timeframe Trend",
        " · ".join(parts),
        "All timeframes agree." if agree else "Timeframes are partially conflicting."
    )


def c_macd(
    s: Snapshot,
    mtf: Dict[str, Snapshot],
) -> Dict[str, object]:
    """MACD"""
    hist = _f(s, "macd_hist")
    prev = _f(s, "macd_hist_prev")

    if hist is None:
        return _vote(0, 11, "MACD", "n/a", "MACD unavailable")

    rising = prev is not None and hist > prev
    falling = prev is not None and hist < prev

    if hist > 0 and rising:
        bias = 1.0
    elif hist < 0 and falling:
        bias = -1.0
    elif hist > 0:
        bias = 0.6
    elif hist < 0:
        bias = -0.6
    else:
        bias = 0.0

    return _vote(
        bias, 11, "MACD",
        f"hist {hist:+.3f}",
        f"MACD histogram is {'positive' if hist > 0 else 'negative'}."
    )


def c_rsi(
    s: Snapshot,
    mtf: Dict[str, Snapshot],
) -> Dict[str, object]:
    """RSI Momentum"""
    rsi = _f(s, "rsi")

    if rsi is None:
        return _vote(0, 10, "RSI Momentum", "n/a", "RSI unavailable")

    if rsi >= 70:
        bias = -0.4
        note = "overbought"
    elif rsi >= 55:
        bias = 0.9
        note = "bullish momentum"
    elif rsi > 45:
        bias = 0.0
        note = "neutral"
    elif rsi > 30:
        bias = -0.9
        note = "bearish momentum"
    else:
        bias = 0.4
        note = "oversold"

    return _vote(
        bias, 10, "RSI Momentum",
        f"RSI {rsi:.1f}",
        f"RSI {rsi:.1f}: {note}."
    )


def c_adx(
    s: Snapshot,
    mtf: Dict[str, Snapshot],
) -> Dict[str, object]:
    """ADX Trend Strength"""
    adx = _f(s, "adx")
    plus_di = _f(s, "plus_di")
    minus_di = _f(s, "minus_di")

    if adx is None or plus_di is None or minus_di is None:
        return _vote(0, 10, "ADX Trend Strength", "n/a", "ADX unavailable")

    strength = min(1.0, max(0.0, (adx - 15.0) / 20.0))
    bias = strength if plus_di > minus_di else -strength

    return _vote(
        bias, 10, "ADX Trend Strength",
        f"ADX {adx:.1f}",
        f"ADX {adx:.1f}; {'+DI buyers dominate' if plus_di > minus_di else '-DI sellers dominate'}."
    )


def c_structure(
    s: Snapshot,
    mtf: Dict[str, Snapshot],
) -> Dict[str, object]:
    """Market Structure"""
    structure = s.get("structure") or {}
    if not isinstance(structure, dict):
        return _vote(0, 11, "Market Structure", "UNCLEAR", "structure unavailable")

    bias = float(structure.get("bias", 0.0))
    label = str(structure.get("label", "UNCLEAR"))
    detail = str(structure.get("detail", ""))

    return _vote(bias, 11, "Market Structure", label, f"{label} — {detail}.")


def c_levels(
    s: Snapshot,
    mtf: Dict[str, Snapshot],
) -> Dict[str, object]:
    """Support / Resistance"""
    price = _f(s, "price")
    atr = _f(s, "atr")
    levels = s.get("levels") or {}

    if not isinstance(levels, dict):
        levels = {}

    support = [float(x) for x in levels.get("support", []) if isinstance(x, (int, float))]
    resistance = [float(x) for x in levels.get("resistance", []) if isinstance(x, (int, float))]

    if price is None or atr is None or atr <= 0:
        return _vote(0, 10, "Support / Resistance", "n/a", "levels unavailable")

    nearest_support = max([x for x in support if x < price], default=None)
    nearest_resistance = min([x for x in resistance if x > price], default=None)

    bias = 0.0

    if nearest_resistance is not None:
        distance = (nearest_resistance - price) / atr
        if distance < 0.6:
            bias -= 0.8

    if nearest_support is not None:
        distance = (price - nearest_support) / atr
        if distance < 0.6:
            bias += 0.8

    if bias == 0.0 and nearest_support is not None and nearest_resistance is not None:
        support_distance = price - nearest_support
        resistance_distance = nearest_resistance - price
        bias = 0.4 if resistance_distance > support_distance else -0.4

    return _vote(
        bias, 10, "Support / Resistance",
        (f"S {nearest_support:.2f}" if nearest_support is not None else "S —") +
        " / " +
        (f"R {nearest_resistance:.2f}" if nearest_resistance is not None else "R —"),
        "Nearby liquidity levels evaluated."
    )


def c_vwap(
    s: Snapshot,
    mtf: Dict[str, Snapshot],
) -> Dict[str, object]:
    """VWAP Bias"""
    price = _f(s, "price")
    vwap = _f(s, "vwap")

    if price is None or vwap is None:
        return _vote(0, 8, "VWAP Bias", "n/a", "VWAP unavailable")

    distance = (price - vwap) / vwap * 100
    bias = max(-1.0, min(1.0, distance / 0.25))

    return _vote(
        bias, 8, "VWAP Bias",
        f"{distance:+.2f}%",
        f"Price is {abs(distance):.2f}% {'above' if distance > 0 else 'below'} VWAP."
    )


def c_bollinger(
    s: Snapshot,
    mtf: Dict[str, Snapshot],
) -> Dict[str, object]:
    """Bollinger Bands"""
    percent_b = _f(s, "percent_b")

    if percent_b is None:
        return _vote(0, 8, "Bollinger Bands", "n/a", "Bollinger unavailable")

    if percent_b > 1.0:
        bias = -0.5
    elif percent_b > 0.6:
        bias = 0.8
    elif percent_b < 0.0:
        bias = 0.5
    elif percent_b < 0.4:
        bias = -0.8
    else:
        bias = 0.0

    return _vote(
        bias, 8, "Bollinger Bands",
        f"%B {percent_b:.2f}",
        f"Bollinger position {percent_b:.2f}."
    )


def c_volume(
    s: Snapshot,
    mtf: Dict[str, Snapshot],
) -> Dict[str, object]:
    """Volume Confirmation"""
    volume = _f(s, "volume")
    average = _f(s, "volume_avg")
    pattern = s.get("pattern") or {}

    if not isinstance(pattern, dict):
        pattern = {}

    pattern_bias = float(pattern.get("bias", 0.0))

    if volume is None or not average:
        return _vote(0, 6, "Volume Confirmation", "n/a", "volume unavailable")

    ratio = volume / average
    conviction = min(1.0, max(0.0, (ratio - 0.8) / 0.7))

    bias = conviction * (1.0 if pattern_bias > 0 else (-1.0 if pattern_bias < 0 else 0.0))

    return _vote(
        bias, 6, "Volume Confirmation",
        f"{ratio:.2f}x",
        f"Volume is {ratio:.2f}x the 20-bar average."
    )


def c_price_action(
    s: Snapshot,
    mtf: Dict[str, Snapshot],
) -> Dict[str, object]:
    """Price Action"""
    pattern = s.get("pattern") or {}

    if not isinstance(pattern, dict):
        pattern = {}

    bias = float(pattern.get("bias", 0.0))
    label = str(pattern.get("label", "NONE"))
    detail = str(pattern.get("detail", ""))

    return _vote(
        bias, 8, "Price Action",
        label,
        f"{label} — {detail}."
    )


def c_breakout(
    s: Snapshot,
    mtf: Dict[str, Snapshot],
) -> Dict[str, object]:
    """Breakout Quality"""
    breakout = s.get("breakout") or {}

    if not isinstance(breakout, dict):
        return _vote(0, 10, "Breakout Quality", "n/a", "breakout unavailable")

    label = str(breakout.get("label", ""))

    if label == "NO DATA":
        return _vote(0, 10, "Breakout Quality", "n/a", "not enough candles")

    bias = float(breakout.get("bias", 0.0))
    detail = str(breakout.get("detail", ""))

    return _vote(
        bias, 10, "Breakout Quality",
        label,
        detail,
    )


# =====================================================================
# CONFIRMATION LIST
# =====================================================================

CONFIRMATIONS: List[
    Callable[
        [Snapshot, Dict[str, Snapshot]],
        Dict[str, object],
    ]
] = [
    c_ema_trend,
    c_mtf_trend,
    c_macd,
    c_rsi,
    c_adx,
    c_structure,
    c_levels,
    c_vwap,
    c_bollinger,
    c_volume,
    c_price_action,
    c_breakout,
]


# =====================================================================
# TOTAL WEIGHT
# =====================================================================

TOTAL_WEIGHT = sum(
    float(
        {
            "c_ema_trend": 14,
            "c_mtf_trend": 14,
            "c_macd": 11,
            "c_rsi": 10,
            "c_adx": 10,
            "c_structure": 11,
            "c_levels": 10,
            "c_vwap": 8,
            "c_bollinger": 8,
            "c_volume": 6,
            "c_price_action": 8,
            "c_breakout": 10,
        }.get(fn.__name__, 0)
    )
    for fn in CONFIRMATIONS
)


# =====================================================================
# SL/TP PLANNING (User settings se dynamic)
# =====================================================================

def plan_levels(
    direction: str,
    entry: float,
    snap: Snapshot,
    cfg: Optional[Dict[str, float]] = None,
) -> Tuple[
    Optional[float],
    Optional[float],
    List[str],
    float,
]:

    cfg = cfg or {}

    atr_sl_mult = _get_cfg(cfg, "atr_sl_mult", 1.00)
    base_rr = _get_cfg(cfg, "base_rr", 1.80)
    min_rr = _get_cfg(cfg, "min_rr", 1.50)

    atr = _f(snap, "atr")

    if atr is None or atr <= 0:
        return (None, None, ["ATR unavailable"], 0.0)

    levels = snap.get("levels") or {}
    if not isinstance(levels, dict):
        levels = {}

    support = [float(x) for x in levels.get("support", []) if isinstance(x, (int, float))]
    resistance = [float(x) for x in levels.get("resistance", []) if isinstance(x, (int, float))]

    reasons: List[str] = []

    # ATR stop
    volatility_stop = atr * atr_sl_mult
    minimum_stop = atr * 0.8
    sl_dist = max(volatility_stop, minimum_stop)

    # Structure adjustment
    if direction == "BUY":
        supports = [x for x in support if x < entry]
        if supports:
            nearest_support = max(supports)
            structure_distance = entry - (nearest_support - 0.15 * atr)
            sl_dist = max(sl_dist, min(structure_distance, 1.8 * atr))

    elif direction == "SELL":
        resistances = [x for x in resistance if x > entry]
        if resistances:
            nearest_resistance = min(resistances)
            structure_distance = (nearest_resistance + 0.15 * atr) - entry
            sl_dist = max(sl_dist, min(structure_distance, 1.8 * atr))

    else:
        return (None, None, ["Invalid direction"], 0.0)

    # Dynamic RR
    adx = _f(snap, "adx") or 20.0
    rr = base_rr + min(0.6, max(0.0, (adx - 20.0) / 50.0))
    rr = max(rr, min_rr)
    tp_dist = sl_dist * rr

    # Resistance/Support TP cap
    if direction == "BUY":
        blockers = sorted([x for x in resistance if x > entry])
        if blockers:
            first = blockers[0]
            candidate = first - 0.10 * atr
            minimum_tp = sl_dist * min_rr
            if candidate > entry + minimum_tp:
                tp_dist = candidate - entry

    else:
        blockers = sorted([x for x in support if x < entry], reverse=True)
        if blockers:
            first = blockers[0]
            candidate = first + 0.10 * atr
            minimum_tp = sl_dist * min_rr
            if candidate < entry - minimum_tp:
                tp_dist = entry - candidate

    final_rr = tp_dist / sl_dist if sl_dist > 0 else 0.0

    reasons.append(f"Initial SL distance {sl_dist:.2f} ({sl_dist / atr:.2f} ATR).")
    reasons.append(f"Initial TP distance {tp_dist:.2f} with R:R {final_rr:.2f}.")

    return (abs(sl_dist), abs(tp_dist), reasons, final_rr)


# =====================================================================
# TRAILING STOP (User settings se dynamic)
# =====================================================================

def calculate_trailing_sl(
    direction: str,
    entry: float,
    current_price: float,
    current_sl: Optional[float],
    initial_sl_dist: float,
    atr: float,
    cfg: Optional[Dict[str, float]] = None,
) -> Optional[float]:

    if not True:  # TRAILING_ENABLED
        return current_sl

    if atr <= 0 or initial_sl_dist <= 0:
        return current_sl

    cfg = cfg or {}

    start_r = _get_cfg(cfg, "trail_start_r", 0.80)
    trail_atr_mult = _get_cfg(cfg, "trail_atr_mult", 0.60)
    profit_lock_r = _get_cfg(cfg, "profit_lock_r", 0.10)

    if direction == "BUY":
        profit = current_price - entry
        if profit <= 0:
            return current_sl

        r_multiple = profit / initial_sl_dist
        if r_multiple < start_r:
            return current_sl

        breakeven_sl = entry + initial_sl_dist * profit_lock_r
        trail_distance = atr * trail_atr_mult
        trailing_sl = current_price - trail_distance
        new_sl = max(breakeven_sl, trailing_sl)

        if current_sl is not None:
            new_sl = max(current_sl, new_sl)

        return new_sl

    if direction == "SELL":
        profit = entry - current_price
        if profit <= 0:
            return current_sl

        r_multiple = profit / initial_sl_dist
        if r_multiple < start_r:
            return current_sl

        breakeven_sl = entry - initial_sl_dist * profit_lock_r
        trail_distance = atr * trail_atr_mult
        trailing_sl = current_price + trail_distance
        new_sl = min(breakeven_sl, trailing_sl)

        if current_sl is not None:
            new_sl = min(current_sl, new_sl)

        return new_sl

    return current_sl


# =====================================================================
# TIMEOUT
# =====================================================================

def timeout_seconds(
    timeframe: str,
    max_hold_minutes: Optional[float] = None,
) -> int:
    if max_hold_minutes:
        return int(max_hold_minutes * 60)
    return INTERVAL_MINUTES.get(timeframe, 15) * 60 * 10


# =====================================================================
# FULL ANALYSIS (Multi-Symbol)
# =====================================================================

def analyze(
    symbol: str,  # ✅ NEW: symbol parameter
    timeframe: str,
    candles_by_tf: Dict[str, List[Dict[str, float]]],
    price: float,
    cfg: Optional[Dict[str, Any]] = None,
) -> Dict[str, object]:

    cfg = cfg or {}

    threshold = _get_cfg(cfg, "confidence_threshold", 70.0)
    min_adx = _get_cfg(cfg, "min_adx", 18.0)
    min_rr = _get_cfg(cfg, "min_rr", 1.50)
    min_atr_pct = _get_cfg(cfg, "min_atr_pct", 0.005)
    max_atr_pct = _get_cfg(cfg, "max_atr_pct", 5.000)

    primary = candles_by_tf.get(timeframe, [])

    if len(primary) < 60:
        return {
            "symbol": symbol,  # ✅ Added
            "timeframe": timeframe,
            "direction": "WAIT",
            "confidence": 0.0,
            "price": price,
            "confirmations": [],
            "risk_checks": [{"name": "Data", "passed": False, "detail": "not enough candles yet"}],
            "tradeable": False,
            "summary": "Waiting for enough market history.",
            "sl_dist": None,
            "tp_dist": None,
            "rr": 0.0,
            "level_reasons": [],
            "atr": None,
            "last_closed": None,
        }

    snap = indicators.snapshot(primary)

    mtf_snaps: Dict[str, Snapshot] = {}
    for tf in dict.fromkeys(MTF_MAP.get(timeframe, [timeframe])):
        candles = candles_by_tf.get(tf)
        if candles and len(candles) >= 60:
            mtf_snaps[tf] = snap if tf == timeframe else indicators.snapshot(candles)

    confirmations = [fn(snap, mtf_snaps) for fn in CONFIRMATIONS]

    bull = sum(float(c["weight"]) * max(float(c["vote"]), 0.0) for c in confirmations)
    bear = sum(float(c["weight"]) * max(-float(c["vote"]), 0.0) for c in confirmations)

    net = bull - bear

    direction = "BUY" if net > 0 else "SELL" if net < 0 else "WAIT"
    confidence = round(min(97.0, abs(net) / TOTAL_WEIGHT * 132.0), 1)

    if confidence < 15:
        direction = "WAIT"

    atr = _f(snap, "atr")
    adx = _f(snap, "adx")
    atr_pct = atr / price * 100 if atr and price else None
    aligned = sum(1 for c in confirmations if c["direction"] == ("BULLISH" if net > 0 else "BEARISH"))

    # SL/TP
    sl_dist = None
    tp_dist = None
    level_reasons: List[str] = []
    rr = 0.0

    if direction in ("BUY", "SELL"):
        sl_dist, tp_dist, level_reasons, rr = plan_levels(direction, price, snap, cfg)

    # Filters
    breakout = snap.get("breakout") or {}
    if not isinstance(breakout, dict):
        breakout = {}
    breakout_label = str(breakout.get("label", ""))
    chop = bool(breakout.get("chop", False))
    fake = bool(breakout.get("fake", False))
    fake_bias = float(breakout.get("bias", 0.0) or 0.0)
    fake_against = (direction == "BUY" and fake_bias < 0) or (direction == "SELL" and fake_bias > 0)

    # MTF opposition
    higher = [tf for tf in ("15m", "30m", "1h") if tf in mtf_snaps and tf != timeframe]
    opposed: List[str] = []
    for tf in higher:
        higher_snap = mtf_snaps[tf]
        fast = _f(higher_snap, "ema21") or _f(higher_snap, "ema20")
        slow = _f(higher_snap, "ema50")
        tf_adx = _f(higher_snap, "adx") or 0.0
        if fast is None or slow is None:
            continue
        up = fast > slow
        if tf_adx >= 20:
            if (direction == "BUY" and not up) or (direction == "SELL" and up):
                opposed.append(f"{tf} ADX {tf_adx:.0f}")

    mtf_ok = direction not in ("BUY", "SELL") or len(opposed) < 2

    # Extension
    ema21 = _f(snap, "ema21") or _f(snap, "ema20")
    stretch = abs(price - ema21) / atr if ema21 and atr else None
    extended = bool(stretch is not None and stretch > 2.2)

    # Volume
    volume = _f(snap, "volume")
    volume_avg = _f(snap, "volume_avg")
    volume_ratio = volume / volume_avg if volume and volume_avg else None
    volume_ok = volume_ratio is None or volume_ratio >= 0.6

    # Risk Checks (Dynamic)
    checks: List[Dict[str, object]] = [
        {"name": f"Confidence ≥ {threshold:.0f}%", "passed": confidence >= threshold, "detail": f"{confidence:.1f}% confidence"},
        {"name": f"ADX ≥ {min_adx:.0f}", "passed": bool(adx and adx >= min_adx), "detail": f"ADX {adx:.1f}" if adx else "ADX unavailable"},
        {"name": "Volatility in tradeable band", "passed": bool(atr_pct and min_atr_pct <= atr_pct <= max_atr_pct), "detail": f"ATR {atr_pct:.3f}%" if atr_pct else "ATR unavailable"},
        {"name": f"Reward:risk ≥ {min_rr}", "passed": rr >= min_rr, "detail": f"R:R {rr:.2f}"},
        {"name": "Direction is not WAIT", "passed": direction in ("BUY", "SELL"), "detail": direction},
        {"name": "Market is not choppy", "passed": not chop, "detail": breakout_label},
        {"name": "No failed breakout against us", "passed": not (fake and fake_against), "detail": breakout_label},
        {"name": "Higher timeframes aligned", "passed": mtf_ok, "detail": "No strong opposition" if not opposed else ", ".join(opposed)},
        {"name": "Price not overextended", "passed": not extended, "detail": f"{stretch:.2f} ATR from EMA21" if stretch is not None else "extension unavailable"},
        {"name": "Volume participation", "passed": volume_ok, "detail": f"{volume_ratio:.2f}x average" if volume_ratio is not None else "volume unavailable"},
    ]

    tradeable = all(bool(check["passed"]) for check in checks)

    # Summary
    if direction == "WAIT":
        summary = "No trade: directional confirmations are not sufficiently aligned."
    elif tradeable:
        summary = f"{direction} setup at {price:.2f} with {confidence:.1f}% confidence. {aligned}/{len(confirmations)} confirmations aligned."
    else:
        failed = [str(check["name"]) for check in checks if not check["passed"]]
        summary = f"Leaning {direction} at {confidence:.1f}%, but no entry. Failed: {', '.join(failed)}."

    last_closed = primary[-2]["close"] if len(primary) >= 2 else primary[-1]["close"]

    # =============================================================
    # ✅ TELEGRAM ALERT TRIGGER (with symbol)
    # =============================================================
    if tradeable and direction in ("BUY", "SELL"):
        user_id = cfg.get("user_id") if cfg else None
        if user_id:
            try:
                from lib.db import db
                from lib.telegram import send_telegram_alert
                
                # ✅ Get user settings (sync, no await)
                user_settings = db.settings.find_one({"user_id": user_id})
                
                if user_settings and user_settings.get("telegram_alerts_enabled"):
                    bot_token = user_settings.get("telegram_bot_token")
                    channel_id = user_settings.get("telegram_channel_id")
                    
                    if bot_token and channel_id and sl_dist is not None and tp_dist is not None:
                        # Calculate SL and TP prices
                        if direction == "BUY":
                            sl_price = price - sl_dist
                            tp_price = price + tp_dist
                        else:
                            sl_price = price + sl_dist
                            tp_price = price - tp_dist
                        
                        # ✅ Send alert with symbol
                        asyncio.create_task(
                            send_telegram_alert(
                                bot_token=bot_token,
                                channel_id=channel_id,
                                symbol=symbol,  # ✅ PASS SYMBOL
                                direction=direction,
                                entry=price,
                                tp=tp_price,
                                sl=sl_price,
                                confidence=confidence,
                                timeframe=timeframe
                            )
                        )
                        print(f"📤 Telegram alert sent for {symbol} {direction} signal at {price:.2f}")
            except Exception as e:
                print(f"⚠️ Telegram alert error: {e}")
    # =============================================================

    return {
        "symbol": symbol,  # ✅ Added
        "timeframe": timeframe,
        "direction": direction,
        "confidence": confidence,
        "price": price,
        "bull_score": round(bull, 1),
        "bear_score": round(bear, 1),
        "confirmations": confirmations,
        "risk_checks": checks,
        "tradeable": tradeable,
        "summary": summary,
        "sl_dist": sl_dist,
        "tp_dist": tp_dist,
        "rr": round(rr, 2),
        "atr": atr,
        "last_closed": last_closed,
        "level_reasons": level_reasons,
    }