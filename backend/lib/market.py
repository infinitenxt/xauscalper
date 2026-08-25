"""Market data layer for gold — one consistent source for price, candles and strategy.

Provider chain (first reachable wins, checked on boot and every ``PROVIDER_TTL``):

1. ``binance-futures``       -> https://fapi.binance.com/fapi/v1   XAUUSDT  (real XAU/USD futures)
2. ``binance-futures-www``   -> https://www.binance.com/fapi/v1    XAUUSDT  (same market, mirror host
   that answers from regions where ``fapi`` returns HTTP 451)
3. ``binance-gold-proxy``    -> https://data-api.binance.vision/api/v3 PAXGUSDT (LAST RESORT proxy,
   labelled "PAXGUSDT GOLD PROXY" everywhere — it is *not* XAU/USD)

Hard rule: REST candles, the live WebSocket tick and the live forming candle all
come from the **same** provider symbol. Live data is tagged with the provider id
that produced it and is discarded the moment the active provider changes, so a
XAUUSDT price is never drawn on PAXGUSDT candles (or the reverse).

Live data is only reported as live while it is fresh (``STALE_AFTER`` seconds);
after that the feed is marked stale and REST takes over instead of showing an old
tick as if it were current.
"""
from __future__ import annotations

import asyncio
import json
import time
from contextlib import suppress
from typing import Any, Dict, List, Optional

import httpx
import websockets

INTERVALS = ["1m", "5m", "15m", "30m", "1h"]
INTERVAL_MINUTES = {"1m": 1, "5m": 5, "15m": 15, "30m": 30, "1h": 60}

BROWSER_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0 Safari/537.36"
)

PROVIDERS: List[Dict[str, Any]] = [
    {
        "id": "binance-futures",
        "base": "https://fapi.binance.com/fapi/v1",
        "symbol": "XAUUSDT",
        "display_symbol": "XAUUSDT",
        "label": "Binance Futures XAUUSDT",
        "kind": "futures",
        "ws": "wss://fstream.binance.com/stream?streams=",
        "ws_symbol": "xauusdt",
        "proxy": False,
        "note": "Live Binance Futures XAUUSDT — real XAU/USD gold market data.",
    },
    {
        "id": "binance-futures-www",
        "base": "https://www.binance.com/fapi/v1",
        "symbol": "XAUUSDT",
        "display_symbol": "XAUUSDT",
        "label": "Binance Futures XAUUSDT (mirror host)",
        "kind": "futures",
        "ws": "wss://fstream.binance.com/stream?streams=",
        "ws_symbol": "xauusdt",
        "proxy": False,
        "note": (
            "Real Binance Futures XAUUSDT data. History is read through Binance's "
            "www mirror because fapi.binance.com answers HTTP 451 from this region; "
            "the live WebSocket tick and candles are the same XAUUSDT market."
        ),
    },
    {
        "id": "binance-gold-proxy",
        "base": "https://data-api.binance.vision/api/v3",
        "symbol": "PAXGUSDT",
        "display_symbol": "PAXGUSDT GOLD PROXY",
        "label": "PAXGUSDT GOLD PROXY (not XAU/USD)",
        "kind": "spot",
        "ws": None,
        "ws_symbol": None,
        "proxy": True,
        "note": (
            "FALLBACK: XAUUSDT is unreachable, so this is PAXGUSDT — a 1oz "
            "gold-backed token used as a proxy. It tracks gold closely but it is "
            "NOT XAU/USD, and prices can differ by a few dollars."
        ),
    },
]

_client: Optional[httpx.AsyncClient] = None
_active: Optional[Dict[str, Any]] = None
_active_checked_at: float = 0.0
_probe_lock = asyncio.Lock()

_kline_cache: Dict[str, Any] = {}
_price_cache: Dict[str, Any] = {}

KLINE_TTL = 4.0
PRICE_TTL = 2.0
PROVIDER_TTL = 300.0
STALE_AFTER = 15.0  # a live tick older than this is no longer "live"

