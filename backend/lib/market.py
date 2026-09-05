"""Multi-Symbol Market Data Layer - Coinbase + Bybit

Supported Symbols:
- BTCUSDT → Coinbase (BTC-USD)
- XAUUSD → Bybit (XAUUSDT)

Features:
- Per-symbol provider routing
- Live WebSocket price per symbol
- Live forming candles per symbol
- REST candle fallback
- REST price fallback
- Stale tick protection
- Automatic WebSocket reconnect
- Cached REST requests
"""

from __future__ import annotations

import asyncio
import json
import os
import time
from contextlib import suppress
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from typing import Any, Dict, List, Optional

import httpx
import websockets


# ---------------------------------------------------------------------------
# Market configuration - Multi-Provider
# ---------------------------------------------------------------------------

INTERVALS = ["1m", "5m", "15m", "30m", "1h"]

INTERVAL_MINUTES = {
    "1m": 1,
    "5m": 5,
    "15m": 15,
    "30m": 30,
    "1h": 60,
}

# ✅ Define supported symbols with provider routing
SUPPORTED_SYMBOLS = {
    "BTCUSDT": {
        "provider": "binance",
        "product_id": "BTCUSDT",
        "display": "BTCUSDT",
        "min_price": 10000,
        "max_price": 150000,
        "point": 0.01,
        "digits": 2,
        "rest_base": "https://data-api.binance.vision/api/v3",
        "candles_path": "/klines",
        "price_path": "/ticker/price",
        "stats_path": "/ticker/24hr",
        "granularity_map": {
            "1m": "1m",
            "5m": "5m",
            "15m": "15m",
            "30m": "30m",
            "1h": "1h",
        },
        "granularity_seconds": {
            "1m": 60,
            "5m": 300,
            "15m": 900,
            "30m": 1800,
            "1h": 3600,
        }
    },
    "XAUUSD": {
        "provider": "binance",
        "product_id": "PAXGUSDT",
        "display": "XAUUSD",
        "min_price": 1000,
        "max_price": 6000,
        "point": 0.01,
        "digits": 2,
        # Binance spot data mirror (api.binance.com is geo-blocked / 451 from this
        # region; the public data mirror is reachable and needs no API key). PAXGUSDT
        # is PAX Gold — a 1oz-gold-backed spot token priced ~= XAU/oz. REST-only.
        "rest_base": "https://data-api.binance.vision/api/v3",
        "candles_path": "/klines",
        "price_path": "/ticker/price",
        "stats_path": "/ticker/24hr",
        "granularity_map": {
            "1m": "1m",
            "5m": "5m",
            "15m": "15m",
            "30m": "30m",
            "1h": "1h",
        },
        "granularity_seconds": {
            "1m": 60,
            "5m": 300,
            "15m": 900,
            "30m": 1800,
            "1h": 3600,
        }
    }
}

# ✅ Default symbol from env
DEFAULT_SYMBOL = os.getenv("DEFAULT_SYMBOL", "BTCUSDT")

BROWSER_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/124.0 Safari/537.36"
)

KLINE_TTL = 4.0
PRICE_TTL = 2.0
STALE_AFTER = 15.0

PROVIDER_ID = "multi"
PROVIDER_LABEL = "Multi-Provider"

# ---------------------------------------------------------------------------
# Per-symbol state
# ---------------------------------------------------------------------------

_symbol_data: Dict[str, Dict[str, Any]] = {}
_ws_tasks: Dict[str, asyncio.Task] = {}
_ws_running: Dict[str, bool] = {}

_kline_cache: Dict[str, Dict[str, Any]] = {}
_price_cache: Dict[str, Dict[str, Any]] = {}
_depth_cache: Dict[str, tuple[float, Dict[str, Any]]] = {}
_depth_last_persist: Dict[str, float] = {}
_depth_lock = asyncio.Lock()

_live_price: Dict[str, Optional[float]] = {}
_live_price_at: Dict[str, float] = {}
_live_candles: Dict[str, Dict[str, Dict[str, Any]]] = {}


# ---------------------------------------------------------------------------
# HTTP client
# ---------------------------------------------------------------------------

_client: Optional[httpx.AsyncClient] = None


def _http() -> httpx.AsyncClient:
    global _client
    if _client is None:
        _client = httpx.AsyncClient(
            timeout=12.0,
            headers={"User-Agent": BROWSER_UA},
        )
    return _client


