"""Signal engine: multi-confirmation confluence scoring for gold.

Design: each *confirmation* is an independent, weighted directional vote in
[-1, +1]. Weights sum to 100 so the net score is already a percentage. Direction
comes from the sign of the net vote, confidence from its magnitude. Risk filters
are separate hard gates — a high confidence score alone never opens a trade.

Adding a new confirmation = append one function to CONFIRMATIONS and give it a
weight. Nothing else changes.
"""
from __future__ import annotations

from typing import Any, Callable, Dict, List, Optional, Tuple

from lib import indicators
from lib.market import INTERVAL_MINUTES

# ---------------------------------------------------------------- tuning knobs
CONFIDENCE_THRESHOLD = 80.0
MIN_ADX = 20.0
MIN_RR = 1.3
RISK_PER_TRADE = 0.01
BASE_RR = 1.4
ATR_SL_MULT = 0.9
MIN_ATR_PCT = 0.010
MAX_ATR_PCT = 1.600
TRADE_COOLDOWN_SEC = 60

MTF_MAP = {
    "1m": ["1m", "5m", "15m", "30m", "1h"],
    "5m": ["5m", "15m", "30m", "1h"],
    "15m": ["15m", "1h"],
    "30m": ["30m", "1h"],
    "1h": ["1h"],
}

Snapshot = Dict[str, object]


def _f(snap: Snapshot, key: str) -> Optional[float]:
    v = snap.get(key)
    return float(v) if isinstance(v, (int, float)) else None


def _vote(
    bias: float,
    weight: float,
    name: str,
    state: str,
    detail: str,
) -> Dict[str, object]:
    return {
        "name": name,
        "weight": weight,
        "vote": round(max(-1.0, min(1.0, bias)), 3),
        "direction": (
            "BULLISH"
            if bias > 0.15
            else ("BEARISH" if bias < -0.15 else "NEUTRAL")
        ),
        "state": state,
        "detail": detail,
    }


# ------------------------------------------------------------- confirmations
def c_ema_trend(s: Snapshot, mtf: Dict[str, Snapshot]) -> Dict[str, object]:
    p, e20, e50 = _f(s, "price"), _f(s, "ema20"), _f(s, "ema50")
    e200 = _f(s, "ema200")

    if None in (p, e20, e50):
        return _vote(
            0,
            14,
            "EMA Trend",
            "n/a",
            "not enough history for EMA 20/50",
        )

    bias = 0.0
    bias += 0.5 if e20 > e50 else -0.5  # type: ignore[operator]
    bias += 0.3 if p > e20 else -0.3  # type: ignore[operator]

    if e200 is not None:
        bias += 0.2 if p > e200 else -0.2  # type: ignore[operator]

    state = f"EMA20 {e20:.2f} / EMA50 {e50:.2f}"

    detail = (
        f"Price {p:.2f} is {'above' if p > e20 else 'below'} EMA20 and EMA20 is "
        f"{'above' if e20 > e50 else 'below'} EMA50 — net EMA read is "
        f"{'bullish' if bias > 0 else 'bearish'}."
    )

    return _vote(bias, 14, "EMA Trend", state, detail)


def c_mtf_trend(s: Snapshot, mtf: Dict[str, Snapshot]) -> Dict[str, object]:
    votes: List[float] = []
    parts: List[str] = []

    for tf, snap in mtf.items():
        e20, e50 = _f(snap, "ema20"), _f(snap, "ema50")

        if e20 is None or e50 is None:
            continue

        up = e20 > e50
        votes.append(1.0 if up else -1.0)
        parts.append(f"{tf} {'UP' if up else 'DOWN'}")

    if not votes:
        return _vote(
            0,
            14,
            "Multi-Timeframe Trend",
            "n/a",
            "higher timeframes unavailable",
        )

    bias = sum(votes) / len(votes)
    agree = abs(bias) == 1.0

    return _vote(
        bias,
        14,
        "Multi-Timeframe Trend",
        " · ".join(parts),
        (
            ("All timeframes agree" if agree else "Timeframes disagree")
            + f" ({' , '.join(parts)}) — higher-timeframe context "
            f"{'supports' if agree else 'dilutes'} the setup."
        ),
    )


