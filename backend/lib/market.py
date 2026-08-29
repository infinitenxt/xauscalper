"""Live BTC market data layer.

Source:
- Binance Futures BTCUSDT

REST and WebSocket data always use the same BTCUSDT market.

Features:
- Live WebSocket price
- Live forming candles
- REST candle fallback
- REST price fallback
- Stale tick protection
- Automatic WebSocket reconnect
- Cached REST requests
- 24/7 BTC market
"""

from __future__ import annotations

import asyncio
import json
import time
from contextlib import suppress
from typing import Any, Dict, List, Optional

import httpx
import websockets


# ---------------------------------------------------------------------------
# Market configuration
# ---------------------------------------------------------------------------

INTERVALS = ["1m", "5m", "15m", "30m", "1h"]

INTERVAL_MINUTES = {
    "1m": 1,
    "5m": 5,
    "15m": 15,
    "30m": 30,
    "1h": 60,
}

SYMBOL = "BTCUSDT"
DISPLAY_SYMBOL = "BTCUSDT"

REST_BASE = "https://fapi.binance.com/fapi/v1"
WS_BASE = "wss://fstream.binance.com/stream?streams="

BROWSER_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/124.0 Safari/537.36"
)

KLINE_TTL = 4.0
PRICE_TTL = 2.0
STALE_AFTER = 15.0


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


# ---------------------------------------------------------------------------
# Caches
# ---------------------------------------------------------------------------

_kline_cache: Dict[str, Any] = {}
_price_cache: Dict[str, Any] = {}


# ---------------------------------------------------------------------------
# Feed status
# ---------------------------------------------------------------------------

feed_status: Dict[str, Any] = {
    "provider_id": "binance-futures",
    "provider_label": "Binance Futures BTCUSDT",
    "symbol": SYMBOL,
    "display_symbol": DISPLAY_SYMBOL,
    "kind": "futures",
    "degraded": False,
    "is_proxy": False,
    "note": "Live Binance Futures BTCUSDT market data.",
    "last_error": "",
    "last_update": None,
    "live_source": "rest",
    "ws_connected": False,
    "ws_reconnects": 0,
    "stale": True,
    "tick_age_seconds": None,
}


# ---------------------------------------------------------------------------
# Live WebSocket state
# ---------------------------------------------------------------------------

_ws_task: Optional[asyncio.Task] = None
_ws_running = False

_live_price: Optional[float] = None
_live_price_at: float = 0.0

_live_candles: Dict[str, Dict[str, Any]] = {}


# ---------------------------------------------------------------------------
# Live data helpers
# ---------------------------------------------------------------------------

def _drop_live_data() -> None:
    global _live_price
    global _live_price_at

    _live_price = None
    _live_price_at = 0.0

    _live_candles.clear()
    _price_cache.pop("last", None)


def _live_fresh() -> bool:
    return bool(
        _live_price is not None
        and (time.time() - _live_price_at) < STALE_AFTER
    )


def _update_live_price(
    price: float,
    source: str,
) -> None:
    global _live_price
    global _live_price_at

    _live_price = price
    _live_price_at = time.time()

    _price_cache["last"] = (
        time.time(),
        price,
    )

    feed_status["live_source"] = source
    feed_status["stale"] = False
    feed_status["tick_age_seconds"] = 0.0
    feed_status["last_update"] = time.time()


def _update_live_candle(
    interval: str,
    kline: Dict[str, Any],
) -> None:
    candle = {
        "time": int(kline["t"]),
        "open": float(kline["o"]),
        "high": float(kline["h"]),
        "low": float(kline["l"]),
        "close": float(kline["c"]),
        "volume": float(kline["v"]),
        "close_time": int(kline["T"]),
        "closed": bool(kline["x"]),
    }

    _live_candles[interval] = candle

    # Only update REST cache after the candle closes.
    if not candle["closed"]:
        return

    for key, cached in list(_kline_cache.items()):
        if not key.startswith(f"{interval}:"):
            continue

        candles = list(cached[1])

        if candles and candles[-1]["time"] == candle["time"]:
            candles[-1] = candle
        else:
            candles.append(candle)

        _kline_cache[key] = (
            time.time(),
            candles,
        )


# ---------------------------------------------------------------------------
# WebSocket
# ---------------------------------------------------------------------------

