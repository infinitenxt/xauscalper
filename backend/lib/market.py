"""Market data layer for gold (XAUUSDT).

Modular provider chain so the data source can be swapped/improved later:

1. ``binance-futures``  -> https://fapi.binance.com/fapi/v1  symbol XAUUSDT  (primary)
2. ``binance-gold-spot`` -> https://data-api.binance.vision/api/v3 symbol PAXGUSDT (fallback)

Binance Futures answers HTTP 451 ("restricted location") from some hosting
regions. When that happens the chain automatically falls back to Binance's
public spot data mirror using PAXGUSDT, a 1:1 physically-backed gold token that
tracks the same underlying (1 troy ounce of gold). The active provider is always
reported to the UI so nothing is hidden from the user.
"""
from __future__ import annotations

import asyncio
import time
from typing import Any, Dict, List, Optional

import httpx

INTERVALS = ["1m", "5m", "15m", "30m", "1h"]
INTERVAL_MINUTES = {"1m": 1, "5m": 5, "15m": 15, "30m": 30, "1h": 60}

PROVIDERS: List[Dict[str, str]] = [
    {
        "id": "binance-futures",
        "base": "https://fapi.binance.com/fapi/v1",
        "symbol": "XAUUSDT",
        "label": "Binance Futures XAUUSDT",
        "kind": "futures",
    },
    {
        "id": "binance-gold-spot",
        "base": "https://data-api.binance.vision/api/v3",
        "symbol": "PAXGUSDT",
        "label": "Binance PAXGUSDT (gold spot proxy)",
        "kind": "spot",
    },
]

_client: Optional[httpx.AsyncClient] = None
_active: Optional[Dict[str, str]] = None
_active_checked_at: float = 0.0
_probe_lock = asyncio.Lock()

_kline_cache: Dict[str, Any] = {}
_price_cache: Dict[str, Any] = {}

KLINE_TTL = 4.0
PRICE_TTL = 2.0
PROVIDER_TTL = 300.0

feed_status: Dict[str, Any] = {
    "provider_id": None,
    "provider_label": "connecting…",
    "symbol": None,
    "kind": None,
    "degraded": False,
    "note": "",
    "last_error": "",
    "last_update": None,
}


def _http() -> httpx.AsyncClient:
    global _client
    if _client is None:
        _client = httpx.AsyncClient(timeout=12.0, headers={"User-Agent": "paper-trader/1.0"})
    return _client


async def close_http() -> None:
    global _client
    if _client is not None:
        await _client.aclose()
        _client = None


def _set_status(provider: Dict[str, str], error: str = "") -> None:
    degraded = provider["id"] != PROVIDERS[0]["id"]
    feed_status.update(
        {
            "provider_id": provider["id"],
            "provider_label": provider["label"],
            "symbol": provider["symbol"],
            "kind": provider["kind"],
            "degraded": degraded,
            "note": (
                "Binance Futures XAUUSDT is not reachable from this server's region "
                "(HTTP 451). Using Binance's public gold market (PAXGUSDT, 1 oz "
                "gold-backed) so prices and candles remain real."
                if degraded
                else "Live Binance Futures XAUUSDT market data."
            ),
            "last_error": error,
            "last_update": time.time(),
        }
    )


async def _try_provider(provider: Dict[str, str]) -> bool:
    try:
        r = await _http().get(
            f"{provider['base']}/klines",
            params={"symbol": provider["symbol"], "interval": "1m", "limit": 2},
        )
        return r.status_code == 200 and isinstance(r.json(), list)
    except Exception:
        return False


async def active_provider(force: bool = False) -> Dict[str, str]:
    """Pick the first reachable provider; result cached for PROVIDER_TTL."""
    global _active, _active_checked_at
    async with _probe_lock:
        fresh = _active is not None and (time.time() - _active_checked_at) < PROVIDER_TTL
        if fresh and not force:
            return _active  # type: ignore[return-value]
        last_error = ""
        for provider in PROVIDERS:
            if await _try_provider(provider):
                _active = provider
                _active_checked_at = time.time()
                _set_status(provider)
                return provider
            last_error = f"{provider['id']} unreachable"
        # Nothing reachable: keep the previous choice if we had one.
        fallback = _active or PROVIDERS[-1]
        _active = fallback
        _active_checked_at = time.time()
        _set_status(fallback, last_error)
        return fallback


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
    if interval not in INTERVAL_MINUTES:
        interval = "15m"
    key = f"{interval}:{limit}"
    cached = _kline_cache.get(key)
    if cached and (time.time() - cached[0]) < KLINE_TTL:
        return cached[1]

    # One attempt on the cached provider, one on a freshly probed provider.
    for force in (False, True):
        provider = await active_provider(force=force)
        try:
            r = await _http().get(
                f"{provider['base']}/klines",
                params={"symbol": provider["symbol"], "interval": interval, "limit": limit},
            )
            if r.status_code != 200:
                raise RuntimeError(f"HTTP {r.status_code}")
            candles = _parse_klines(r.json())
            _kline_cache[key] = (time.time(), candles)
            _set_status(provider)
            return candles
        except Exception as exc:  # noqa: BLE001
            feed_status["last_error"] = f"klines {interval}: {exc}"
    return cached[1] if cached else []


async def get_price() -> Optional[float]:
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
        _price_cache["last"] = (time.time(), price)
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