async def close_http() -> None:
    global _client
    if _client is not None:
        await _client.aclose()
        _client = None


def _neutral_order_book(symbol: str, error: str = "") -> Dict[str, Any]:
    return {
        "symbol": symbol,
        "provider_symbol": get_product_id(symbol),
        "stale": True,
        "imbalance": 0.0,
        "near_imbalance": 0.0,
        "spread_bps": None,
        "bid_notional": 0.0,
        "ask_notional": 0.0,
        "near_bid_notional": 0.0,
        "near_ask_notional": 0.0,
        "bids": [],
        "asks": [],
        "captured_at": datetime.now(timezone.utc),
        "error": error,
    }


async def get_order_book(symbol: str, limit: int = 20) -> Dict[str, Any]:
    """Return validated Binance depth metrics; failures are neutral, never blocking."""
    symbol = symbol.upper()
    info = SUPPORTED_SYMBOLS.get(symbol)
    if not info or info.get("provider") != "binance":
        return _neutral_order_book(symbol, "order book unavailable for this provider")

    now_mono = time.time()
    cached = _depth_cache.get(symbol)
    if cached and now_mono - cached[0] < 3.0:
        return dict(cached[1])

    async with _depth_lock:
        cached = _depth_cache.get(symbol)
        if cached and time.time() - cached[0] < 3.0:
            return dict(cached[1])
        try:
            endpoint = f"{info['rest_base']}/depth"
            raw = await _rest_get(endpoint, {"symbol": info["product_id"], "limit": min(20, max(5, limit))})
            if not isinstance(raw, dict):
                raise ValueError("invalid depth payload")

            def parse_levels(value: Any) -> List[List[float]]:
                if not isinstance(value, list):
                    raise ValueError("invalid depth levels")
                parsed: List[List[float]] = []
                for level in value[:20]:
                    if not isinstance(level, list) or len(level) < 2:
                        raise ValueError("invalid depth level")
                    try:
                        price = Decimal(str(level[0]))
                        quantity = Decimal(str(level[1]))
                    except (InvalidOperation, ValueError) as exc:
                        raise ValueError("invalid depth decimal") from exc
                    if price <= 0 or quantity <= 0:
                        raise ValueError("non-positive depth level")
                    parsed.append([float(price), float(quantity)])
                return parsed

            bids = parse_levels(raw.get("bids"))
            asks = parse_levels(raw.get("asks"))
            if not bids or not asks or asks[0][0] < bids[0][0]:
                raise ValueError("invalid two-sided order book")

            bid_notional = sum(price * quantity for price, quantity in bids)
            ask_notional = sum(price * quantity for price, quantity in asks)
            total = bid_notional + ask_notional
            imbalance = (bid_notional - ask_notional) / total if total else 0.0
            best_bid, best_ask = bids[0][0], asks[0][0]
            mid = (best_bid + best_ask) / 2
            spread_bps = (best_ask - best_bid) / mid * 10_000 if mid else None
            near_band = 0.001
            near_bid = sum(p * q for p, q in bids if p >= mid * (1 - near_band))
            near_ask = sum(p * q for p, q in asks if p <= mid * (1 + near_band))
            near_total = near_bid + near_ask
            near_imbalance = (near_bid - near_ask) / near_total if near_total else 0.0
            captured_at = datetime.now(timezone.utc)
            result = {
                "symbol": symbol,
                "provider_symbol": info["product_id"],
                "last_update_id": int(raw.get("lastUpdateId") or 0),
                "stale": False,
                "imbalance": round(imbalance, 6),
                "near_imbalance": round(near_imbalance, 6),
                "spread_bps": round(spread_bps, 4) if spread_bps is not None else None,
                "bid_notional": round(bid_notional, 2),
                "ask_notional": round(ask_notional, 2),
                "near_bid_notional": round(near_bid, 2),
                "near_ask_notional": round(near_ask, 2),
                "bids": bids[:10],
                "asks": asks[:10],
                "captured_at": captured_at,
                "error": "",
            }
            _depth_cache[symbol] = (time.time(), result)

            if time.time() - _depth_last_persist.get(symbol, 0.0) >= 30.0:
                from lib.db import db
                await db.order_book_snapshots.insert_one(dict(result))
                _depth_last_persist[symbol] = time.time()
            return dict(result)
        except Exception as exc:
            result = _neutral_order_book(symbol, f"depth unavailable: {type(exc).__name__}")
            _depth_cache[symbol] = (time.time(), result)
            return result