async def _websocket_loop() -> None:
    global _ws_running

    streams = [
        f"{SYMBOL.lower()}@trade",
        *[
            f"{SYMBOL.lower()}@kline_{tf}"
            for tf in INTERVALS
        ],
    ]

    url = f"{WS_BASE}{'/'.join(streams)}"

    _ws_running = True

    while _ws_running:
        try:
            async with websockets.connect(
                url,
                ping_interval=20,
                ping_timeout=20,
                close_timeout=5,
            ) as ws:

                feed_status["ws_connected"] = True
                feed_status["last_error"] = ""

                async for raw in ws:
                    if not _ws_running:
                        break

                    try:
                        message = json.loads(raw)

                        stream = message.get(
                            "stream",
                            "",
                        )

                        data = message.get(
                            "data",
                            {},
                        )

                        if "@trade" in stream:
                            price = float(data["p"])

                            _update_live_price(
                                price,
                                "websocket",
                            )

                        elif "@kline_" in stream:
                            kline = data.get("k")

                            if not kline:
                                continue

                            interval = str(
                                kline.get("i")
                            )

                            if interval in INTERVALS:
                                _update_live_candle(
                                    interval,
                                    kline,
                                )

                    except Exception as exc:
                        feed_status["last_error"] = (
                            f"websocket message: {exc}"
                        )

        except asyncio.CancelledError:
            feed_status["ws_connected"] = False
            raise

        except Exception as exc:
            feed_status["ws_connected"] = False
            feed_status["ws_reconnects"] = (
                int(
                    feed_status.get(
                        "ws_reconnects"
                    )
                    or 0
                )
                + 1
            )

            feed_status["last_error"] = (
                f"websocket disconnected: {exc}"
            )

            await asyncio.sleep(3)

    feed_status["ws_connected"] = False
    _ws_running = False


async def start_feed() -> None:
    """Start the BTCUSDT WebSocket feed."""

    global _ws_task

    if (
        _ws_task
        and not _ws_task.done()
    ):
        return

    _drop_live_data()

    _ws_task = asyncio.create_task(
        _websocket_loop()
    )


async def stop_websocket() -> None:
    global _ws_running
    global _ws_task

    _ws_running = False

    if (
        _ws_task
        and not _ws_task.done()
    ):
        _ws_task.cancel()

        with suppress(asyncio.CancelledError):
            await _ws_task

    _ws_task = None

    feed_status["ws_connected"] = False


# ---------------------------------------------------------------------------
# REST helpers
# ---------------------------------------------------------------------------

def _set_status(error: str = "") -> None:
    age = (
        time.time() - _live_price_at
        if _live_price_at
        else None
    )

    stale = not _live_fresh()

    feed_status.update(
        {
            "provider_id": "binance-futures",
            "provider_label": "Binance Futures BTCUSDT",
            "symbol": SYMBOL,
            "display_symbol": DISPLAY_SYMBOL,
            "kind": "futures",
            "degraded": False,
            "is_proxy": False,
            "note": (
                "Live Binance Futures BTCUSDT "
                "market data."
            ),
            "last_error": (
                error
                or feed_status.get(
                    "last_error",
                    "",
                )
            ),
            "stale": stale,
            "tick_age_seconds": (
                round(age, 1)
                if age is not None
                else None
            ),
            "live_source": (
                "websocket"
                if _live_fresh()
                else "rest"
            ),
        }
    )


async def _rest_get(
    path: str,
    params: Dict[str, Any],
) -> Any:
    response = await _http().get(
        f"{REST_BASE}{path}",
        params=params,
    )

    response.raise_for_status()

    return response.json()


# ---------------------------------------------------------------------------
# Candles
# ---------------------------------------------------------------------------

