"""Pure-python technical indicators.

Stateless, deterministic indicator calculations for the BTCUSD/XAUUSD
scalping engine.  The module returns measurements only; trade direction
should be decided by the strategy layer.
"""
from __future__ import annotations

from typing import Dict, List, Optional, Sequence

Candle = Dict[str, float]


def closes(candles: Sequence[Candle]) -> List[float]:
    return [float(c["close"]) for c in candles]


def sma(values: Sequence[float], period: int) -> Optional[float]:
    if period <= 0 or len(values) < period:
        return None
    return sum(values[-period:]) / period


def ema_series(
    values: Sequence[float],
    period: int,
) -> List[Optional[float]]:
    out: List[Optional[float]] = [None] * len(values)
    if period <= 0 or len(values) < period:
        return out

    k = 2.0 / (period + 1.0)
    prev = sum(values[:period]) / period
    out[period - 1] = prev

    for i in range(period, len(values)):
        prev = values[i] * k + prev * (1.0 - k)
        out[i] = prev

    return out


def ema(
    values: Sequence[float],
    period: int,
) -> Optional[float]:
    series = ema_series(values, period)
    return series[-1] if series else None


def rsi(
    values: Sequence[float],
    period: int = 14,
) -> Optional[float]:
    """Wilder RSI.

    Returns the raw RSI measurement.  Overbought/oversold interpretation
    belongs in the strategy layer so trending markets are not automatically
    treated as reversal setups.
    """
    if period <= 0 or len(values) < period + 1:
        return None

    gains = 0.0
    losses = 0.0

    for i in range(1, period + 1):
        delta = values[i] - values[i - 1]
        gains += max(delta, 0.0)
        losses += max(-delta, 0.0)

    avg_gain = gains / period
    avg_loss = losses / period

    for i in range(period + 1, len(values)):
        delta = values[i] - values[i - 1]
        avg_gain = (
            avg_gain * (period - 1) + max(delta, 0.0)
        ) / period
        avg_loss = (
            avg_loss * (period - 1) + max(-delta, 0.0)
        ) / period

    if avg_loss == 0:
        return 100.0

    rs = avg_gain / avg_loss
    return 100.0 - (100.0 / (1.0 + rs))


def macd(
    values: Sequence[float],
    fast: int = 12,
    slow: int = 26,
    signal: int = 9,
) -> Dict[str, Optional[float]]:
    fast_s = ema_series(values, fast)
    slow_s = ema_series(values, slow)

    line: List[float] = []

    for fast_value, slow_value in zip(fast_s, slow_s):
        if fast_value is not None and slow_value is not None:
            line.append(fast_value - slow_value)

    if len(line) < signal + 1:
        return {
            "macd": None,
            "signal": None,
            "hist": None,
            "hist_prev": None,
            "hist_slope": None,
        }

    signal_s = ema_series(line, signal)
    signal_value = signal_s[-1]
    signal_prev = signal_s[-2]

    hist = (
        line[-1] - signal_value
        if signal_value is not None
        else None
    )
    hist_prev = (
        line[-2] - signal_prev
        if signal_prev is not None
        else None
    )

    hist_slope = (
        hist - hist_prev
        if hist is not None and hist_prev is not None
        else None
    )

    return {
        "macd": line[-1],
        "signal": signal_value,
        "hist": hist,
        "hist_prev": hist_prev,
        "hist_slope": hist_slope,
    }


def bollinger(
    values: Sequence[float],
    period: int = 20,
    mult: float = 2.0,
) -> Dict[str, Optional[float]]:
    """Bollinger Bands plus expansion/contraction measurements."""
    empty = {
        "upper": None,
        "middle": None,
        "lower": None,
        "width_pct": None,
        "width_prev_pct": None,
        "width_change_pct": None,
        "percent_b": None,
    }

    if period <= 0 or len(values) < period + 1:
        return empty

    window = values[-period:]
    previous_window = values[-period - 1:-1]

    middle = sum(window) / period
    previous_middle = sum(previous_window) / period

    variance = sum(
        (value - middle) ** 2
        for value in window
    ) / period

    previous_variance = sum(
        (value - previous_middle) ** 2
        for value in previous_window
    ) / period

    sd = variance ** 0.5
    previous_sd = previous_variance ** 0.5

    upper = middle + mult * sd
    lower = middle - mult * sd

    previous_upper = previous_middle + mult * previous_sd
    previous_lower = previous_middle - mult * previous_sd

    band_range = upper - lower
    previous_range = previous_upper - previous_lower

    width_pct = (
        band_range / middle * 100.0
        if middle
        else None
    )

    width_prev_pct = (
        previous_range / previous_middle * 100.0
        if previous_middle
        else None
    )

    width_change_pct = (
        width_pct - width_prev_pct
        if width_pct is not None
        and width_prev_pct is not None
        else None
    )

    percent_b = (
        (values[-1] - lower) / band_range
        if band_range
        else 0.5
    )

    return {
        "upper": upper,
        "middle": middle,
        "lower": lower,
        "width_pct": width_pct,
        "width_prev_pct": width_prev_pct,
        "width_change_pct": width_change_pct,
        "percent_b": percent_b,
    }