# ---------------------------------------------------------------------------
# Symbol helpers
# ---------------------------------------------------------------------------

def get_provider(symbol: str) -> str:
    """Get provider for a symbol"""
    info = SUPPORTED_SYMBOLS.get(symbol, {})
    return info.get("provider", "coinbase")


def get_product_id(symbol: str) -> str:
    """Get product ID for a symbol"""
    info = SUPPORTED_SYMBOLS.get(symbol, {})
    return info.get("product_id", f"{symbol}-USD")


def get_display_symbol(symbol: str) -> str:
    """Get display symbol"""
    info = SUPPORTED_SYMBOLS.get(symbol, {})
    return info.get("display", symbol)


def get_symbol_info(symbol: str) -> Dict[str, Any]:
    """Get symbol configuration"""
    return SUPPORTED_SYMBOLS.get(symbol, {})


def get_feed_status(symbol: str = None) -> Dict[str, Any]:
    """Get feed status for a symbol"""
    symbol = symbol or DEFAULT_SYMBOL
    return _symbol_data.get(symbol, {
        "symbol": symbol,
        "display_symbol": get_display_symbol(symbol),
        "provider": get_provider(symbol),
        "ws_connected": False,
        "stale": True,
        "last_error": "",
        "last_price": None,
        "tick_age_seconds": None,
    })


# ---------------------------------------------------------------------------
# Per-symbol data helpers
# ---------------------------------------------------------------------------

def _init_symbol(symbol: str) -> None:
    """Initialize state for a symbol"""
    if symbol not in _symbol_data:
        _symbol_data[symbol] = {
            "symbol": symbol,
            "display_symbol": get_display_symbol(symbol),
            "provider": get_provider(symbol),
            "ws_connected": False,
            "stale": True,
            "last_error": "",
            "last_price": None,
            "tick_age_seconds": None,
            "last_update": None,
        }
    if symbol not in _live_price:
        _live_price[symbol] = None
        _live_price_at[symbol] = 0.0
    if symbol not in _live_candles:
        _live_candles[symbol] = {}


def _drop_live_data(symbol: str) -> None:
    _init_symbol(symbol)
    _live_price[symbol] = None
    _live_price_at[symbol] = 0.0
    _live_candles[symbol] = {}
    _price_cache.pop(symbol, None)


def _live_fresh(symbol: str) -> bool:
    _init_symbol(symbol)
    return bool(
        _live_price[symbol] is not None
        and (time.time() - _live_price_at[symbol]) < STALE_AFTER
    )


def _update_live_price(symbol: str, price: float, source: str) -> None:
    _init_symbol(symbol)
    _live_price[symbol] = price
    _live_price_at[symbol] = time.time()
    
    _price_cache[symbol] = (time.time(), price)
    
    status = _symbol_data[symbol]
    status["last_price"] = price
    status["stale"] = False
    status["tick_age_seconds"] = 0.0
    status["last_update"] = time.time()


def _update_live_candle(symbol: str, interval: str, candle_data: Dict[str, Any]) -> None:
    _init_symbol(symbol)
    candle = {
        "time": int(candle_data.get("start", candle_data.get("t", 0))),
        "open": float(candle_data.get("open", candle_data.get("o", 0))),
        "high": float(candle_data.get("high", candle_data.get("h", 0))),
        "low": float(candle_data.get("low", candle_data.get("l", 0))),
        "close": float(candle_data.get("close", candle_data.get("c", 0))),
        "volume": float(candle_data.get("volume", candle_data.get("v", 0))),
        "close_time": int(candle_data.get("close_time", candle_data.get("T", 0))),
        "closed": candle_data.get("closed", candle_data.get("x", False)),
    }
    _live_candles[symbol][interval] = candle


# ---------------------------------------------------------------------------
# WebSocket - Multi-Provider
# ---------------------------------------------------------------------------

