"""Market data routes — multi-symbol support"""

import time  # ✅ ADDED
from fastapi import APIRouter, Query, HTTPException
from typing import List, Optional

from lib import market

router = APIRouter(tags=["market"])


# =====================================================================
# CANDLES
# =====================================================================

@router.get("/market/candles")
async def get_candles(
    symbol: str = Query("BTCUSDT", description="Symbol: BTCUSDT, XAUUSD"),
    timeframe: str = Query("1m", description="Timeframe: 1m, 5m, 15m, 30m, 1h"),
    limit: int = Query(160, description="Number of candles", ge=10, le=500)
):
    """Get candles for a specific symbol"""
    try:
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
# PRICE
# =====================================================================

@router.get("/market/price")
async def get_price(
    symbol: str = Query("BTCUSDT", description="Symbol: BTCUSDT, XAUUSD")
):
    """Get current price for a specific symbol"""
    try:
        price = await market.get_price(symbol)
        if price is None:
            raise HTTPException(status_code=503, detail="Price unavailable")
        return {
            "symbol": symbol,
            "price": price,
            "timestamp": int(time.time())  # ✅ time imported
        }
    except Exception as e:
        raise HTTPException(status_code=503, detail=f"Price unavailable: {str(e)}")


# =====================================================================
# STATS
# =====================================================================

@router.get("/market/stats")
async def get_stats(
    symbol: str = Query("BTCUSDT", description="Symbol: BTCUSDT, XAUUSD")
):
    """Get 24h stats for a specific symbol"""
    try:
        stats = await market.get_stats_24h(symbol)
        return {
            "symbol": symbol,
            **stats
        }
    except Exception as e:
        raise HTTPException(status_code=503, detail=f"Stats unavailable: {str(e)}")


# =====================================================================
# FEED STATUS
# =====================================================================

@router.get("/market/feed")
async def get_feed(
    symbol: str = Query("BTCUSDT", description="Symbol: BTCUSDT, XAUUSD")
):
    """Get feed status for a specific symbol"""
    return market.get_feed_status(symbol)


# =====================================================================
# SUPPORTED SYMBOLS
# =====================================================================

@router.get("/market/symbols")
async def get_supported_symbols():
    """Get list of supported symbols"""
    return {
        "symbols": [
            {
                "symbol": "BTCUSDT",
                "display": "BTC/USD",
                "coinbase": "BTC-USD",
                "min_price": 10000,
                "max_price": 150000,
                "digits": 2,
                "point": 0.01,
            },
            {
                "symbol": "XAUUSD",
                "display": "XAU/USD",
                "coinbase": "XAU-USD",
                "min_price": 1500,
                "max_price": 3500,
                "digits": 2,
                "point": 0.01,
            }
        ]
    }


# =====================================================================
# HEALTH
# =====================================================================

@router.get("/market/health")
async def market_health():
    """Get market health status"""
    return {
        "status": "ok",
        "provider": "coinbase",
        "symbols": list(market.SUPPORTED_SYMBOLS.keys()),
        "websocket": market._ws_tasks
    }