feed_status: Dict[str, Any] = {
    "provider_id": None,
    "provider_label": "connecting…",
    "symbol": None,
    "display_symbol": None,
    "kind": None,
    "degraded": False,
    "is_proxy": False,
    "note": "",
    "last_error": "",
    "last_update": None,
    "live_source": "rest",
    "ws_connected": False,
    "ws_reconnects": 0,
    "stale": True,
    "tick_age_seconds": None,
}

# ------------------------------------------------------------------ WebSocket
_ws_task: Optional[asyncio.Task] = None
_ws_running = False
_ws_provider_id: Optional[str] = None

_live_price: Optional[float] = None
_live_price_at: float = 0.0
_live_provider_id: Optional[str] = None
_live_candles: Dict[str, Dict[str, float]] = {}


def _provider_id() -> Optional[str]:
    return _active["id"] if _active else None


def _drop_live_data() -> None:
    """Live data from a different symbol must never mix with the active one."""
    global _live_price, _live_price_at, _live_provider_id
    _live_price = None
    _live_price_at = 0.0
    _live_provider_id = None
    _live_candles.clear()
    _price_cache.pop("last", None)


def _live_fresh() -> bool:
    return (
        _live_price is not None
        and _live_provider_id == _provider_id()
        and (time.time() - _live_price_at) < STALE_AFTER
    )


def _update_live_price(price: float, provider_id: Optional[str], source: str) -> None:
    global _live_price, _live_price_at, _live_provider_id
    _live_price = price
    _live_price_at = time.time()
    _live_provider_id = provider_id
    _price_cache["last"] = (time.time(), price)
    feed_status["live_source"] = source
    feed_status["stale"] = False
    feed_status["tick_age_seconds"] = 0.0
    feed_status["last_update"] = time.time()


def _update_live_candle(interval: str, k: Dict[str, Any], provider_id: str) -> None:
    if provider_id != _provider_id():
        return  # a stream from a provider we are no longer using

    candle = {
        "time": int(k["t"]),
        "open": float(k["o"]),
        "high": float(k["h"]),
        "low": float(k["l"]),
        "close": float(k["c"]),
        "volume": float(k["v"]),
        "close_time": int(k["T"]),
        "closed": bool(k["x"]),
    }
    _live_candles[interval] = candle

    # Only fold into the REST cache once the candle has closed.
    if candle["closed"]:
        for key, cached in list(_kline_cache.items()):
            if key.startswith(f"{interval}:"):
                candles = list(cached[1])
                if candles and candles[-1]["time"] == candle["time"]:
                    candles[-1] = candle
                else:
                    candles.append(candle)
                _kline_cache[key] = (time.time(), candles)


async def _websocket_loop(provider: Dict[str, Any]) -> None:
    """Stream trades + klines for exactly the active provider's symbol."""
    global _ws_running

    symbol = provider["ws_symbol"]
    streams = [f"{symbol}@trade"] + [f"{symbol}@kline_{tf}" for tf in INTERVALS]
    url = f"{provider['ws']}{'/'.join(streams)}"
    pid = provider["id"]
    _ws_running = True

    while _ws_running:
        try:
            async with websockets.connect(url, ping_interval=20, ping_timeout=20, close_timeout=5) as ws:
                feed_status["ws_connected"] = True
                feed_status["last_error"] = ""
                async for raw in ws:
                    if not _ws_running or pid != _provider_id():
                        break
                    try:
                        message = json.loads(raw)
                        stream = message.get("stream", "")
                        data = message.get("data", {})
                        if "@trade" in stream:
                            _update_live_price(float(data["p"]), pid, "websocket")
                        elif "@kline_" in stream:
                            kline = data.get("k")
                            if kline and kline.get("i") in INTERVALS:
                                _update_live_candle(str(kline["i"]), kline, pid)
                    except Exception as exc:  # noqa: BLE001 — one bad frame must not kill the feed
                        feed_status["last_error"] = f"websocket message: {exc}"
        except asyncio.CancelledError:
            feed_status["ws_connected"] = False
            raise
        except Exception as exc:  # noqa: BLE001
            feed_status["ws_connected"] = False
            feed_status["ws_reconnects"] = int(feed_status.get("ws_reconnects") or 0) + 1
            feed_status["last_error"] = f"websocket disconnected: {exc}"
            await asyncio.sleep(3)  # back off, then auto-reconnect

    feed_status["ws_connected"] = False
    _ws_running = False