async def _websocket_loop(symbol: str) -> None:
    """WebSocket loop for a specific symbol"""
    info = SUPPORTED_SYMBOLS.get(symbol, {})
    provider = info.get("provider", "coinbase")
    product_id = info.get("product_id", f"{symbol}-USD")
    ws_base = info.get("ws_base")
    
    if not ws_base:
        return
    
    _ws_running[symbol] = True
    
    while _ws_running.get(symbol, False):
        try:
            async with websockets.connect(
                ws_base,
                ping_interval=20,
                ping_timeout=20,
                close_timeout=5,
            ) as ws:
                if provider == "coinbase":
                    subscribe_msg = {
                        "type": "subscribe",
                        "product_ids": [product_id],
                        "channel": "ticker"
                    }
                elif provider == "bybit":
                    subscribe_msg = {
                        "op": "subscribe",
                        "args": [f"ticker.{product_id}"]
                    }
                else:
                    break
                
                await ws.send(json.dumps(subscribe_msg))
                
                status = _symbol_data[symbol]
                status["ws_connected"] = True
                status["last_error"] = ""
                
                async for raw in ws:
                    if not _ws_running.get(symbol, False):
                        break
                    
                    try:
                        message = json.loads(raw)
                        
                        if provider == "coinbase":
                            msg_type = message.get("type", "")
                            if msg_type == "ticker":
                                price = float(message.get("price", 0))
                                if price > 0:
                                    _update_live_price(symbol, price, "websocket")
                            elif msg_type == "candle":
                                candles = message.get("candles", [])
                                for c in candles:
                                    interval = str(c.get("interval", "1m"))
                                    if interval in INTERVALS:
                                        _update_live_candle(symbol, interval, c)
                        
                        elif provider == "bybit":
                            topic = message.get("topic", "")
                            data = message.get("data", {})
                            
                            if "ticker." in topic:
                                price = float(data.get("lastPrice", 0))
                                if price > 0:
                                    _update_live_price(symbol, price, "websocket")
                                    
                    except Exception as exc:
                        status["last_error"] = f"websocket message: {exc}"
                        
        except asyncio.CancelledError:
            status = _symbol_data.get(symbol, {})
            status["ws_connected"] = False
            raise
            
        except Exception as exc:
            status = _symbol_data.get(symbol, {})
            status["ws_connected"] = False
            status["last_error"] = f"websocket disconnected: {exc}"
            await asyncio.sleep(3)
    
    status = _symbol_data.get(symbol, {})
    status["ws_connected"] = False
    _ws_running[symbol] = False


async def start_feed(symbol: str = None) -> None:
    """Start WebSocket feed for a symbol"""
    symbol = symbol or DEFAULT_SYMBOL
    _init_symbol(symbol)
    
    if symbol in _ws_tasks and not _ws_tasks[symbol].done():
        return
    
    _drop_live_data(symbol)
    _ws_tasks[symbol] = asyncio.create_task(_websocket_loop(symbol))


async def start_all_feeds() -> None:
    """Start WebSocket feeds for all supported symbols"""
    for symbol in SUPPORTED_SYMBOLS:
        await start_feed(symbol)


async def stop_websocket(symbol: str = None) -> None:
    """Stop WebSocket for a symbol"""
    symbol = symbol or DEFAULT_SYMBOL
    _ws_running[symbol] = False
    
    if symbol in _ws_tasks and not _ws_tasks[symbol].done():
        _ws_tasks[symbol].cancel()
        with suppress(asyncio.CancelledError):
            await _ws_tasks[symbol]
    
    _ws_tasks.pop(symbol, None)
    status = _symbol_data.get(symbol, {})
    status["ws_connected"] = False


# ---------------------------------------------------------------------------
# REST helpers
# ---------------------------------------------------------------------------

def _set_status(symbol: str, error: str = "") -> None:
    _init_symbol(symbol)
    age = time.time() - _live_price_at[symbol] if _live_price_at.get(symbol) else None
    stale = not _live_fresh(symbol)
    
    status = _symbol_data[symbol]
    status["stale"] = stale
    status["tick_age_seconds"] = round(age, 1) if age is not None else None
    if error:
        status["last_error"] = error


async def _rest_get(url: str, params: Optional[Dict[str, Any]] = None) -> Any:
    response = await _http().get(url, params=params or {})
    response.raise_for_status()
    return response.json()


# ---------------------------------------------------------------------------
# Candles - Multi-Provider
# ---------------------------------------------------------------------------

