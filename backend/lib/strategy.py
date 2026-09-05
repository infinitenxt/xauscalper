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
- BTCUSD (broker variants/families supported by EA)
- XAUUSD (broker variants/families supported by EA)
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
    "confidence_threshold": 80.0,
    "min_adx": 18.0,
    "min_rr": 1.50,
    
    # Risk
    "risk_per_trade_pct": 3.0,  # aggressive but controlled
    
    # SL/TP
    "base_rr": 1.80,
    "atr_sl_mult": 1.00,
    
    # Volatility filter
    "min_atr_pct": 0.005,
    "max_atr_pct": 5.000,
    
    # Trailing
    "trail_start_r": 0.70,
    "trail_atr_mult": 0.55,
    "breakeven_at_r": 0.70,
    "profit_lock_r": 0.15,
    
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
    "trailing_enabled": True,
    "use_closed_candle": True,
    "min_volume_ratio": 0.60,
    "max_extension_atr": 2.40,
    "primary_timeframe": "5m",
    
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
    """MACD momentum + acceleration."""
    hist = _f(s, "macd_hist")
    prev = _f(s, "macd_hist_prev")
    slope = _f(s, "macd_hist_slope")

    if hist is None:
        return _vote(0, 11, "MACD", "n/a", "MACD unavailable")

    if slope is None:
        slope = (hist - prev) if prev is not None else 0.0

    if hist > 0 and slope > 0:
        bias = 1.0
        note = "bullish momentum accelerating"
    elif hist < 0 and slope < 0:
        bias = -1.0
        note = "bearish momentum accelerating"
    elif hist > 0 and slope < 0:
        bias = 0.35
        note = "bullish but momentum cooling"
    elif hist < 0 and slope > 0:
        bias = -0.35
        note = "bearish but momentum cooling"
    elif hist > 0:
        bias = 0.60
        note = "bullish momentum"
    elif hist < 0:
        bias = -0.60
        note = "bearish momentum"
    else:
        bias = 0.0
        note = "neutral"

    return _vote(
        bias, 11, "MACD",
        f"hist {hist:+.3f} / slope {slope:+.3f}",
        note,
    )


def c_rsi(
    s: Snapshot,
    mtf: Dict[str, Snapshot],
) -> Dict[str, object]:
    """Trend-aware RSI momentum.

    In a strong trend, high RSI is continuation strength rather than an
    automatic short signal. Extreme readings are treated as exhaustion only.
    """
    value = _f(s, "rsi")
    ema20 = _f(s, "ema20")
    ema50 = _f(s, "ema50")
    adx_value = _f(s, "adx") or 0.0

    if value is None:
        return _vote(0, 10, "RSI Momentum", "n/a", "RSI unavailable")

    bullish_regime = (
        ema20 is not None and ema50 is not None and ema20 > ema50 and adx_value >= 20
    )
    bearish_regime = (
        ema20 is not None and ema50 is not None and ema20 < ema50 and adx_value >= 20
    )

    if bullish_regime:
        if 55 <= value <= 75:
            bias, note = 1.0, "bullish trend momentum"
        elif value > 75:
            bias, note = 0.20, "bullish but extended momentum"
        elif value >= 45:
            bias, note = 0.35, "bullish momentum recovering"
        else:
            bias, note = -0.35, "bullish trend losing momentum"
    elif bearish_regime:
        if 25 <= value <= 45:
            bias, note = -1.0, "bearish trend momentum"
        elif value < 25:
            bias, note = -0.20, "bearish but extended momentum"
        elif value <= 55:
            bias, note = -0.35, "bearish momentum recovering"
        else:
            bias, note = 0.35, "bearish trend losing momentum"
    else:
        if value >= 70:
            bias, note = -0.45, "range overbought"
        elif value <= 30:
            bias, note = 0.45, "range oversold"
        elif value >= 55:
            bias, note = 0.70, "bullish momentum"
        elif value <= 45:
            bias, note = -0.70, "bearish momentum"
        else:
            bias, note = 0.0, "neutral"

    return _vote(
        bias, 10, "RSI Momentum",
        f"RSI {value:.1f}",
        f"RSI {value:.1f}: {note}.",
    )