def c_macd(s: Snapshot, mtf: Dict[str, Snapshot]) -> Dict[str, object]:
    hist, prev = _f(s, "macd_hist"), _f(s, "macd_hist_prev")

    if hist is None:
        return _vote(
            0,
            11,
            "MACD",
            "n/a",
            "MACD needs more candles",
        )

    bias = 0.6 if hist > 0 else -0.6
    rising = prev is not None and hist > prev

    if hist > 0 and rising:
        bias = 1.0
    elif hist < 0 and prev is not None and hist < prev:
        bias = -1.0

    return _vote(
        bias,
        11,
        "MACD",
        f"hist {hist:+.3f}",
        f"MACD histogram is {'positive' if hist > 0 else 'negative'} and "
        f"{'expanding' if (rising and hist > 0) or (not rising and hist < 0) else 'contracting'} — "
        f"momentum {'favours buyers' if hist > 0 else 'favours sellers'}.",
    )


def c_rsi(s: Snapshot, mtf: Dict[str, Snapshot]) -> Dict[str, object]:
    r = _f(s, "rsi")

    if r is None:
        return _vote(
            0,
            10,
            "RSI Momentum",
            "n/a",
            "RSI needs more candles",
        )

    if r >= 70:
        bias, note = -0.4, "overbought — chasing longs here is poor risk"
    elif r >= 55:
        bias, note = 0.9, "healthy bullish momentum without being overbought"
    elif r > 45:
        bias, note = 0.0, "neutral momentum, no edge"
    elif r > 30:
        bias, note = -0.9, "bearish momentum with room to fall"
    else:
        bias, note = 0.4, "oversold — shorting here is poor risk"

    return _vote(
        bias,
        10,
        "RSI Momentum",
        f"RSI {r:.1f}",
        f"RSI at {r:.1f}: {note}.",
    )


def c_adx(s: Snapshot, mtf: Dict[str, Snapshot]) -> Dict[str, object]:
    a, pdi, mdi = _f(s, "adx"), _f(s, "plus_di"), _f(s, "minus_di")

    if a is None or pdi is None or mdi is None:
        return _vote(
            0,
            10,
            "ADX Trend Strength",
            "n/a",
            "ADX needs more candles",
        )

    strength = min(1.0, max(0.0, (a - 15) / 20))
    bias = strength * (1.0 if pdi > mdi else -1.0)

    return _vote(
        bias,
        10,
        "ADX Trend Strength",
        f"ADX {a:.1f} · +DI {pdi:.1f} / -DI {mdi:.1f}",
        f"ADX {a:.1f} means "
        f"{'a trending' if a >= MIN_ADX else 'a weak/ranging'} market, and "
        f"{'+DI dominates (buyers)' if pdi > mdi else '-DI dominates (sellers)'}.",
    )


def c_structure(s: Snapshot, mtf: Dict[str, Snapshot]) -> Dict[str, object]:
    st = s.get("structure") or {}

    bias = float(st.get("bias", 0.0)) if isinstance(st, dict) else 0.0
    label = str(st.get("label", "UNCLEAR")) if isinstance(st, dict) else "UNCLEAR"
    detail = str(st.get("detail", "")) if isinstance(st, dict) else ""

    return _vote(
        bias,
        11,
        "Market Structure",
        label,
        f"Swing structure reads {label} — {detail}.",
    )


def c_vwap(s: Snapshot, mtf: Dict[str, Snapshot]) -> Dict[str, object]:
    p, v = _f(s, "price"), _f(s, "vwap")

    if p is None or v is None:
        return _vote(
            0,
            8,
            "VWAP Bias",
            "n/a",
            "VWAP unavailable (no volume data)",
        )

    dist_pct = (p - v) / v * 100
    bias = max(-1.0, min(1.0, dist_pct / 0.25))

    return _vote(
        bias,
        8,
        "VWAP Bias",
        f"{dist_pct:+.2f}% vs VWAP {v:.2f}",
        f"Price is {abs(dist_pct):.2f}% "
        f"{'above' if dist_pct > 0 else 'below'} rolling VWAP — "
        f"volume-weighted control is with "
        f"{'buyers' if dist_pct > 0 else 'sellers'}.",
    )