async def get_klines(
    symbol: str,
    interval: str,
    limit: int = 300,
) -> List[Dict[str, Any]]:
    """Get candles for a specific symbol from its provider"""
    symbol = symbol or DEFAULT_SYMBOL
    _init_symbol(symbol)
    
    if interval not in INTERVAL_MINUTES:
        interval = "15m"
    
    info = SUPPORTED_SYMBOLS.get(symbol, {})
    provider = info.get("provider", "coinbase")
    
    cache_key = f"{symbol}:{interval}:{limit}"
    cached = _kline_cache.get(cache_key)
    
    if cached and (time.time() - cached[0]) < KLINE_TTL:
        return list(cached[1])
    
    try:
        if provider == "coinbase":
            candles = await _get_coinbase_klines(symbol, interval, limit, info)
        elif provider == "bybit":
            candles = await _get_bybit_klines(symbol, interval, limit, info)
        elif provider == "binance":
            candles = await _get_binance_klines(symbol, interval, limit, info)
        else:
            return []
        
        _kline_cache[cache_key] = (time.time(), candles)
        _set_status(symbol)
        return candles[-limit:]
        
    except Exception as exc:
        _set_status(symbol, f"klines {interval}: {exc}")
        return list(cached[1]) if cached else []


async def _get_coinbase_klines(symbol: str, interval: str, limit: int, info: Dict) -> List[Dict]:
    """Fetch candles from Coinbase"""
    product_id = info.get("product_id", f"{symbol}-USD")
    granularity = info["granularity_map"].get(interval, "FIFTEEN_MINUTE")
    granularity_seconds = info["granularity_seconds"].get(interval, 900)
    rest_base = info.get("rest_base", "https://api.coinbase.com/api/v3")
    
    now = int(time.time())
    start = now - (limit * granularity_seconds)
    
    params = {
        "granularity": granularity,
        "start": start,
        "end": now,
    }
    
    candles_endpoint = f"{rest_base}{info['candles_path']}"
    raw = await _rest_get(candles_endpoint, params)
    
    result = raw.get("candles", [])
    candles = []
    for c in result:
        candles.append({
            "time": int(c["start"]),
            "open": float(c["open"]),
            "high": float(c["high"]),
            "low": float(c["low"]),
            "close": float(c["close"]),
            "volume": float(c["volume"]),
            "close_time": int(c["start"]) + granularity_seconds,
        })
    candles.reverse()
    return candles


async def _get_bybit_klines(symbol: str, interval: str, limit: int, info: Dict) -> List[Dict]:
    """Fetch candles from Bybit"""
    product_id = info.get("product_id", "XAUUSDT")
    granularity = info["granularity_map"].get(interval, "1")
    granularity_seconds = info["granularity_seconds"].get(interval, 60)
    rest_base = info.get("rest_base", "https://api.bybit.com/v5")
    category = info.get("category", "spot")
    
    params = {
        "category": category,
        "symbol": product_id,
        "interval": granularity,
        "limit": limit,
    }
    
    raw = await _rest_get(f"{rest_base}{info['candles_path']}", params)
    
    if raw.get("retCode") != 0:
        return []
    
    candles = []
    for k in raw.get("result", {}).get("list", []):
        candles.append({
            "time": int(k[0]),
            "open": float(k[1]),
            "high": float(k[2]),
            "low": float(k[3]),
            "close": float(k[4]),
            "volume": float(k[5]),
            "close_time": int(k[0]) + granularity_seconds,
        })
    candles.reverse()
    return candles


async def _get_binance_klines(symbol: str, interval: str, limit: int, info: Dict) -> List[Dict]:
    """Fetch candles from the Binance public spot data mirror (REST, no key)."""
    product_id = info.get("product_id", "PAXGUSDT")
    binance_interval = info["granularity_map"].get(interval, "1m")
    granularity_seconds = info["granularity_seconds"].get(interval, 60)
    rest_base = info.get("rest_base", "https://data-api.binance.vision/api/v3")

    params = {
        "symbol": product_id,
        "interval": binance_interval,
        "limit": min(int(limit), 1000),
    }

    raw = await _rest_get(f"{rest_base}{info['candles_path']}", params)
    if not isinstance(raw, list):
        return []

    # Binance kline: [openTime(ms), open, high, low, close, volume, closeTime(ms), ...]
    candles = []
    for k in raw:
        open_sec = int(k[0]) // 1000  # seconds, to match the coinbase path
        candles.append({
            "time": open_sec,
            "open": float(k[1]),
            "high": float(k[2]),
            "low": float(k[3]),
            "close": float(k[4]),
            "volume": float(k[5]),
            "close_time": open_sec + granularity_seconds,
        })
    # Binance already returns oldest -> newest, which is the app's expected order.
    return candles