def c_adx(
    s: Snapshot,
    mtf: Dict[str, Snapshot],
) -> Dict[str, object]:
    """ADX trend strength with direction and slope."""
    adx_value = _f(s, "adx")
    adx_prev = _f(s, "adx_prev")
    adx_slope = _f(s, "adx_slope")
    plus_di = _f(s, "plus_di")
    minus_di = _f(s, "minus_di")

    if adx_value is None or plus_di is None or minus_di is None:
        return _vote(0, 10, "ADX Trend Strength", "n/a", "ADX unavailable")

    if adx_slope is None and adx_prev is not None:
        adx_slope = adx_value - adx_prev

    strength = min(1.0, max(0.0, (adx_value - 15.0) / 20.0))
    if adx_value < 18:
        strength *= 0.35
    elif adx_slope is not None and adx_slope < -1.5:
        strength *= 0.75

    bias = strength if plus_di > minus_di else -strength
    slope_note = (
        "rising" if (adx_slope or 0) > 0.25
        else "falling" if (adx_slope or 0) < -0.25
        else "flat"
    )

    return _vote(
        bias, 10, "ADX Trend Strength",
        f"ADX {adx_value:.1f} / {slope_note}",
        f"ADX {adx_value:.1f}; "
        f"{'+DI buyers dominate' if plus_di > minus_di else '-DI sellers dominate'}; "
        f"trend strength {slope_note}.",
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
    """Trend-aware Bollinger position and volatility expansion."""
    percent_b = _f(s, "percent_b")
    width_change = _f(s, "bb_width_change_pct")
    ema20 = _f(s, "ema20")
    ema50 = _f(s, "ema50")
    adx_value = _f(s, "adx") or 0.0

    if percent_b is None:
        return _vote(0, 8, "Bollinger Bands", "n/a", "Bollinger unavailable")

    bullish = ema20 is not None and ema50 is not None and ema20 > ema50
    bearish = ema20 is not None and ema50 is not None and ema20 < ema50
    expanding = width_change is not None and width_change > 0

    if bullish and adx_value >= 20:
        if percent_b > 1.0:
            bias, note = (0.75 if expanding else 0.25), "bullish upper-band expansion"
        elif percent_b >= 0.55:
            bias, note = 0.85, "bullish continuation zone"
        elif percent_b < 0.0:
            bias, note = -0.45, "bull trend but price below lower band"
        else:
            bias, note = 0.15, "bullish mid-band zone"
    elif bearish and adx_value >= 20:
        if percent_b < 0.0:
            bias, note = (-0.75 if expanding else -0.25), "bearish lower-band expansion"
        elif percent_b <= 0.45:
            bias, note = -0.85, "bearish continuation zone"
        elif percent_b > 1.0:
            bias, note = 0.45, "bear trend but price above upper band"
        else:
            bias, note = -0.15, "bearish mid-band zone"
    else:
        if percent_b > 1.0:
            bias, note = -0.45, "range upper-band exhaustion"
        elif percent_b < 0.0:
            bias, note = 0.45, "range lower-band exhaustion"
        elif percent_b >= 0.60:
            bias, note = 0.45, "upper half of range"
        elif percent_b <= 0.40:
            bias, note = -0.45, "lower half of range"
        else:
            bias, note = 0.0, "range middle"

    return _vote(
        bias, 8, "Bollinger Bands",
        f"%B {percent_b:.2f}",
        f"{note}; width change {width_change:.3f}%" if width_change is not None else note,
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


def c_order_book(book: Any) -> Dict[str, object]:
    """Bounded live microstructure vote; historical/unavailable depth is neutral."""
    if not isinstance(book, dict) or book.get("stale"):
        return _vote(0, 0, "Order Book", "n/a", "live depth unavailable; no score adjustment")
    imbalance = float(book.get("imbalance") or 0.0)
    near_imbalance = float(book.get("near_imbalance") or 0.0)
    spread_bps = float(book.get("spread_bps") or 0.0)
    combined = imbalance * 0.65 + near_imbalance * 0.35
    spread_quality = max(0.25, min(1.0, 1.0 - spread_bps / 20.0))
    bias = max(-1.0, min(1.0, combined / 0.22)) * spread_quality
    return _vote(
        bias,
        8,
        "Order Book",
        f"imbalance {imbalance:+.2f}",
        f"Top-20 imbalance {imbalance:+.2f}, near-mid {near_imbalance:+.2f}, spread {spread_bps:.2f} bps.",
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
    """Return a monotonic trailing SL.

    The function never loosens an existing stop. It moves to a small profit
    after the configured R threshold and then follows price by ATR. The
    execution layer must call this repeatedly and send an MT5 position
    modification when the returned SL is better than the current SL.
    """
    cfg = cfg or {}

    if not bool(_get_cfg(cfg, "trailing_enabled", True)):
        return current_sl

    if atr <= 0 or initial_sl_dist <= 0 or entry <= 0 or current_price <= 0:
        return current_sl

    start_r = float(_get_cfg(cfg, "trail_start_r", 0.70))
    trail_atr_mult = float(_get_cfg(cfg, "trail_atr_mult", 0.55))
    profit_lock_r = float(_get_cfg(cfg, "profit_lock_r", 0.15))
    start_r = max(0.0, start_r)
    trail_atr_mult = max(0.05, trail_atr_mult)
    profit_lock_r = max(0.0, profit_lock_r)

    if direction == "BUY":
        profit = current_price - entry
        if profit <= 0:
            return current_sl

        r_multiple = profit / initial_sl_dist
        if r_multiple < start_r:
            return current_sl

        lock_sl = entry + initial_sl_dist * profit_lock_r
        trail_sl = current_price - atr * trail_atr_mult
        candidate = max(lock_sl, trail_sl)

        # Never move a BUY stop downward.
        if current_sl is not None:
            candidate = max(float(current_sl), candidate)

        return candidate

    if direction == "SELL":
        profit = entry - current_price
        if profit <= 0:
            return current_sl

        r_multiple = profit / initial_sl_dist
        if r_multiple < start_r:
            return current_sl

        lock_sl = entry - initial_sl_dist * profit_lock_r
        trail_sl = current_price + atr * trail_atr_mult
        candidate = min(lock_sl, trail_sl)

        # Never move a SELL stop upward.
        if current_sl is not None:
            candidate = min(float(current_sl), candidate)

        return candidate

    return current_sl


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
    symbol: str,
    timeframe: str,
    candles_by_tf: Dict[str, List[Dict[str, float]]],
    price: float,
    cfg: Optional[Dict[str, Any]] = None,
) -> Dict[str, object]:
    """Run the complete multi-timeframe analysis and build trade levels."""

    cfg = cfg or {}

    threshold = float(_get_cfg(cfg, "confidence_threshold", 80.0))
    min_adx = float(_get_cfg(cfg, "min_adx", 18.0))
    min_rr = float(_get_cfg(cfg, "min_rr", 1.50))
    min_atr_pct = float(_get_cfg(cfg, "min_atr_pct", 0.005))
    max_atr_pct = float(_get_cfg(cfg, "max_atr_pct", 5.000))
    max_extension_atr = float(_get_cfg(cfg, "max_extension_atr", 2.40))
    min_volume_ratio = float(_get_cfg(cfg, "min_volume_ratio", 0.60))

    primary_raw = candles_by_tf.get(timeframe, [])
    if len(primary_raw) < 60:
        return {
            "symbol": symbol,
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
            "bull_score": 0.0,
            "bear_score": 0.0,
            "structure": {},
            "pattern": {},
            "breakout": {},
            "sl": None,
            "tp": None,
            "trailing_sl": None,
            "partial_tp_price": None,
        }

    # Use closed candles for signal generation when the feed includes a live bar.
    use_closed = bool(_get_cfg(cfg, "use_closed_candle", True))
    primary = primary_raw[:-1] if use_closed and len(primary_raw) >= 61 else primary_raw
    if len(primary) < 60:
        primary = primary_raw

    snap = indicators.snapshot(primary)

    mtf_snaps: Dict[str, Snapshot] = {}
    for tf in dict.fromkeys(MTF_MAP.get(timeframe, [timeframe])):
        candles = candles_by_tf.get(tf)
        if not candles:
            continue
        if use_closed and len(candles) >= 61:
            candles = candles[:-1]
        if len(candles) >= 60:
            mtf_snaps[tf] = snap if tf == timeframe else indicators.snapshot(candles)

    order_book = cfg.get("order_book")
    confirmations = [fn(snap, mtf_snaps) for fn in CONFIRMATIONS]
    book_confirmation = c_order_book(order_book)
    confirmations.append(book_confirmation)

    bull = sum(float(c["weight"]) * max(float(c["vote"]), 0.0) for c in confirmations)
    bear = sum(float(c["weight"]) * max(-float(c["vote"]), 0.0) for c in confirmations)
    net = bull - bear

    direction = "BUY" if net > 0 else "SELL" if net < 0 else "WAIT"
    effective_weight = TOTAL_WEIGHT + float(book_confirmation.get("weight") or 0.0)
    confidence = round(min(97.0, abs(net) / effective_weight * 132.0), 1)
    if confidence < 15:
        direction = "WAIT"

    atr_value = _f(snap, "atr")
    adx_value = _f(snap, "adx")
    atr_pct = atr_value / price * 100 if atr_value and price > 0 else None
    dominant = "BULLISH" if net > 0 else "BEARISH" if net < 0 else "NEUTRAL"
    aligned = sum(1 for c in confirmations if c["direction"] == dominant)

    sl_dist: Optional[float] = None
    tp_dist: Optional[float] = None
    level_reasons: List[str] = []
    rr = 0.0

    if direction in ("BUY", "SELL"):
        sl_dist, tp_dist, level_reasons, rr = plan_levels(direction, price, snap, cfg)

    breakout = snap.get("breakout") or {}
    if not isinstance(breakout, dict):
        breakout = {}

    breakout_label = str(breakout.get("label", ""))
    chop = bool(breakout.get("chop", False))
    fake = bool(breakout.get("fake", False))
    fake_bias = float(breakout.get("bias", 0.0) or 0.0)
    fake_against = (
        (direction == "BUY" and fake_bias < 0)
        or (direction == "SELL" and fake_bias > 0)
    )

    # Higher-timeframe opposition: two or more strong opposing TFs block entry.
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

    ema21 = _f(snap, "ema21") or _f(snap, "ema20")
    stretch = abs(price - ema21) / atr_value if ema21 and atr_value else None
    breakout_quality = float(breakout.get("quality", 0.0) or 0.0)
    strong_breakout = (
        breakout_quality >= 0.70
        and bool(adx_value and adx_value >= max(min_adx, 22.0))
    )
    extended = bool(
        stretch is not None
        and stretch > max_extension_atr
        and not strong_breakout
    )

    volume = _f(snap, "volume")
    volume_avg = _f(snap, "volume_avg")
    volume_ratio = volume / volume_avg if volume and volume_avg else None
    volume_ok = volume_ratio is None or volume_ratio >= min_volume_ratio

    # Do not use a low-confidence direction as an entry merely because other
    # filters pass.
    checks: List[Dict[str, object]] = [
        {
            "name": f"Confidence ≥ {threshold:.0f}%",
            "passed": confidence >= threshold,
            "detail": f"{confidence:.1f}% confidence",
        },
        {
            "name": f"ADX ≥ {min_adx:.0f}",
            "passed": bool(adx_value is not None and adx_value >= min_adx),
            "detail": f"ADX {adx_value:.1f}" if adx_value is not None else "ADX unavailable",
        },
        {
            "name": "Volatility in tradeable band",
            "passed": bool(
                atr_pct is not None
                and min_atr_pct <= atr_pct <= max_atr_pct
            ),
            "detail": f"ATR {atr_pct:.3f}%" if atr_pct is not None else "ATR unavailable",
        },
        {
            "name": f"Reward:risk ≥ {min_rr:.2f}",
            "passed": rr >= min_rr,
            "detail": f"R:R {rr:.2f}",
        },
        {
            "name": "Direction is not WAIT",
            "passed": direction in ("BUY", "SELL"),
            "detail": direction,
        },
        {
            "name": "Market is not choppy",
            "passed": not chop,
            "detail": breakout_label,
        },
        {
            "name": "No failed breakout against us",
            "passed": not (fake and fake_against),
            "detail": breakout_label,
        },
        {
            "name": "Higher timeframes aligned",
            "passed": mtf_ok,
            "detail": "No strong opposition" if not opposed else ", ".join(opposed),
        },
        {
            "name": "Price not overextended",
            "passed": not extended,
            "detail": (
                f"{stretch:.2f} ATR from EMA21"
                if stretch is not None else "extension unavailable"
            ),
        },
        {
            "name": "Volume participation",
            "passed": volume_ok,
            "detail": (
                f"{volume_ratio:.2f}x average"
                if volume_ratio is not None else "volume unavailable"
            ),
        },
    ]

    tradeable = all(bool(check["passed"]) for check in checks)

    if direction == "WAIT":
        summary = "No trade: directional confirmations are not sufficiently aligned."
    elif tradeable:
        summary = (
            f"{direction} setup at {price:.2f} with {confidence:.1f}% confidence. "
            f"{aligned}/{len(confirmations)} confirmations aligned."
        )
    else:
        failed = [str(check["name"]) for check in checks if not check["passed"]]
        summary = (
            f"Leaning {direction} at {confidence:.1f}%, but no entry. "
            f"Failed: {', '.join(failed)}."
        )

    # Initial levels.
    sl_price = None
    tp_price = None
    trailing_sl = None
    partial_tp_price = None

    if direction in ("BUY", "SELL") and sl_dist is not None and tp_dist is not None:
        if direction == "BUY":
            sl_price = price - sl_dist
            tp_price = price + tp_dist
        else:
            sl_price = price + sl_dist
            tp_price = price - tp_dist

        partial_r = float(_get_cfg(cfg, "partial_tp_at_r", 1.50))
        if direction == "BUY":
            partial_tp_price = price + sl_dist * partial_r
        else:
            partial_tp_price = price - sl_dist * partial_r

        # This is the recommended SL for the current market price. The
        # execution layer should pass the real current_sl on every cycle.
        if bool(_get_cfg(cfg, "trailing_enabled", True)):
            trailing_sl = calculate_trailing_sl(
                direction=direction,
                entry=price,
                current_price=price,
                current_sl=sl_price,
                initial_sl_dist=sl_dist,
                atr=atr_value or 0.0,
                cfg=cfg,
            )

    last_closed = (
        primary_raw[-2]["close"]
        if len(primary_raw) >= 2
        else primary_raw[-1]["close"]
    )

    # Telegram alerting remains asynchronous and non-blocking.
    if tradeable and direction in ("BUY", "SELL"):
        user_id = cfg.get("user_id")
        if user_id and sl_dist is not None and tp_dist is not None:
            try:
                loop = asyncio.get_running_loop()
            except RuntimeError:
                loop = None

            if loop is not None:
                alert_sl = sl_price
                alert_tp = tp_price

                async def _maybe_alert(
                    uid=user_id,
                    slp=alert_sl,
                    tpp=alert_tp,
                    sym=symbol,
                    dirn=direction,
                    entry=price,
                    conf=confidence,
                    tf=timeframe,
                ):
                    try:
                        from lib.db import db
                        from lib.telegram import send_telegram_alert

                        us = await db.settings.find_one({"user_id": uid})
                        if not (us and us.get("telegram_alerts_enabled")):
                            return
                        bot_token = us.get("telegram_bot_token")
                        channel_id = us.get("telegram_channel_id")
                        if bot_token and channel_id:
                            await send_telegram_alert(
                                bot_token=bot_token,
                                channel_id=channel_id,
                                symbol=sym,
                                direction=dirn,
                                entry=entry,
                                tp=tpp,
                                sl=slp,
                                confidence=conf,
                                timeframe=tf,
                                user_id=uid,
                            )
                    except Exception as e:
                        print(f"⚠️ Telegram alert error: {e}")

                loop.create_task(_maybe_alert())

    return {
        "symbol": symbol,
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
        "atr": atr_value,
        "atr_pct": atr_pct,
        "last_closed": last_closed,
        "level_reasons": level_reasons,
        "structure": snap.get("structure") or {},
        "pattern": snap.get("pattern") or {},
        "breakout": breakout,
        "order_book": order_book if isinstance(order_book, dict) else None,
        "sl": sl_price,
        "tp": tp_price,
        "trailing_sl": trailing_sl,
        "partial_tp_price": partial_tp_price,
        "trailing_enabled": bool(_get_cfg(cfg, "trailing_enabled", True)),
    }