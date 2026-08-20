"""Trading API — every route is scoped to the signed-in subscriber's own wallet.

Market data and signals are shared; wallets, trades and history are private.
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


def _tf(timeframe: str) -> str:
    if timeframe not in market.INTERVAL_MINUTES:
        raise HTTPException(status_code=400, detail=f"unsupported timeframe '{timeframe}'")
    return timeframe


@router.get("/market/feed", response_model=FeedStatus)
async def get_feed(user: Dict[str, Any] = Sub) -> FeedStatus:
    await market.active_provider()
    return FeedStatus(**{k: v for k, v in market.feed_status.items() if k != "last_update"})


@router.get("/market/ticker", response_model=Ticker)
async def get_ticker(user: Dict[str, Any] = Sub) -> Ticker:
    price = await market.get_price()
    stats = await market.get_stats_24h()
    return Ticker(symbol=market.feed_status.get("symbol") or "XAUUSDT", price=price, **stats)


@router.get("/market/candles", response_model=CandlesResponse)
async def get_candles(
    timeframe: str = Query("15m"),
    limit: int = Query(180, ge=20, le=500),
    user: Dict[str, Any] = Sub,
) -> CandlesResponse:
    tf = _tf(timeframe)
    candles = await market.get_klines(tf, limit)
    if not candles:
        raise HTTPException(status_code=503, detail="market data unavailable from all providers")
    return CandlesResponse(
        symbol=market.feed_status.get("symbol") or "XAUUSDT",
        timeframe=tf,
        provider=market.feed_status.get("provider_label") or "",
        candles=candles,  # type: ignore[arg-type]
    )


@router.get("/signal", response_model=Signal)
async def get_signal(timeframe: str = Query("15m"), user: Dict[str, Any] = Sub) -> Signal:
    return Signal(**await engine.get_signal(_tf(timeframe)))


@router.get("/wallet", response_model=Wallet)
async def get_wallet(user: Dict[str, Any] = Sub) -> Wallet:
    open_t = await engine.get_open_trade(user["id"])
    return Wallet(**await engine.wallet_view(user["id"], open_t, await market.get_price()))


@router.get("/trades", response_model=List[Trade])
async def get_trades(limit: int = Query(40, ge=1, le=200), user: Dict[str, Any] = Sub) -> List[Trade]:
    return [Trade(**t) for t in await engine.trade_history(user["id"], limit)]


@router.post("/trades/{trade_id}/close", response_model=Trade)
async def close_trade(trade_id: str, user: Dict[str, Any] = Sub) -> Trade:
    open_t = await engine.get_open_trade(user["id"])
    if not open_t or open_t["id"] != trade_id:
        raise HTTPException(status_code=404, detail="no open trade with that id on your account")
    price = await market.get_price()
    if not price:
        raise HTTPException(status_code=503, detail="no live price available to close against")
    closed = await engine.close_trade(
        open_t,
        price,
        "MANUAL CLOSE",
        f"Closed manually from the dashboard at {price:.2f}, before stop, target or timeout was reached. "
        "Discretionary exits bypass the engine's risk plan.",
    )
    return Trade(**closed)


@router.post("/engine/reset", response_model=Wallet)
async def reset_engine(user: Dict[str, Any] = Sub) -> Wallet:
    await engine.reset_all(user["id"])
    return Wallet(**await engine.wallet_view(user["id"], None, await market.get_price()))


@router.get("/engine/config", response_model=EngineConfig)
async def get_config(user: Dict[str, Any] = Sub) -> EngineConfig:
    return EngineConfig(**await engine.config())


@router.get("/engine/health", response_model=EngineHealth)
async def get_health() -> EngineHealth:
    """Public liveness probe for the never-sleep loop."""
    return EngineHealth(**engine.health())


@router.get("/settings", response_model=EngineConfig)
async def read_settings(user: Dict[str, Any] = Sub) -> EngineConfig:
    return EngineConfig(**await engine.config())


@router.put("/settings", response_model=EngineConfig)
async def write_settings(
    patch: SettingsPatch, user: Dict[str, Any] = Depends(auth.require_admin)
) -> EngineConfig:
    """Strategy settings are global, so only an admin may change them."""
    await settings_mod.update_settings(patch.model_dump(exclude_none=True))
    return EngineConfig(**await engine.config())


@router.post("/settings/reset", response_model=EngineConfig)
async def restore_settings(user: Dict[str, Any] = Depends(auth.require_admin)) -> EngineConfig:
    await settings_mod.reset_settings()
    return EngineConfig(**await engine.config())


@router.get("/engine/guards", response_model=Guards)
async def read_guards(user: Dict[str, Any] = Sub) -> Guards:
    cfg = await settings_mod.get_settings()
    return Guards(**await engine.guards(user["id"], cfg))


@router.post("/presence")
async def heartbeat(user: Dict[str, Any] = Sub) -> Dict[str, Any]:
    """Explicit heartbeat. Polling /dashboard also refreshes presence."""
    await engine.touch_presence(user["id"])
    return {"present": True, "window_seconds": engine.PRESENCE_WINDOW}


@router.get("/dashboard", response_model=Dashboard)
async def get_dashboard(timeframe: str = Query("15m"), user: Dict[str, Any] = Sub) -> Dashboard:
    return Dashboard(**await engine.dashboard(user["id"], _tf(timeframe)))