async def _restart_websocket(provider: Dict[str, Any]) -> None:
    """(Re)bind the stream to the active provider. No stream for proxy providers."""
    global _ws_task, _ws_running, _ws_provider_id

    if _ws_provider_id == provider["id"] and _ws_task and not _ws_task.done():
        return

    await stop_websocket()
    _drop_live_data()
    _ws_provider_id = provider["id"]

    if not provider.get("ws"):
        feed_status["live_source"] = "rest"
        feed_status["ws_connected"] = False
        return

    _ws_task = asyncio.create_task(_websocket_loop(provider))


async def start_feed() -> None:
    """Boot the feed: pick a provider, then bind its WebSocket."""
    provider = await active_provider(force=True)
    await _restart_websocket(provider)


async def stop_websocket() -> None:
    global _ws_running, _ws_task
    _ws_running = False
    if _ws_task and not _ws_task.done():
        _ws_task.cancel()
        with suppress(asyncio.CancelledError):
            await _ws_task
    _ws_task = None


def _http() -> httpx.AsyncClient:
    global _client
    if _client is None:
        _client = httpx.AsyncClient(timeout=12.0, headers={"User-Agent": BROWSER_UA})
    return _client


async def close_http() -> None:
    global _client
    if _client is not None:
        await _client.aclose()
        _client = None


def _set_status(provider: Dict[str, Any], error: str = "") -> None:
    age = (time.time() - _live_price_at) if _live_price_at else None
    stale = not _live_fresh()
    feed_status.update(
        {
            "provider_id": provider["id"],
            "provider_label": provider["label"],
            "symbol": provider["symbol"],
            "display_symbol": provider["display_symbol"],
            "kind": provider["kind"],
            "degraded": provider["id"] != PROVIDERS[0]["id"],
            "is_proxy": bool(provider.get("proxy")),
            "note": provider["note"],
            "last_error": error or feed_status.get("last_error", ""),
            "stale": stale,
            "tick_age_seconds": round(age, 1) if age is not None else None,
            "live_source": "websocket" if _live_fresh() else "rest",
        }
    )


async def _try_provider(provider: Dict[str, Any]) -> bool:
    try:
        r = await _http().get(
            f"{provider['base']}/klines",
            params={"symbol": provider["symbol"], "interval": "1m", "limit": 2},
        )
        return r.status_code == 200 and isinstance(r.json(), list)
    except Exception:  # noqa: BLE001
        return False


async def active_provider(force: bool = False) -> Dict[str, Any]:
    """First reachable provider; cached for PROVIDER_TTL. Rebinds the stream on change."""
    global _active, _active_checked_at
    async with _probe_lock:
        fresh = _active is not None and (time.time() - _active_checked_at) < PROVIDER_TTL
        if fresh and not force:
            return _active  # type: ignore[return-value]

        previous = _active["id"] if _active else None
        last_error = ""
        chosen: Optional[Dict[str, Any]] = None
        for provider in PROVIDERS:
            if await _try_provider(provider):
                chosen = provider
                break
            last_error = f"{provider['id']} unreachable"

        if chosen is None:
            chosen = _active or PROVIDERS[-1]

        _active = chosen
        _active_checked_at = time.time()
        if previous and previous != chosen["id"]:
            _kline_cache.clear()
            _drop_live_data()
        _set_status(chosen, last_error if chosen is None else "")

    if previous != chosen["id"]:
        await _restart_websocket(chosen)
    return chosen