def c_bollinger(s: Snapshot, mtf: Dict[str, Snapshot]) -> Dict[str, object]:
    pb, width = _f(s, "percent_b"), _f(s, "bb_width_pct")

    if pb is None:
        return _vote(
            0,
            8,
            "Bollinger Bands",
            "n/a",
            "Bollinger needs more candles",
        )

    if pb > 1.0:
        bias, note = -0.5, "closed outside the upper band — stretched, mean reversion risk"
    elif pb > 0.6:
        bias, note = 0.8, "riding the upper half, buyers in control"
    elif pb < 0.0:
        bias, note = 0.5, "closed outside the lower band — stretched, bounce risk for shorts"
    elif pb < 0.4:
        bias, note = -0.8, "pinned to the lower half, sellers in control"
    else:
        bias, note = 0.0, "sitting mid-band, no directional edge"

    state = f"%B {pb:.2f}" + (
        f" · width {width:.2f}%" if width is not None else ""
    )

    return _vote(
        bias,
        8,
        "Bollinger Bands",
        state,
        f"Bollinger {note}.",
    )


def c_volume(s: Snapshot, mtf: Dict[str, Snapshot]) -> Dict[str, object]:
    v, avg = _f(s, "volume"), _f(s, "volume_avg")
    pat = s.get("pattern") or {}

    pat_bias = (
        float(pat.get("bias", 0.0))
        if isinstance(pat, dict)
        else 0.0
    )

    if v is None or not avg:
        return _vote(
            0,
            6,
            "Volume Confirmation",
            "n/a",
            "volume data unavailable",
        )

    ratio = v / avg
    conviction = min(1.0, max(0.0, (ratio - 0.8) / 0.7))
    bias = conviction * (
        1.0 if pat_bias > 0 else (-1.0 if pat_bias < 0 else 0.0)
    )

    return _vote(
        bias,
        6,
        "Volume Confirmation",
        f"{ratio:.2f}x 20-bar average",
        f"Current bar traded {ratio:.2f}x its 20-bar average volume — "
        f"{'participation confirms the move' if ratio >= 1.0 else 'thin participation, weak conviction'}.",
    )


def c_price_action(s: Snapshot, mtf: Dict[str, Snapshot]) -> Dict[str, object]:
    pat = s.get("pattern") or {}

    bias = float(pat.get("bias", 0.0)) if isinstance(pat, dict) else 0.0
    label = str(pat.get("label", "NONE")) if isinstance(pat, dict) else "NONE"
    detail = str(pat.get("detail", "")) if isinstance(pat, dict) else ""

    return _vote(
        bias,
        8,
        "Price Action",
        label,
        f"Last candle: {label} — {detail}.",
    )


def c_levels(s: Snapshot, mtf: Dict[str, Snapshot]) -> Dict[str, object]:
    p, a = _f(s, "price"), _f(s, "atr")
    levels = s.get("levels") or {}

    sup = (
        list(levels.get("support", []))[:1]
        if isinstance(levels, dict)
        else []
    )
    res = (
        list(levels.get("resistance", []))[:1]
        if isinstance(levels, dict)
        else []
    )

    if p is None or a is None or not a:
        return _vote(
            0,
            10,
            "Support / Resistance",
            "n/a",
            "levels unavailable",
        )

    d_sup = (p - sup[0]) / a if sup else None
    d_res = (res[0] - p) / a if res else None

    bias = 0.0
    notes: List[str] = []

    if d_res is not None and d_res < 0.6:
        bias -= 0.8
        notes.append(
            f"resistance {res[0]:.2f} only {d_res:.2f} ATR overhead (caps upside)"
        )

    if d_sup is not None and d_sup < 0.6:
        bias += 0.8
        notes.append(
            f"support {sup[0]:.2f} only {d_sup:.2f} ATR below (cushions downside)"
        )

    if not notes:
        if d_res is not None and d_sup is not None:
            bias = 0.4 if d_res > d_sup else -0.4

        notes.append(
            f"clear runway: {d_sup:.2f} ATR to support, {d_res:.2f} ATR to resistance"
            if d_sup is not None and d_res is not None
            else "no nearby level pressure"
        )

    state = (
        f"S {sup[0]:.2f}" if sup else "S —"
    ) + " / " + (
        f"R {res[0]:.2f}" if res else "R —"
    )

    return _vote(
        bias,
        10,
        "Support / Resistance",
        state,
        "; ".join(notes).capitalize() + ".",
    )


