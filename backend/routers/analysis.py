"""Session awareness and strategy backtesting."""

from __future__ import annotations

import asyncio
import time
from datetime import datetime, timezone
from typing import Any, Dict, Tuple

from fastapi import APIRouter, Depends, HTTPException, Query

from lib import auth, backtest, market, market_sessions, settings as settings_mod, strategy
from models.accounts import BacktestResult, SessionSnapshot

router = APIRouter(tags=["analysis"])

_cache: Dict[str, Tuple[float, Dict[str, Any]]] = {}
CACHE_TTL = 120.0


@router.get("/market/sessions", response_model=SessionSnapshot)
async def sessions() -> SessionSnapshot:
    return SessionSnapshot(**market_sessions.snapshot())


@router.get(
    "/backtest",
    response_model=BacktestResult,
    dependencies=[Depends(auth.require_subscription)],
)
async def run_backtest(
    timeframe: str = Query("5m"),
    days: float = Query(3.0, ge=0.25, le=30.0),
    refresh: bool = Query(False),
    user: Dict[str, Any] = Depends(auth.require_subscription),
) -> BacktestResult:

    if timeframe not in market.INTERVAL_MINUTES:
        raise HTTPException(
            status_code=400,
            detail=f"unsupported timeframe '{timeframe}'",
        )

    # ---------------------------------------------------------------
    # IMPORTANT:
    # Cache is now user-specific.
    # Each user gets a backtest based on their own settings.
    # ---------------------------------------------------------------
    user_id = str(user["id"])
    cfg = await settings_mod.get_settings(user_id, refresh=True)
    symbol = cfg.get("symbol", market.DEFAULT_SYMBOL)
    key = f"{user_id}:{symbol}:{timeframe}:{days}"

    hit = _cache.get(key)

    if (
        hit
        and not refresh
        and (time.time() - hit[0]) < CACHE_TTL
    ):
        return BacktestResult(**hit[1])

    # ---------------------------------------------------------------
    # Get user's preferred symbol
    # ---------------------------------------------------------------
    # ---------------------------------------------------------------
    # Market history remains shared.
    # ---------------------------------------------------------------
    tf_min = market.INTERVAL_MINUTES[timeframe]

    wanted = (
        int(days * 24 * 60 / tf_min)
        + backtest.WARMUP
    )

    limit = max(
        300,
        min(1500, wanted),
    )

    # ✅ FIXED: symbol first
    candles = await market.get_klines(
        symbol,  # ✅ Add symbol first
        timeframe,
        limit,
    )

    if len(candles) < backtest.WARMUP + 30:
        raise HTTPException(
            status_code=503,
            detail="not enough market history available to backtest",
        )

    # ---------------------------------------------------------------
    # Multi-timeframe market data remains shared.
    # ---------------------------------------------------------------
    mtf: Dict[str, Any] = {}

    for tf in strategy.MTF_MAP.get(
        timeframe,
        [],
    ):
        if tf != timeframe:
            # ✅ FIXED: symbol first
            mtf[tf] = await market.get_klines(
                symbol,  # ✅ Add symbol first
                tf,
                400,
            )

    # ---------------------------------------------------------------
    # Run backtest using this user's personal configuration.
    # ---------------------------------------------------------------
    result = await asyncio.to_thread(
        backtest.run,
        candles,
        timeframe,
        cfg,
        mtf,
        symbol,
    )

    result["generated_at"] = (
        datetime.now(timezone.utc).isoformat()
    )

    result["starting_equity"] = (
        backtest.START_EQUITY
    )

    result["settings_used"] = {
        "confidence_threshold": cfg[
            "confidence_threshold"
        ],
        "risk_per_trade_pct": cfg[
            "risk_per_trade_pct"
        ],
        "atr_sl_mult": cfg[
            "atr_sl_mult"
        ],
        "base_rr": cfg[
            "base_rr"
        ],
        "breakeven_at_r": cfg[
            "breakeven_at_r"
        ],
        "partial_tp_at_r": cfg[
            "partial_tp_at_r"
        ],
        "partial_tp_fraction": cfg[
            "partial_tp_fraction"
        ],
        "trail_atr_mult": cfg[
            "trail_atr_mult"
        ],
        "max_hold_minutes": cfg[
            "max_hold_minutes"
        ],
        "min_adx": cfg[
            "min_adx"
        ],
        "min_rr": cfg[
            "min_rr"
        ],
    }

    # ---------------------------------------------------------------
    # Store result only under THIS user's cache key.
    # ---------------------------------------------------------------
    _cache[key] = (
        time.time(),
        result,
    )

    return BacktestResult(**result)