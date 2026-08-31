"""Trading routes — paper trading dashboard, signals, and execution"""

from typing import Optional
from fastapi import APIRouter, Request, HTTPException, Query
from datetime import datetime, timezone

from lib import auth, paper_trading, market, strategy, settings as settings_mod
from lib.db import db

router = APIRouter(tags=["trading"])


# =====================================================================
# HELPERS
# =====================================================================

def _now() -> datetime:
    return datetime.now(timezone.utc)


# =====================================================================
# DASHBOARD (Multi-Symbol)
# =====================================================================

@router.get("/dashboard")
async def get_dashboard(
    request: Request,
    timeframe: str = Query("1m", description="Timeframe: 1m, 5m, 15m, 30m, 1h"),
    symbol: str = Query("BTCUSDT", description="Symbol: BTCUSDT, XAUUSD")
):
    """Get full dashboard data for a specific symbol"""
    user = await auth.require_subscription(request)
    
    # ✅ Update presence
    await paper_trading.touch_presence(user["id"])
    
    # ✅ Get user settings
    cfg = await settings_mod.get_settings(user["id"], refresh=True)
    
    # ✅ Get market data for symbol
    price = await market.get_price(symbol)
    if not price:
        price = 0.0
    
    # ✅ Get candles for the symbol (FIXED: symbol first)
    candles = await market.get_klines(symbol, timeframe, 160)
    candles_by_tf = {timeframe: candles}
    
    # ✅ Get MTF candles (FIXED: symbol first)
    mtf_map = {
        "1m": ["1m", "5m", "15m", "30m", "1h"],
        "5m": ["5m", "15m", "30m", "1h"],
        "15m": ["15m", "1h"],
        "30m": ["30m", "1h"],
        "1h": ["1h"],
    }
    for tf in mtf_map.get(timeframe, []):
        if tf != timeframe:
            tf_candles = await market.get_klines(symbol, tf, 60)
            candles_by_tf[tf] = tf_candles
    
    # ✅ Get signal for symbol
    cfg_with_user = {**cfg, "user_id": user["id"]}
    signal = await strategy.analyze(
        symbol=symbol,
        timeframe=timeframe,
        candles_by_tf=candles_by_tf,
        price=price,
        cfg=cfg_with_user
    )
    
    # ✅ Get open trade
    open_trade = await paper_trading.get_open_trade(user["id"])
    
    # ✅ Decorate open trade with current price
    if open_trade and price:
        open_trade["current_price"] = price
        open_trade["unrealized_pnl"] = paper_trading._pnl(open_trade, price)
    
    # ✅ Get wallet view
    wallet = await paper_trading.wallet_view(user["id"], open_trade, price)
    
    # ✅ Get guards
    guards = await paper_trading.guards(user["id"], cfg, present=True)
    
    # ✅ Get trade history
    history = await paper_trading.trade_history(user["id"], 40)
    
    # ✅ Get feed status
    feed_status = market.get_feed_status(symbol)
    
    # ✅ Get 24h stats
    stats = await market.get_stats_24h(symbol)
    
    # ✅ Build ticker
    ticker = {
        "symbol": symbol,
        "price": price,
        "open_24h": stats.get("open_24h", 0),
        "high_24h": stats.get("high_24h", 0),
        "low_24h": stats.get("low_24h", 0),
        "volume_24h": stats.get("volume_24h", 0),
        "change_24h": stats.get("change_24h", 0),
        "change_pct_24h": stats.get("change_pct_24h", 0),
    }
    
    # ✅ Get engine health
    engine_health = paper_trading.health()
    
    # ✅ Sessions (placeholder for now)
    sessions = {
        "utc_time": _now().isoformat(),
        "sessions": [],
        "active": [],
        "liquidity": "medium",
        "tradeable": True,
        "note": "All sessions active",
        "overlap_active": False,
        "minutes_to_overlap": 0,
    }
    
    # ✅ Build response
    return {
        "feed": feed_status,
        "ticker": ticker,
        "signal": signal,
        "wallet": wallet,
        "open_trade": open_trade,
        "history": history,
        "config": cfg,
        "guards": guards,
        "sessions": sessions,
        "engine": engine_health,
        "server_time": _now().isoformat(),
    }


# =====================================================================
# SIGNAL ONLY (Multi-Symbol)
# =====================================================================

