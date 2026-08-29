"""Trading API — every route is scoped to the signed-in subscriber's own wallet
and personal trading settings.

Market data is shared, but wallets, trades, history and strategy settings are
private to each signed-in subscriber.

Admin/default settings are managed separately and are used only as the starting
configuration for users who do not yet have personal settings.
"""
from __future__ import annotations

from typing import Any, Dict, List

from fastapi import APIRouter, Depends, HTTPException, Query

from lib import auth, engine, market, settings as settings_mod
from models.trading import (
    CandlesResponse,
    Dashboard,
    EngineConfig,
    EngineHealth,
    FeedStatus,
    Guards,
    SettingsPatch,
    Signal,
    Ticker,
    Trade,
    Wallet,
)

router = APIRouter(tags=["trading"])

Sub = Depends(auth.require_subscription)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _tf(timeframe: str) -> str:
    if timeframe not in market.INTERVAL_MINUTES:
        raise HTTPException(
            status_code=400,
            detail=f"unsupported timeframe '{timeframe}'",
        )
    return timeframe


# ---------------------------------------------------------------------------
# Market
# ---------------------------------------------------------------------------

@router.get("/debug/BTC-rest")
async def debug_BTC_rest(
    user: Dict[str, Any] = Sub,
):
    from lib.market import test_BTC_rest

    return await test_BTC_rest()


@router.get("/market/feed", response_model=FeedStatus)
async def get_feed(
    user: Dict[str, Any] = Sub,
) -> FeedStatus:
    await market.active_provider()

    return FeedStatus(
        **{
            k: v
            for k, v in market.feed_status.items()
            if k != "last_update"
        }
    )


@router.get("/market/ticker", response_model=Ticker)
async def get_ticker(
    user: Dict[str, Any] = Sub,
) -> Ticker:
    price = await market.get_price()
    stats = await market.get_stats_24h()

    return Ticker(
        symbol=market.feed_status.get("symbol") or "BTCUSDT",
        price=price,
        **stats,
    )


@router.get("/market/candles", response_model=CandlesResponse)
async def get_candles(
    timeframe: str = Query("15m"),
    limit: int = Query(180, ge=20, le=500),
    user: Dict[str, Any] = Sub,
) -> CandlesResponse:
    tf = _tf(timeframe)

    candles = await market.get_klines(
        tf,
        limit,
    )

    if not candles:
        raise HTTPException(
            status_code=503,
            detail="market data unavailable from all providers",
        )

    return CandlesResponse(
        symbol=market.feed_status.get("symbol") or "BTCUSDT",
        timeframe=tf,
        provider=market.feed_status.get("provider_label") or "",
        candles=candles,  # type: ignore[arg-type]
    )


# ---------------------------------------------------------------------------
# Signals
# ---------------------------------------------------------------------------

@router.get("/signal", response_model=Signal)
async def get_signal(
    timeframe: str = Query("15m"),
    user: Dict[str, Any] = Sub,
) -> Signal:
    return Signal(
        **await engine.get_signal(
            _tf(timeframe)
        )
    )


# ---------------------------------------------------------------------------
# Wallet
# ---------------------------------------------------------------------------

@router.get("/wallet", response_model=Wallet)
async def get_wallet(
    user: Dict[str, Any] = Sub,
) -> Wallet:
    user_id = user["id"]

    open_t = await engine.get_open_trade(
        user_id
    )

    price = await market.get_price()

    return Wallet(
        **await engine.wallet_view(
            user_id,
            open_t,
            price,
        )
    )


# ---------------------------------------------------------------------------
# Trades
# ---------------------------------------------------------------------------

@router.get("/trades", response_model=List[Trade])
async def get_trades(
    limit: int = Query(
        40,
        ge=1,
        le=200,
    ),
    user: Dict[str, Any] = Sub,
) -> List[Trade]:
    return [
        Trade(**t)
        for t in await engine.trade_history(
            user["id"],
            limit,
        )
    ]


@router.post(
    "/trades/{trade_id}/close",
    response_model=Trade,
)
async def close_trade(
    trade_id: str,
    user: Dict[str, Any] = Sub,
) -> Trade:
    user_id = user["id"]

    open_t = await engine.get_open_trade(
        user_id
    )

    if not open_t or open_t["id"] != trade_id:
        raise HTTPException(
            status_code=404,
            detail="no open trade with that id on your account",
        )

    price = await market.get_price()

    if not price:
        raise HTTPException(
            status_code=503,
            detail="no live price available to close against",
        )

    closed = await engine.close_trade(
        open_t,
        price,
        "MANUAL CLOSE",
        (
            f"Closed manually from the dashboard at "
            f"{price:.2f}, before stop, target or timeout "
            "was reached. Discretionary exits bypass the "
            "engine's risk plan."
        ),
    )

    return Trade(**closed)