def true_ranges(candles: Sequence[Candle]) -> List[float]:
    trs: List[float] = []

    for i in range(1, len(candles)):
        high = candles[i]["high"]
        low = candles[i]["low"]
        previous_close = candles[i - 1]["close"]

        trs.append(
            max(
                high - low,
                abs(high - previous_close),
                abs(low - previous_close),
            )
        )

    return trs


def atr(
    candles: Sequence[Candle],
    period: int = 14,
) -> Optional[float]:
    """Wilder ATR."""
    if period <= 0:
        return None

    trs = true_ranges(candles)

    if len(trs) < period:
        return None

    value = sum(trs[:period]) / period

    for tr in trs[period:]:
        value = (
            value * (period - 1) + tr
        ) / period

    return value


def adx(
    candles: Sequence[Candle],
    period: int = 14,
) -> Dict[str, Optional[float]]:
    """Wilder-style ADX, DI and ADX slope."""
    empty = {
        "adx": None,
        "adx_prev": None,
        "adx_slope": None,
        "plus_di": None,
        "minus_di": None,
    }

    if period <= 0 or len(candles) < period * 2 + 2:
        return empty

    plus_dm: List[float] = []
    minus_dm: List[float] = []
    trs = true_ranges(candles)

    for i in range(1, len(candles)):
        up = candles[i]["high"] - candles[i - 1]["high"]
        down = candles[i - 1]["low"] - candles[i]["low"]

        plus_dm.append(
            up if up > down and up > 0 else 0.0
        )
        minus_dm.append(
            down if down > up and down > 0 else 0.0
        )

    def wilder(sequence: List[float]) -> List[float]:
        if len(sequence) < period:
            return []

        output: List[float] = []
        value = sum(sequence[:period])
        output.append(value)

        for item in sequence[period:]:
            value = (
                value - value / period + item
            )
            output.append(value)

        return output

    tr_s = wilder(trs)
    plus_s = wilder(plus_dm)
    minus_s = wilder(minus_dm)

    if not tr_s or not plus_s or not minus_s:
        return empty

    dxs: List[float] = []

    for tr_value, plus_value, minus_value in zip(
        tr_s,
        plus_s,
        minus_s,
    ):
        if tr_value <= 0:
            continue

        plus_di = 100.0 * plus_value / tr_value
        minus_di = 100.0 * minus_value / tr_value
        denominator = plus_di + minus_di

        if denominator > 0:
            dxs.append(
                100.0
                * abs(plus_di - minus_di)
                / denominator
            )

    if len(dxs) < period:
        return empty

    adx_series: List[float] = []

    adx_value = sum(dxs[:period]) / period
    adx_series.append(adx_value)

    for dx in dxs[period:]:
        adx_value = (
            adx_value * (period - 1) + dx
        ) / period
        adx_series.append(adx_value)

    adx_prev = (
        adx_series[-2]
        if len(adx_series) >= 2
        else None
    )

    tr_last = tr_s[-1]

    if tr_last <= 0:
        return empty

    plus_di_last = (
        100.0 * plus_s[-1] / tr_last
    )
    minus_di_last = (
        100.0 * minus_s[-1] / tr_last
    )

    return {
        "adx": adx_value,
        "adx_prev": adx_prev,
        "adx_slope": (
            adx_value - adx_prev
            if adx_prev is not None
            else None
        ),
        "plus_di": plus_di_last,
        "minus_di": minus_di_last,
    }


def vwap(
    candles: Sequence[Candle],
    period: int = 60,
) -> Optional[float]:
    """Rolling volume-weighted average price."""
    if period <= 0 or not candles:
        return None

    window = candles[-period:]
    total_volume = sum(
        max(float(c["volume"]), 0.0)
        for c in window
    )

    if total_volume <= 0:
        return None

    weighted_price = sum(
        (
            (c["high"] + c["low"] + c["close"])
            / 3.0
        )
        * max(float(c["volume"]), 0.0)
        for c in window
    )

    return weighted_price / total_volume