@router.get("/signal")
async def get_signal(
    request: Request,
    timeframe: str = Query("1m", description="Timeframe: 1m, 5m, 15m, 30m, 1h"),
    symbol: str = Query("BTCUSDT", description="Symbol: BTCUSDT, XAUUSD")
):
    """Get only the signal for a specific symbol"""
    user = await auth.require_subscription(request)
    
    # ✅ Get user settings
    cfg = await settings_mod.get_settings(user["id"], refresh=True)
    
    # ✅ Get market data
    price = await market.get_price(symbol)
    if not price:
        price = 0.0
    
    # ✅ Get candles (FIXED: symbol first)
    candles = await market.get_klines(symbol, timeframe, 160)
    candles_by_tf = {timeframe: candles}
    
    # ✅ Get MTF candles (FIXED: symbol first)
    mtf_map = {
        "1m": ["1m", "5m", "15m", "30m", "1h"],
        "5m": ["5m", "15m", "30m", "1h"],
        "15m": ["15m", "1h"],
        "30m": ["30m", "1h"],
        "1h": ["1h"],
    }
    for tf in mtf_map.get(timeframe, []):
        if tf != timeframe:
            tf_candles = await market.get_klines(symbol, tf, 60)
            candles_by_tf[tf] = tf_candles
    
    # ✅ Get signal
    cfg_with_user = {**cfg, "user_id": user["id"]}
    signal = await strategy.analyze(
        symbol=symbol,
        timeframe=timeframe,
        candles_by_tf=candles_by_tf,
        price=price,
        cfg=cfg_with_user
    )
    
    return signal


# =====================================================================
# MARKET CANDLES (FIXED)
# =====================================================================

@router.get("/market/candles")
async def get_candles(
    symbol: str = Query("BTCUSDT", description="Symbol: BTCUSDT, XAUUSD"),
    timeframe: str = Query("1m", description="Timeframe: 1m, 5m, 15m, 30m, 1h"),
    limit: int = Query(160, description="Number of candles", ge=10, le=500)
):
    """Get candles for a specific symbol"""
    try:
        # ✅ FIXED: symbol first, then timeframe, then limit
        candles = await market.get_klines(symbol, timeframe, limit)
        return {
            "symbol": symbol,
            "timeframe": timeframe,
            "provider": "coinbase",
            "candles": candles
        }
    except Exception as e:
        raise HTTPException(status_code=503, detail=f"Market data unavailable: {str(e)}")


# =====================================================================
# CLOSE TRADE
# =====================================================================

@router.post("/trades/{trade_id}/close")
async def close_trade(
    trade_id: str,
    request: Request
):
    """Close a paper trade"""
    user = await auth.require_subscription(request)
    
    # ✅ Find trade
    trade = await db.trades.find_one({
        "id": trade_id,
        "user_id": user["id"],
        "status": "OPEN"
    })
    
    if not trade:
        raise HTTPException(status_code=404, detail="Open trade not found")
    
    # ✅ Get current price
    symbol = trade.get("symbol", "BTCUSDT")
    price = await market.get_price(symbol)
    
    if not price:
        raise HTTPException(status_code=503, detail="Market price unavailable")
    
    # ✅ Close trade
    closed = await paper_trading.close_trade(
        trade=trade,
        price=price,
        reason="MANUAL CLOSE",
        explanation="User manually closed the position from dashboard"
    )
    
    return closed


# =====================================================================
# PRESENCE
# =====================================================================

@router.post("/presence")
async def presence(request: Request):
    """Update user presence (dashboard open)"""
    user = await auth.require_subscription(request)
    await paper_trading.touch_presence(user["id"])
    return {"status": "ok"}


# =====================================================================
# ENGINE RESET
# =====================================================================

@router.post("/engine/reset")
async def reset_engine(request: Request):
    """Reset paper trading account"""
    user = await auth.require_subscription(request)
    wallet = await paper_trading.reset_all(user["id"])
    return wallet


# =====================================================================
# ENGINE HEALTH
# =====================================================================

@router.get("/engine/health")
async def engine_health():
    """Get engine health status"""
    return paper_trading.health()


# =====================================================================
# SUPPORTED SYMBOLS
# =====================================================================

@router.get("/symbols")
async def get_symbols():
    """Get list of supported symbols"""
    return {
        "symbols": [
            {"symbol": "BTCUSDT", "display": "BTC/USD", "min_price": 10000, "max_price": 150000},
            {"symbol": "XAUUSD", "display": "XAU/USD", "min_price": 1500, "max_price": 3500},
        ]
    }