def _parse_klines(
    raw: List[List[Any]],
) -> List[Dict[str, Any]]:
    candles: List[Dict[str, Any]] = []

    for k in raw:
        candles.append(
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

    return candles


async def get_klines(
    interval: str,
    limit: int = 300,
) -> List[Dict[str, Any]]:
    """Return historical candles plus the live forming candle."""

    if interval not in INTERVAL_MINUTES:
        interval = "15m"

    key = f"{interval}:{limit}"

    cached = _kline_cache.get(key)

    if (
        cached
        and (
            time.time() - cached[0]
        ) < KLINE_TTL
    ):
        candles = list(cached[1])

    else:
        try:
            raw = await _rest_get(
                "/klines",
                {
                    "symbol": SYMBOL,
                    "interval": interval,
                    "limit": limit,
                },
            )

            candles = _parse_klines(raw)

            _kline_cache[key] = (
                time.time(),
                candles,
            )

            _set_status()

        except Exception as exc:
            feed_status["last_error"] = (
                f"klines {interval}: {exc}"
            )

            candles = (
                list(cached[1])
                if cached
                else []
            )

    # Add/replace live forming candle.
    live = _live_candles.get(interval)

    if (
        live
        and _live_fresh()
    ):
        if (
            candles
            and candles[-1]["time"]
            == live["time"]
        ):
            candles[-1] = dict(live)

        elif (
            not candles
            or live["time"] > candles[-1]["time"]
        ):
            candles.append(dict(live))

    return candles[-limit:]


# ---------------------------------------------------------------------------
# Live price
# ---------------------------------------------------------------------------

async def get_price() -> Optional[float]:
    """Return live BTC price with REST fallback."""

    if _live_fresh():
        age = time.time() - _live_price_at

        feed_status["tick_age_seconds"] = round(
            age,
            1,
        )

        feed_status["stale"] = False

        return _live_price

    cached = _price_cache.get("last")

    if (
        cached
        and (
            time.time() - cached[0]
        ) < PRICE_TTL
    ):
        return cached[1]

    try:
        data = await _rest_get(
            "/ticker/price",
            {
                "symbol": SYMBOL,
            },
        )

        price = float(data["price"])

        _update_live_price(
            price,
            "rest",
        )

        _set_status()

        return price

    except Exception as exc:
        feed_status["last_error"] = (
            f"price: {exc}"
        )

        candles = await get_klines(
            "1m",
            2,
        )

        if candles:
            return candles[-1]["close"]

        if cached:
            return cached[1]

        return None


# ---------------------------------------------------------------------------
# 24h ticker statistics
# ---------------------------------------------------------------------------

async def get_stats_24h() -> Dict[str, float]:
    """Return BTC 24-hour ticker statistics."""

    try:
        data = await _rest_get(
            "/ticker/24hr",
            {
                "symbol": SYMBOL,
            },
        )

        return {
            "open_24h": float(
                data["openPrice"]
            ),
            "high_24h": float(
                data["highPrice"]
            ),
            "low_24h": float(
                data["lowPrice"]
            ),
            "volume_24h": float(
                data["volume"]
            ),
            "change_24h": float(
                data["priceChange"]
            ),
            "change_pct_24h": float(
                data["priceChangePercent"]
            ),
        }

    except Exception as exc:
        feed_status["last_error"] = (
            f"24h stats: {exc}"
        )

        # Fallback from candles.
        candles = await get_klines(
            "1h",
            25,
        )

        if not candles:
            return {}

        first_open = candles[0]["open"]
        last_close = candles[-1]["close"]

        return {
            "open_24h": first_open,
            "high_24h": max(
                c["high"]
                for c in candles
            ),
            "low_24h": min(
                c["low"]
                for c in candles
            ),
            "volume_24h": sum(
                c["volume"]
                for c in candles
            ),
            "change_24h": (
                last_close - first_open
            ),
            "change_pct_24h": (
                (
                    last_close - first_open
                )
                / first_open
                * 100
                if first_open
                else 0.0
            ),
        }


# ---------------------------------------------------------------------------
# WebSocket health
# ---------------------------------------------------------------------------

def websocket_health() -> Dict[str, Any]:
    return {
        "running": bool(
            _ws_task
            and not _ws_task.done()
        ),
        "connected": bool(
            feed_status.get(
                "ws_connected"
            )
        ),
        "provider_id": "binance-futures",
        "last_price": (
            _live_price
            if _live_fresh()
            else None
        ),
        "tick_age_seconds": (
            round(
                time.time()
                - _live_price_at,
                1,
            )
            if _live_price_at
            else None
        ),
        "reconnects": feed_status.get(
            "ws_reconnects",
            0,
        ),
        "error": feed_status.get(
            "last_error",
            "",
        ),
    }


# ---------------------------------------------------------------------------
# Backward compatibility
# ---------------------------------------------------------------------------

def start_websocket() -> None:
    asyncio.create_task(
        start_feed()
    )