def swing_points(
    candles: Sequence[Candle],
    left: int = 2,
    right: int = 2,
) -> Dict[str, List[Dict[str, float]]]:
    highs: List[Dict[str, float]] = []
    lows: List[Dict[str, float]] = []

    if left < 1 or right < 1:
        return {"highs": highs, "lows": lows}

    for i in range(
        left,
        len(candles) - right,
    ):
        window = candles[
            i - left:i + right + 1
        ]
        candle = candles[i]

        if candle["high"] == max(
            item["high"] for item in window
        ):
            highs.append(
                {
                    "index": float(i),
                    "price": candle["high"],
                }
            )

        if candle["low"] == min(
            item["low"] for item in window
        ):
            lows.append(
                {
                    "index": float(i),
                    "price": candle["low"],
                }
            )

    return {"highs": highs, "lows": lows}


def support_resistance(
    candles: Sequence[Candle],
    lookback: int = 120,
) -> Dict[str, List[float]]:
    """Cluster recent swing points into nearby S/R levels.

    Tolerance adapts to both price and current ATR so the same indicator
    behaves sensibly on BTCUSD and XAUUSD without hard-coding a broker's
    symbol suffix.
    """
    window = list(candles[-lookback:])

    if len(window) < 20:
        return {
            "support": [],
            "resistance": [],
        }

    swing = swing_points(window)
    price = window[-1]["close"]

    atr_value = atr(window, 14)

    price_tolerance = price * 0.0008
    atr_tolerance = (
        atr_value * 0.25
        if atr_value is not None
        else 0.0
    )

    tolerance = max(
        price_tolerance,
        atr_tolerance,
        0.01,
    )

    def cluster(
        points: List[Dict[str, float]],
    ) -> List[float]:
        levels: List[List[float]] = []

        for point in sorted(
            item["price"] for item in points
        ):
            if (
                levels
                and abs(point - levels[-1][-1])
                <= tolerance * 2.0
            ):
                levels[-1].append(point)
            else:
                levels.append([point])

        return [
            sum(group) / len(group)
            for group in levels
        ]

    resistance = [
        level
        for level in cluster(swing["highs"])
        if level > price
    ]

    support = [
        level
        for level in cluster(swing["lows"])
        if level < price
    ]

    resistance.sort()
    support.sort(reverse=True)

    return {
        "support": support[:4],
        "resistance": resistance[:4],
    }


def market_structure(
    candles: Sequence[Candle],
) -> Dict[str, object]:
    """Higher-high/higher-low vs lower-high/lower-low structure read."""
    swing = swing_points(
        list(candles[-120:])
    )

    highs = [
        point["price"]
        for point in swing["highs"]
    ][-3:]

    lows = [
        point["price"]
        for point in swing["lows"]
    ][-3:]

    if len(highs) < 2 or len(lows) < 2:
        return {
            "label": "UNCLEAR",
            "bias": 0.0,
            "detail": (
                "not enough swing points "
                "to read structure"
            ),
        }

    hh = highs[-1] > highs[-2]
    hl = lows[-1] > lows[-2]
    lh = highs[-1] < highs[-2]
    ll = lows[-1] < lows[-2]

    if hh and hl:
        return {
            "label": "UPTREND",
            "bias": 1.0,
            "detail": "higher highs and higher lows",
        }

    if lh and ll:
        return {
            "label": "DOWNTREND",
            "bias": -1.0,
            "detail": "lower highs and lower lows",
        }

    if hh and ll:
        return {
            "label": "EXPANSION",
            "bias": 0.0,
            "detail": (
                "broadening range, "
                "both extremes extending"
            ),
        }

    if hl and lh:
        return {
            "label": "COMPRESSION",
            "bias": 0.0,
            "detail": (
                "contracting range, "
                "coiling before expansion"
            ),
        }

    return {
        "label": "RANGE",
        "bias": 0.3 if hl else -0.3,
        "detail": "mixed swings, no clean trend",
    }