# ---------------------------------------------------------------------------
# Price - Multi-Provider
# ---------------------------------------------------------------------------

async def get_price(symbol: str = None) -> Optional[float]:
    """Get price for a specific symbol"""
    symbol = symbol or DEFAULT_SYMBOL
    _init_symbol(symbol)
    
    if _live_fresh(symbol):
        return _live_price[symbol]
    
    cached = _price_cache.get(symbol)
    if cached and (time.time() - cached[0]) < PRICE_TTL:
        return cached[1]
    
    info = SUPPORTED_SYMBOLS.get(symbol, {})
    provider = info.get("provider", "coinbase")
    
    try:
        if provider == "coinbase":
            price = await _get_coinbase_price(symbol, info)
        elif provider == "bybit":
            price = await _get_bybit_price(symbol, info)
        elif provider == "binance":
            price = await _get_binance_price(symbol, info)
        else:
            return None
        
        if price and price > 0:
            _update_live_price(symbol, price, "rest")
            _set_status(symbol)
            return price
        return None
        
    except Exception as exc:
        _set_status(symbol, f"price: {exc}")
        candles = await get_klines(symbol, "1m", 2)
        if candles:
            return candles[-1]["close"]
        if cached:
            return cached[1]
        return None


async def _get_coinbase_price(symbol: str, info: Dict) -> Optional[float]:
    """Fetch price from Coinbase"""
    product_id = info.get("product_id", f"{symbol}-USD")
    rest_base = info.get("rest_base", "https://api.coinbase.com/api/v3")
    
    endpoint = f"{rest_base}{info['price_path']}"
    data = await _rest_get(endpoint)
    trades = data.get("trades", [])
    if trades and len(trades) > 0:
        return float(trades[0].get("price", 0))
    return None


async def _get_bybit_price(symbol: str, info: Dict) -> Optional[float]:
    """Fetch price from Bybit"""
    product_id = info.get("product_id", "XAUUSDT")
    rest_base = info.get("rest_base", "https://api.bybit.com/v5")
    category = info.get("category", "spot")
    
    params = {
        "category": category,
        "symbol": product_id,
    }
    
    data = await _rest_get(f"{rest_base}{info['price_path']}", params)
    
    if data.get("retCode") != 0:
        return None
    
    tickers = data.get("result", {}).get("list", [])
    if tickers:
        return float(tickers[0].get("lastPrice", 0))
    return None


async def _get_binance_price(symbol: str, info: Dict) -> Optional[float]:
    """Fetch price from the Binance public spot data mirror."""
    product_id = info.get("product_id", "PAXGUSDT")
    rest_base = info.get("rest_base", "https://data-api.binance.vision/api/v3")

    data = await _rest_get(f"{rest_base}{info['price_path']}", {"symbol": product_id})
    price = float(data.get("price", 0)) if isinstance(data, dict) else 0.0
    return price or None


# ---------------------------------------------------------------------------
# Stats - Multi-Provider
# ---------------------------------------------------------------------------

async def get_stats_24h(symbol: str = None) -> Dict[str, float]:
    """Get 24h stats for a specific symbol"""
    symbol = symbol or DEFAULT_SYMBOL
    info = SUPPORTED_SYMBOLS.get(symbol, {})
    provider = info.get("provider", "coinbase")
    
    try:
        if provider == "coinbase":
            return await _get_coinbase_stats(symbol, info)
        elif provider == "bybit":
            return await _get_bybit_stats(symbol, info)
        elif provider == "binance":
            return await _get_binance_stats(symbol, info)
        return {}
        
    except Exception as exc:
        _set_status(symbol, f"stats: {exc}")
        return {}