def c_breakout(s: Snapshot, mtf: Dict[str, Snapshot]) -> Dict[str, object]:
    """Breakout quality / fake-breakout / chop read of the recent range."""

    brk = s.get("breakout") or {}

    if not isinstance(brk, dict) or brk.get("label") == "NO DATA":
        return _vote(
            0,
            10,
            "Breakout Quality",
            "n/a",
            "not enough candles for a breakout read",
        )

    bias = float(brk.get("bias", 0.0))
    label = str(brk.get("label", ""))

    return _vote(
        bias,
        10,
        "Breakout Quality",
        label,
        str(brk.get("detail", "")).capitalize() + ".",
    )


CONFIRMATIONS: List[
    Callable[[Snapshot, Dict[str, Snapshot]], Dict[str, object]]
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

TOTAL_WEIGHT = 120.0


# --------------------------------------------------------------- SL/TP design
def plan_levels(
    direction: str,
    entry: float,
    snap: Snapshot,
    cfg: Optional[Dict[str, float]] = None,
) -> Tuple[Optional[float], Optional[float], List[str], float]:
    """Volatility + structure aware SL/TP.

    Returns:
        (sl_dist, tp_dist, reasons, rr)

    sl_dist and tp_dist are PRICE DISTANCES, not absolute prices.
    The MT5 bridge converts these distances into actual SL/TP using
    the live broker price at execution time.
    """

    cfg = cfg or {}

    sl_mult = float(cfg.get("atr_sl_mult", ATR_SL_MULT))
    base_rr = float(cfg.get("base_rr", BASE_RR))
    min_rr = float(cfg.get("min_rr", MIN_RR))

    a = _f(snap, "atr")

    if a is None or a <= 0:
        return (
            None,
            None,
            ["ATR unavailable — cannot size risk safely"],
            0.0,
        )

    levels = snap.get("levels") or {}

    sup = (
        list(levels.get("support", []))
        if isinstance(levels, dict)
        else []
    )
    res = (
        list(levels.get("resistance", []))
        if isinstance(levels, dict)
        else []
    )

    adx_val = _f(snap, "adx") or 20.0
    reasons: List[str] = []

    # --------------------------------------------------------- stop distance
    vol_stop = sl_mult * a
    max_stop = max(vol_stop, 2.0 * a)

    if direction == "BUY":
        struct_stop = (
            entry - (sup[0] - 0.2 * a)
            if sup
            else vol_stop
        )

        sl_dist = max(
            vol_stop,
            min(struct_stop, max_stop),
        )

        # Internal absolute price used only for planning/reason calculation.
        sl = entry - sl_dist

        reasons.append(
            f"Stop placed {sl_dist:.2f} below entry = "
            f"max({sl_mult}x ATR {a:.2f}"
            + (
                f", 0.2 ATR under support {sup[0]:.2f}"
                if sup
                else ""
            )
            + ") — tight enough for a scalp, wide enough that ordinary "
            "noise cannot hit it."
        )

    else:
        struct_stop = (
            (res[0] + 0.2 * a) - entry
            if res
            else vol_stop
        )

        sl_dist = max(
            vol_stop,
            min(struct_stop, max_stop),
        )

        # Internal absolute price used only for planning/reason calculation.
        sl = entry + sl_dist

        reasons.append(
            f"Stop placed {sl_dist:.2f} above entry = "
            f"max({sl_mult}x ATR {a:.2f}"
            + (
                f", 0.2 ATR over resistance {res[0]:.2f}"
                if res
                else ""
            )
            + ") — tight enough for a scalp, wide enough that ordinary "
            "noise cannot hit it."
        )

    # --------------------------------------------------------------- RR
    rr = base_rr + min(
        0.5,
        max(0.0, (adx_val - 20) / 50),
    )

    reasons.append(
        f"Target reward:risk set to {rr:.2f} because ADX is {adx_val:.1f} "
        f"({'strong push, give it a little more room' if adx_val >= 25 else 'moderate push, take the quick win'})."
    )

    # ---------------------------------------------------------- target price
    if direction == "BUY":
        tp = entry + sl_dist * rr

        blockers = [lv for lv in res if lv > entry]

        if blockers and blockers[0] < tp:
            capped = blockers[0] - 0.15 * a

            if capped > entry + sl_dist * min_rr:
                tp = capped

                reasons.append(
                    f"Target pulled back to {tp:.2f}, just under resistance "
                    f"{blockers[0]:.2f}, so we bank profit before the level "
                    "rejects price."
                )

    else:
        tp = entry - sl_dist * rr

        blockers = [lv for lv in sup if lv < entry]

        if blockers and blockers[0] > tp:
            capped = blockers[0] + 0.15 * a

            if capped < entry - sl_dist * min_rr:
                tp = capped

                reasons.append(
                    f"Target pulled up to {tp:.2f}, just above support "
                    f"{blockers[0]:.2f}, so we bank profit before the level "
                    "bounces price."
                )

    # ----------------------------------------------------------- final RR
    final_rr = abs(tp - entry) / sl_dist if sl_dist else 0.0

    struct = (
        snap.get("structure")
        if isinstance(snap.get("structure"), dict)
        else {}
    )

    brk = (
        snap.get("breakout")
        if isinstance(snap.get("breakout"), dict)
        else {}
    )

    e21 = _f(snap, "ema21") or _f(snap, "ema20")
    vw = _f(snap, "vwap")

    if direction == "BUY":
        reasons.append(
            "Setup is invalidated if price closes back below "
            + (f"EMA21 {e21:.2f}" if e21 else "the fast EMA")
            + (f" or loses VWAP {vw:.2f}" if vw else "")
            + f", or if structure flips from "
            f"{struct.get('label', 'its current read')} "
            "to lower highs and lower lows."
        )

    else:
        reasons.append(
            "Setup is invalidated if price closes back above "
            + (f"EMA21 {e21:.2f}" if e21 else "the fast EMA")
            + (f" or reclaims VWAP {vw:.2f}" if vw else "")
            + f", or if structure flips from "
            f"{struct.get('label', 'its current read')} "
            "to higher highs and higher lows."
        )

    reasons.append(
        f"Main risk: gold can move {a:.2f} (1 ATR) either way on news or "
        f"a liquidity grab; the current range read is "
        f"{brk.get('label', 'unclassified')}, so a sudden reversal would "
        "hit the stop before the target. Risk is capped at the configured "
        "% of balance — paper trading only, no signal is a guarantee."
    )

    # ------------------------------------------------------- DISTANCE OUTPUT
    #
    # IMPORTANT:
    # Do NOT return absolute SL/TP prices.
    # Return only distances from the planned entry.
    #
    # MT5 EA will calculate:
    #
    # BUY:
    #   SL = live_price - sl_dist
    #   TP = live_price + tp_dist
    #
    # SELL:
    #   SL = live_price + sl_dist
    #   TP = live_price - tp_dist
    #
    tp_dist = abs(tp - entry)
    sl_dist = abs(sl - entry)

    return sl_dist, tp_dist, reasons, final_rr


# ------------------------------------------------------------------- analysis
def analyze(
    timeframe: str,
    candles_by_tf: Dict[str, List[Dict[str, float]]],
    price: float,
    cfg: Optional[Dict[str, Any]] = None,
) -> Dict[str, object]:
    """Run the full confluence engine for one primary timeframe."""

    cfg = cfg or {}

    threshold = float(
        cfg.get("confidence_threshold", CONFIDENCE_THRESHOLD)
    )
    min_adx = float(
        cfg.get("min_adx", MIN_ADX)
    )
    min_rr = float(
        cfg.get("min_rr", MIN_RR)
    )
    min_atr_pct = float(
        cfg.get("min_atr_pct", MIN_ATR_PCT)
    )
    max_atr_pct = float(
        cfg.get("max_atr_pct", MAX_ATR_PCT)
    )

    primary = candles_by_tf.get(timeframe, [])

    if len(primary) < 60:
        return {
            "timeframe": timeframe,
            "direction": "WAIT",
            "confidence": 0.0,
            "price": price,
            "confirmations": [],
            "risk_checks": [
                {
                    "name": "Data",
                    "passed": False,
                    "detail": "not enough candles yet",
                }
            ],
            "tradeable": False,
            "summary": "Waiting for enough market history to evaluate.",
            "sl_dist": None,
            "tp_dist": None,
            "rr": 0.0,
            "level_reasons": [],
            "atr": None,
            "last_closed": None,
        }

    snap = indicators.snapshot(primary)

    mtf_snaps: Dict[str, Snapshot] = {}

    for tf in dict.fromkeys(
        MTF_MAP.get(timeframe, [timeframe])
    ):
        cs = candles_by_tf.get(tf)

        if cs and len(cs) >= 60:
            mtf_snaps[tf] = (
                snap
                if tf == timeframe
                else indicators.snapshot(cs)
            )

    confirmations = [
        fn(snap, mtf_snaps)
        for fn in CONFIRMATIONS
    ]

    bull = sum(
        float(c["weight"]) * max(float(c["vote"]), 0.0)
        for c in confirmations
    )

    bear = sum(
        float(c["weight"]) * max(-float(c["vote"]), 0.0)
        for c in confirmations
    )

    net = bull - bear

    direction = (
        "BUY"
        if net > 0
        else ("SELL" if net < 0 else "WAIT")
    )

    confidence = round(
        min(
            97.0,
            abs(net) / TOTAL_WEIGHT * 132.0,
        ),
        1,
    )

    if confidence < 15:
        direction = "WAIT"

    a = _f(snap, "atr")
    adx_val = _f(snap, "adx")

    atr_pct = (
        (a / price * 100)
        if a and price
        else None
    )

    aligned = sum(
        1
        for c in confirmations
        if c["direction"]
        == (
            "BULLISH"
            if net > 0
            else "BEARISH"
        )
    )

    # ----------------------------------------------------------- SL/TP
    sl_dist, tp_dist, level_reasons, rr = (
        None,
        None,
        [],
        0.0,
    )

    if direction in ("BUY", "SELL"):
        sl_dist, tp_dist, level_reasons, rr = plan_levels(
            direction,
            price,
            snap,
            cfg,
        )

    last_closed = (
        primary[-2]["close"]
        if len(primary) >= 2
        else primary[-1]["close"]
    )

    # ---- extra scalping gates
    brk = (
        snap.get("breakout")
        if isinstance(snap.get("breakout"), dict)
        else {}
    )

    brk_label = (
        str(brk.get("label", ""))
        if isinstance(brk, dict)
        else ""
    )

    chop = (
        bool(brk.get("chop"))
        if isinstance(brk, dict)
        else False
    )

    fake = (
        bool(brk.get("fake"))
        if isinstance(brk, dict)
        else False
    )

    efficiency = (
        float(brk.get("efficiency") or 0.0)
        if isinstance(brk, dict)
        else 0.0
    )

    fake_bias = (
        float(brk.get("bias") or 0.0)
        if isinstance(brk, dict)
        else 0.0
    )

    fake_against = (
        (direction == "BUY" and fake_bias < 0)
        or (direction == "SELL" and fake_bias > 0)
    )

    # higher timeframes must not strongly contradict entry timeframe
    higher = [
        tf
        for tf in ("15m", "30m", "1h")
        if tf in mtf_snaps and tf != timeframe
    ]

    opposed: List[str] = []

    for tf in higher:
        sn = mtf_snaps[tf]

        e_fast = (
            _f(sn, "ema21")
            or _f(sn, "ema20")
        )

        e_slow = _f(sn, "ema50")
        adx_tf = _f(sn, "adx") or 0.0

        if e_fast is None or e_slow is None:
            continue

        tf_up = e_fast > e_slow
        strong = adx_tf >= 20

        if strong and (
            (direction == "BUY" and not tf_up)
            or (direction == "SELL" and tf_up)
        ):
            opposed.append(
                f"{tf} (ADX {adx_tf:.0f})"
            )

    mtf_ok = (
        direction not in ("BUY", "SELL")
        or len(opposed) < 2
    )

    mtf_detail = (
        f"{len(opposed)} higher timeframe(s) strongly opposed: "
        f"{', '.join(opposed)}"
        if opposed
        else
        f"{len(higher)} higher timeframe(s) checked, "
        "none strongly opposed"
    )

    # over-extension
    e21 = _f(snap, "ema21") or _f(snap, "ema20")

    stretch = (
        abs(price - e21) / a
        if (e21 and a)
        else None
    )

    extended = bool(
        stretch is not None
        and stretch > 2.2
    )

    extension_detail = (
        f"price is {stretch:.2f} ATR from EMA21 (cap 2.20 ATR)"
        if stretch is not None
        else "EMA21 distance unavailable"
    )

    vol_now = _f(snap, "volume")
    vol_avg = _f(snap, "volume_avg")

    vol_ratio = (
        (vol_now / vol_avg)
        if (vol_now and vol_avg)
        else None
    )

    vol_ok = (
        vol_ratio is None
        or vol_ratio >= 0.6
    )

    vol_detail = (
        f"current bar traded {vol_ratio:.2f}x its 20-bar average "
        "(need ≥ 0.60x)"
        if vol_ratio is not None
        else "volume data unavailable"
    )

    checks: List[Dict[str, object]] = [
        {
            "name": f"Confidence ≥ {threshold:.0f}%",
            "passed": confidence >= threshold,
            "detail": (
                f"confluence score {confidence:.1f}% "
                f"({aligned}/{len(confirmations)} confirmations aligned)"
            ),
        },
        {
            "name": f"Trend strength ADX ≥ {min_adx:.0f}",
            "passed": bool(
                adx_val
                and adx_val >= min_adx
            ),
            "detail": (
                f"ADX {adx_val:.1f}"
                if adx_val
                else "ADX unavailable"
            ),
        },
        {
            "name": "Volatility in tradeable band",
            "passed": bool(
                atr_pct
                and min_atr_pct <= atr_pct <= max_atr_pct
            ),
            "detail": (
                f"ATR is {atr_pct:.3f}% of price "
                f"(band {min_atr_pct}–{max_atr_pct}%)"
                if atr_pct
                else "ATR unavailable"
            ),
        },
        {
            "name": f"Reward:risk ≥ {min_rr}",
            "passed": rr >= min_rr,
            "detail": (
                f"planned R:R {rr:.2f}"
                if rr
                else "no valid SL/TP plan"
            ),
        },
        {
            "name": "Direction is not WAIT",
            "passed": direction in ("BUY", "SELL"),
            "detail": f"engine bias {direction}",
        },
        {
            "name": "Market is not choppy",
            "passed": not chop,
            "detail": (
                f"{brk_label} — directional efficiency "
                f"{efficiency:.2f} (need ≥ 0.22 to scalp)"
            ),
        },
        {
            "name": "No failed/fake breakout against us",
            "passed": not (fake and fake_against),
            "detail": (
                f"{brk_label}: a failed break points the other way"
                if (fake and fake_against)
                else (
                    brk_label
                    or "no failed break detected"
                )
            ),
        },
        {
            "name": "Higher timeframes not opposed",
            "passed": mtf_ok,
            "detail": mtf_detail,
        },
        {
            "name": "Price not over-extended",
            "passed": not extended,
            "detail": extension_detail,
        },
        {
            "name": "Volume participation",
            "passed": vol_ok,
            "detail": vol_detail,
        },
    ]

    tradeable = all(
        bool(c["passed"])
        for c in checks
    )

    if direction == "WAIT":
        summary = (
            "No trade: confirmations are split, so the engine stays flat "
            "rather than forcing a low-quality entry."
        )

    elif tradeable:
        summary = (
            f"{direction} setup at {price:.2f} with "
            f"{confidence:.1f}% confluence — "
            f"{aligned}/{len(confirmations)} confirmations agree "
            "and every risk gate passed."
        )

    else:
        failed = [
            str(c["name"])
            for c in checks
            if not c["passed"]
        ]

        summary = (
            f"Leaning {direction} at {confidence:.1f}% confidence, "
            "but holding fire — failed gate(s): "
            f"{', '.join(failed)}."
        )

    return {
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

        # IMPORTANT:
        # These are distances, NOT absolute market prices.
        "sl_dist": sl_dist,
        "tp_dist": tp_dist,

        "rr": round(rr, 2),
        "atr": a,
        "last_closed": last_closed,
        "level_reasons": level_reasons,

        "indicators": {
            k: v
            for k, v in snap.items()
            if k not in (
                "levels",
                "structure",
                "pattern",
                "breakout",
            )
            and isinstance(v, (int, float))
        },

        "levels": snap.get("levels"),
        "structure": snap.get("structure"),
        "pattern": snap.get("pattern"),
        "breakout": snap.get("breakout"),

        "mtf": {
            tf: {
                "trend": (
                    "UP"
                    if (
                        (
                            _f(sn, "ema21")
                            or _f(sn, "ema20")
                            or 0
                        )
                        >
                        (
                            _f(sn, "ema50")
                            or 0
                        )
                    )
                    else "DOWN"
                ),
                "rsi": _f(sn, "rsi"),
                "adx": _f(sn, "adx"),
            }
            for tf, sn in mtf_snaps.items()
        },
    }


def timeout_seconds(
    timeframe: str,
    max_hold_minutes: Optional[float] = None,
) -> int:
    """Scalper hold limit — an absolute wall-clock cap, not a candle count."""

    if max_hold_minutes:
        return int(max_hold_minutes * 60)

    return (
        INTERVAL_MINUTES.get(timeframe, 15)
        * 60
        * 10
    )