def candle_pattern(
    candles: Sequence[Candle],
) -> Dict[str, object]:
    """Last-candle price action measurement."""
    if len(candles) < 3:
        return {
            "label": "NONE",
            "bias": 0.0,
            "detail": "insufficient candles",
        }

    candle = candles[-1]
    previous = candles[-2]

    body = abs(
        candle["close"] - candle["open"]
    )
    candle_range = max(
        candle["high"] - candle["low"],
        1e-9,
    )

    upper_wick = (
        candle["high"]
        - max(candle["close"], candle["open"])
    )

    lower_wick = (
        min(candle["close"], candle["open"])
        - candle["low"]
    )

    bullish = candle["close"] > candle["open"]
    previous_body = abs(
        previous["close"] - previous["open"]
    )

    if body > previous_body and (
        (
            bullish
            and candle["close"] > previous["open"]
            and candle["open"] < previous["close"]
            and previous["close"] < previous["open"]
        )
        or (
            not bullish
            and candle["close"] < previous["open"]
            and candle["open"] > previous["close"]
            and previous["close"] > previous["open"]
        )
    ):
        return {
            "label": (
                "BULLISH ENGULFING"
                if bullish
                else "BEARISH ENGULFING"
            ),
            "bias": 1.0 if bullish else -1.0,
            "detail": (
                "last candle fully engulfs "
                "the prior opposite candle"
            ),
        }

    if (
        lower_wick > body * 2.0
        and upper_wick < body
    ):
        return {
            "label": "HAMMER / LONG LOWER WICK",
            "bias": 0.7,
            "detail": (
                "sellers rejected at the lows"
            ),
        }

    if (
        upper_wick > body * 2.0
        and lower_wick < body
    ):
        return {
            "label": (
                "SHOOTING STAR / LONG UPPER WICK"
            ),
            "bias": -0.7,
            "detail": (
                "buyers rejected at the highs"
            ),
        }

    if body / candle_range > 0.7:
        return {
            "label": (
                "STRONG BULL MARUBOZU"
                if bullish
                else "STRONG BEAR MARUBOZU"
            ),
            "bias": 0.8 if bullish else -0.8,
            "detail": (
                "wide-range candle closing "
                "near its extreme"
            ),
        }

    if body / candle_range < 0.15:
        return {
            "label": "DOJI / INDECISION",
            "bias": 0.0,
            "detail": (
                "tiny body, buyers and "
                "sellers balanced"
            ),
        }

    return {
        "label": (
            "MINOR BULL CANDLE"
            if bullish
            else "MINOR BEAR CANDLE"
        ),
        "bias": 0.25 if bullish else -0.25,
        "detail": (
            "ordinary candle, no strong "
            "price-action signal"
        ),
    }