async def _get_coinbase_stats(symbol: str, info: Dict) -> Dict[str, float]:
    """Fetch stats from Coinbase"""
    product_id = info.get("product_id", f"{symbol}-USD")
    rest_base = info.get("rest_base", "https://api.coinbase.com/api/v3")
    
    endpoint = f"{rest_base}{info['stats_path']}"
    data = await _rest_get(endpoint)
    product = data.get("product", {})
    
    candles = await get_klines(symbol, "1h", 25)
    if candles:
        first_open = candles[0]["open"]
        last_close = candles[-1]["close"]
        high = max(c["high"] for c in candles)
        low = min(c["low"] for c in candles)
        volume = sum(c["volume"] for c in candles)
        
        return {
            "open_24h": first_open,
            "high_24h": high,
            "low_24h": low,
            "volume_24h": volume,
            "change_24h": last_close - first_open,
            "change_pct_24h": ((last_close - first_open) / first_open * 100) if first_open else 0.0,
        }
    
    return {
        "open_24h": float(product.get("open", 0)),
        "high_24h": float(product.get("high", 0)),
        "low_24h": float(product.get("low", 0)),
        "volume_24h": float(product.get("volume", 0)),
        "change_24h": float(product.get("price_percentage_change_24h", 0)) / 100,
        "change_pct_24h": float(product.get("price_percentage_change_24h", 0)),
    }


async def _get_bybit_stats(symbol: str, info: Dict) -> Dict[str, float]:
    """Fetch stats from Bybit"""
    product_id = info.get("product_id", "XAUUSDT")
    rest_base = info.get("rest_base", "https://api.bybit.com/v5")
    category = info.get("category", "spot")
    
    params = {
        "category": category,
        "symbol": product_id,
    }
    
    data = await _rest_get(f"{rest_base}{info['stats_path']}", params)
    
    if data.get("retCode") != 0:
        return {}
    
    tickers = data.get("result", {}).get("list", [])
    if not tickers:
        return {}
    
    ticker = tickers[0]
    return {
        "open_24h": float(ticker.get("prevPrice24h", 0)),
        "high_24h": float(ticker.get("highPrice24h", 0)),
        "low_24h": float(ticker.get("lowPrice24h", 0)),
        "volume_24h": float(ticker.get("volume24h", 0)),
        "change_24h": float(ticker.get("price24hPcnt", 0)) * 100,
        "change_pct_24h": float(ticker.get("price24hPcnt", 0)) * 100,
    }


async def _get_binance_stats(symbol: str, info: Dict) -> Dict[str, float]:
    """Fetch 24h stats from the Binance public spot data mirror."""
    product_id = info.get("product_id", "PAXGUSDT")
    rest_base = info.get("rest_base", "https://data-api.binance.vision/api/v3")

    data = await _rest_get(f"{rest_base}{info['stats_path']}", {"symbol": product_id})
    if not isinstance(data, dict):
        return {}

    return {
        "open_24h": float(data.get("openPrice", 0)),
        "high_24h": float(data.get("highPrice", 0)),
        "low_24h": float(data.get("lowPrice", 0)),
        "volume_24h": float(data.get("volume", 0)),
        "change_24h": float(data.get("priceChange", 0)),
        "change_pct_24h": float(data.get("priceChangePercent", 0)),
    }


# ---------------------------------------------------------------------------
# Provider Info
# ---------------------------------------------------------------------------

async def active_provider(symbol: str = None) -> Dict[str, Any]:
    """Get active provider info"""
    symbol = symbol or DEFAULT_SYMBOL
    return {
        "provider_id": get_provider(symbol),
        "provider_label": f"{get_provider(symbol).title()} {get_display_symbol(symbol)}",
        "symbol": symbol,
        "display_symbol": get_display_symbol(symbol),
        "kind": "spot",
        "status": "active",
        "reachable": True,
        "last_check": time.time(),
    }


async def test_rest(symbol: str = None) -> Dict[str, Any]:
    """Test REST API connectivity"""
    symbol = symbol or DEFAULT_SYMBOL
    try:
        price = await get_price(symbol)
        return {
            "status": "ok",
            "provider": get_provider(symbol),
            "symbol": symbol,
            "price": price,
            "timestamp": time.time(),
        }
    except Exception as exc:
        return {
            "status": "error",
            "provider": get_provider(symbol),
            "symbol": symbol,
            "error": str(exc),
            "timestamp": time.time(),
        }


# ---------------------------------------------------------------------------
# Backward compatibility
# ---------------------------------------------------------------------------

SYMBOL = DEFAULT_SYMBOL
DISPLAY_SYMBOL = get_display_symbol(SYMBOL)

feed_status = get_feed_status(SYMBOL)


def start_websocket() -> None:
    """Start WebSocket for default symbol (backward compatibility)"""
    asyncio.create_task(start_feed(DEFAULT_SYMBOL))