def _parse_klines(raw: List[List[Any]]) -> List[Dict[str, float]]:
    out: List[Dict[str, float]] = []
    for k in raw:
        out.append(
            {
                "time": int(k[0]),
                "open": float(k[1]),
                "high": float(k[2]),
                "low": float(k[3]),
                "close": float(k[4]),
                "volume": float(k[5]),
                "close_time": int(k[6]),
            }
        )
    return out


async def get_klines(interval: str, limit: int = 300) -> List[Dict[str, float]]:
    """Historical candles (cached) with the live forming candle appended."""
    if interval not in INTERVAL_MINUTES:
        interval = "15m"

    key = f"{interval}:{limit}"
    cached = _kline_cache.get(key)

    if not cached or (time.time() - cached[0]) >= KLINE_TTL:
        for force in (False, True):
            provider = await active_provider(force=force)
            try:
                r = await _http().get(
                    f"{provider['base']}/klines",
                    params={"symbol": provider["symbol"], "interval": interval, "limit": limit},
                )
                if r.status_code != 200:
                    raise RuntimeError(f"HTTP {r.status_code}")
                _kline_cache[key] = (time.time(), _parse_klines(r.json()))
                _set_status(provider)
                cached = _kline_cache[key]
                break
            except Exception as exc:  # noqa: BLE001
                feed_status["last_error"] = f"klines {interval}: {exc}"

    candles = list(cached[1]) if cached else []

    # Fold in the live forming candle — same provider only, and only while fresh.
    live = _live_candles.get(interval)
    if live and _live_provider_id == _provider_id() and (time.time() - _live_price_at) < STALE_AFTER:
        if candles and candles[-1]["time"] == live["time"]:
            candles[-1] = dict(live)
        elif not candles or live["time"] > candles[-1]["time"]:
            candles.append(dict(live))

    return candles[-limit:]


async def get_price() -> Optional[float]:
    """Live price. Never returns a stale tick as if it were live."""
    if _live_fresh():
        feed_status["tick_age_seconds"] = round(time.time() - _live_price_at, 1)
        feed_status["stale"] = False
        return _live_price

    cached = _price_cache.get("last")
    if cached and (time.time() - cached[0]) < PRICE_TTL:
        return cached[1]

    provider = await active_provider()
    try:
        r = await _http().get(
            f"{provider['base']}/ticker/price", params={"symbol": provider["symbol"]}
        )
        r.raise_for_status()
        price = float(r.json()["price"])
        _update_live_price(price, provider["id"], "rest")
        _set_status(provider)
        return price
    except Exception as exc:  # noqa: BLE001
        feed_status["last_error"] = f"price: {exc}"
        candles = await get_klines("1m", 2)
        if candles:
            return candles[-1]["close"]
        return cached[1] if cached else None


async def get_stats_24h() -> Dict[str, float]:
    """24h change / high / low / volume for the ticker bar."""
    candles = await get_klines("1h", 25)
    if not candles:
        return {}
    first_open = candles[0]["open"]
    last_close = candles[-1]["close"]
    return {
        "open_24h": first_open,
        "high_24h": max(c["high"] for c in candles),
        "low_24h": min(c["low"] for c in candles),
        "volume_24h": sum(c["volume"] for c in candles),
        "change_24h": last_close - first_open,
        "change_pct_24h": ((last_close - first_open) / first_open * 100) if first_open else 0.0,
    }


def websocket_health() -> Dict[str, Any]:
    return {
        "running": bool(_ws_task and not _ws_task.done()),
        "connected": bool(feed_status.get("ws_connected")),
        "provider_id": _ws_provider_id,
        "last_price": _live_price if _live_fresh() else None,
        "tick_age_seconds": round(time.time() - _live_price_at, 1) if _live_price_at else None,
        "reconnects": feed_status.get("ws_reconnects", 0),
        "error": feed_status.get("last_error", ""),
    }


# Back-compat with the previous boot API.
def start_websocket() -> None:
    asyncio.create_task(start_feed())