def breakout(
    candles: Sequence[Candle],
    lookback: int = 20,
) -> Dict[str, object]:
    """Breakout quality, failed-break read and chop detection.

    The breakout range is built only from candles before the latest
    candle.  The strategy layer should pass closed candles when it wants
    a non-repainting signal.
    """
    if (
        lookback <= 0
        or len(candles) < lookback + 5
    ):
        return {
            "label": "NO DATA",
            "bias": 0.0,
            "detail": (
                "not enough candles "
                "for a breakout read"
            ),
            "quality": 0.0,
            "fake": False,
            "chop": False,
            "efficiency": 0.0,
        }

    window = list(
        candles[-(lookback + 1):-1]
    )
    last = candles[-1]

    high_level = max(
        candle["high"] for candle in window
    )
    low_level = min(
        candle["low"] for candle in window
    )

    range_size = max(
        high_level - low_level,
        1e-9,
    )

    body = abs(
        last["close"] - last["open"]
    )

    candle_range = max(
        last["high"] - last["low"],
        1e-9,
    )

    close_position = (
        last["close"] - last["low"]
    ) / candle_range

    volumes = [
        candle["volume"]
        for candle in candles[-(lookback + 1):]
    ]

    volume_average = (
        sum(volumes[:-1])
        / max(1, len(volumes) - 1)
    )

    volume_ratio = (
        volumes[-1] / volume_average
        if volume_average > 0
        else 1.0
    )

    closes_window = [
        candle["close"]
        for candle in candles[-(lookback + 1):]
    ]

    travel = sum(
        abs(
            closes_window[i]
            - closes_window[i - 1]
        )
        for i in range(1, len(closes_window))
    )

    travel = max(travel, 1e-9)

    efficiency = abs(
        closes_window[-1]
        - closes_window[0]
    ) / travel

    chop = efficiency < 0.22

    up_break = last["close"] > high_level
    down_break = last["close"] < low_level

    pierced_up = (
        last["high"] > high_level
        and last["close"] <= high_level
    )

    pierced_down = (
        last["low"] < low_level
        and last["close"] >= low_level
    )

    if up_break or down_break:
        quality = min(
            1.0,
            (
                body / candle_range
            ) * 0.4
            + min(
                1.0,
                volume_ratio / 1.5,
            ) * 0.3
            + (
                close_position
                if up_break
                else 1.0 - close_position
            ) * 0.3,
        )

        beyond = (
            last["close"] - high_level
            if up_break
            else low_level - last["close"]
        )

        label = (
            "BREAKOUT UP"
            if up_break
            else "BREAKOUT DOWN"
        )

        bias = (
            quality
            if up_break
            else -quality
        )

        detail = (
            f"closed {beyond:.2f} beyond the "
            f"{lookback}-bar "
            f"{'high ' + format(high_level, '.2f') if up_break else 'low ' + format(low_level, '.2f')} "
            f"on {volume_ratio:.2f}x average volume, "
            f"body {body / candle_range * 100:.0f}% "
            f"of range "
            f"(quality {quality * 100:.0f}%)"
        )

        return {
            "label": label,
            "bias": bias,
            "detail": detail,
            "quality": round(quality, 3),
            "fake": False,
            "chop": chop,
            "efficiency": round(
                efficiency,
                3,
            ),
        }

    if pierced_up or pierced_down:
        label = (
            "FAKE BREAKOUT UP"
            if pierced_up
            else "FAKE BREAKOUT DOWN"
        )

        level = (
            high_level
            if pierced_up
            else low_level
        )

        return {
            "label": label,
            "bias": (
                -0.7
                if pierced_up
                else 0.7
            ),
            "detail": (
                f"price pierced {level:.2f} "
                f"but closed back inside the "
                f"{lookback}-bar range — failed "
                "break, liquidity grab rather "
                "than continuation"
            ),
            "quality": 0.0,
            "fake": True,
            "chop": chop,
            "efficiency": round(
                efficiency,
                3,
            ),
        }

    position = (
        last["close"] - low_level
    ) / range_size

    return {
        "label": (
            "CHOPPY RANGE"
            if chop
            else "INSIDE RANGE"
        ),
        "bias": 0.0,
        "detail": (
            f"price is {position * 100:.0f}% "
            f"up the {lookback}-bar range "
            f"({low_level:.2f}–{high_level:.2f}), "
            f"directional efficiency "
            f"{efficiency:.2f}"
            + (
                " — chop, no clean scalp"
                if chop
                else ""
            )
        ),
        "quality": 0.0,
        "fake": False,
        "chop": chop,
        "efficiency": round(
            efficiency,
            3,
        ),
    }


def snapshot(
    candles: Sequence[Candle],
) -> Dict[str, object]:
    """Return all measurements used by the strategy."""
    cl = closes(candles)
    volumes = [
        float(c["volume"])
        for c in candles
    ]

    macd_data = macd(cl)
    bb = bollinger(cl)
    dmi = adx(candles)
    atr_value = atr(candles)
    breakout_data = breakout(candles)

    return {
        "price": cl[-1] if cl else None,

        "ema9": ema(cl, 9),
        "ema21": ema(cl, 21),
        "ema20": ema(cl, 20),
        "ema50": ema(cl, 50),
        "ema200": ema(cl, 200),

        "rsi": rsi(cl),

        "macd": macd_data["macd"],
        "macd_signal": macd_data["signal"],
        "macd_hist": macd_data["hist"],
        "macd_hist_prev": macd_data["hist_prev"],
        "macd_hist_slope": macd_data["hist_slope"],

        "bb_upper": bb["upper"],
        "bb_middle": bb["middle"],
        "bb_lower": bb["lower"],
        "bb_width_pct": bb["width_pct"],
        "bb_width_prev_pct": bb["width_prev_pct"],
        "bb_width_change_pct": bb["width_change_pct"],
        "percent_b": bb["percent_b"],

        "atr": atr_value,
        "atr_pct": (
            atr_value / cl[-1] * 100.0
            if atr_value is not None
            and cl
            and cl[-1] > 0
            else None
        ),

        "adx": dmi["adx"],
        "adx_prev": dmi["adx_prev"],
        "adx_slope": dmi["adx_slope"],
        "plus_di": dmi["plus_di"],
        "minus_di": dmi["minus_di"],

        "vwap": vwap(candles),

        "volume": (
            volumes[-1]
            if volumes
            else None
        ),
        "volume_avg": sma(
            volumes,
            20,
        ),

        "breakout_quality": float(
            breakout_data.get("quality")
            or 0.0
        ),
        "range_efficiency": float(
            breakout_data.get("efficiency")
            or 0.0
        ),

        "levels": support_resistance(candles),
        "structure": market_structure(candles),
        "pattern": candle_pattern(candles),
        "breakout": breakout_data,
    }