@router.post(
    "/engine/reset",
    response_model=Wallet,
)
async def reset_engine(
    user: Dict[str, Any] = Sub,
) -> Wallet:
    user_id = user["id"]

    await engine.reset_all(
        user_id
    )

    return Wallet(
        **await engine.wallet_view(
            user_id,
            None,
            await market.get_price(),
        )
    )


# ---------------------------------------------------------------------------
# Engine
# ---------------------------------------------------------------------------

@router.get(
    "/engine/config",
    response_model=EngineConfig,
)
async def get_config(
    user: Dict[str, Any] = Sub,
) -> EngineConfig:
    """
    Return this user's personal engine configuration.

    Each subscriber receives their own settings.
    """
    return EngineConfig(
        **await engine.config(
            user["id"]
        )
    )


@router.get(
    "/engine/health",
    response_model=EngineHealth,
)
async def get_health() -> EngineHealth:
    """Public liveness probe for the never-sleep loop."""

    return EngineHealth(
        **engine.health()
    )


# ---------------------------------------------------------------------------
# Personal trading settings
# ---------------------------------------------------------------------------

@router.get(
    "/settings",
    response_model=EngineConfig,
)
async def read_settings(
    user: Dict[str, Any] = Sub,
) -> EngineConfig:
    """
    Return only the signed-in user's personal trading settings.
    """

    user_id = user["id"]

    cfg = await settings_mod.get_settings(
        user_id,
        refresh=True,
    )

    return EngineConfig(
        **{
            **cfg,
            "starting_balance": engine.STARTING_BALANCE,
            "timeframes": market.INTERVALS,
            "loop_seconds": engine.LOOP_SECONDS,
            "presence_window_seconds": engine.PRESENCE_WINDOW,
        }
    )


@router.put(
    "/settings",
    response_model=EngineConfig,
)
async def write_settings(
    patch: SettingsPatch,
    user: Dict[str, Any] = Sub,
) -> EngineConfig:
    """
    Update only the signed-in user's personal trading settings.

    A normal subscriber can change their own:
        - confidence threshold
        - timeframe
        - risk per trade
        - leverage
        - RR
        - ATR settings
        - trailing settings
        - break-even
        - partial TP
        - time cap
        - cooldown
        - circuit breakers
        - etc.

    These changes never modify another user's settings or the global defaults.
    """

    user_id = user["id"]

    await settings_mod.update_settings(
        user_id,
        patch.model_dump(
            exclude_none=True
        ),
    )

    return EngineConfig(
        **await engine.config(
            user_id
        )
    )


@router.post(
    "/settings/reset",
    response_model=EngineConfig,
)
async def restore_settings(
    user: Dict[str, Any] = Sub,
) -> EngineConfig:
    """
    Reset only this user's settings to the current default configuration.
    """

    user_id = user["id"]

    await settings_mod.reset_settings(
        user_id
    )

    return EngineConfig(
        **await engine.config(
            user_id
        )
    )


# ---------------------------------------------------------------------------
# User-specific guards
# ---------------------------------------------------------------------------

@router.get(
    "/engine/guards",
    response_model=Guards,
)
async def read_guards(
    user: Dict[str, Any] = Sub,
) -> Guards:
    """
    Evaluate entry guards using this user's personal settings.
    """

    user_id = user["id"]

    cfg = await settings_mod.get_settings(
        user_id,
        refresh=True,
    )

    return Guards(
        **await engine.guards(
            user_id,
            cfg,
            present=True,
        )
    )


# ---------------------------------------------------------------------------
# Presence
# ---------------------------------------------------------------------------

@router.post("/presence")
async def heartbeat(
    user: Dict[str, Any] = Sub,
) -> Dict[str, Any]:
    """
    Explicit dashboard heartbeat.

    Polling /dashboard also refreshes presence.
    """

    await engine.touch_presence(
        user["id"]
    )

    return {
        "present": True,
        "window_seconds": engine.PRESENCE_WINDOW,
    }


# ---------------------------------------------------------------------------
# Dashboard
# ---------------------------------------------------------------------------

@router.get(
    "/dashboard",
    response_model=Dashboard,
)
async def get_dashboard(
    timeframe: str = Query("15m"),
    user: Dict[str, Any] = Sub,
) -> Dashboard:
    return Dashboard(
        **await engine.dashboard(
            user["id"],
            _tf(timeframe),
        )
    )