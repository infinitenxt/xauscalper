"""Runtime-editable engine settings, persisted in Mongo.

Defaults are tuned for **1-minute scalping**: fast entries, tight stops, short
holds, and hard circuit breakers. Everything here is editable live from the
dashboard, so the strategy can be retuned without a redeploy.
"""
from __future__ import annotations

from typing import Any, Dict

from lib.db import db

SETTINGS_ID = "main"

DEFAULTS: Dict[str, Any] = {
    # --- what to trade -----------------------------------------------------
    "auto_trade_enabled": True,
    "primary_timeframe": "1m",
    # --- entry quality -----------------------------------------------------
    "confidence_threshold": 80.0,
    "min_adx": 20.0,
    "min_rr": 1.3,
    "min_atr_pct": 0.010,
    "max_atr_pct": 1.600,
    "stale_entry_max_pct": 25.0,   # skip if price already ran this % toward TP
    # --- sizing ------------------------------------------------------------
    "risk_per_trade_pct": 1.0,
    "max_leverage": 10.0,
    # --- stop / target -----------------------------------------------------
    "atr_sl_mult": 0.9,
    "base_rr": 1.4,
    "trail_atr_mult": 0.8,
    "breakeven_at_r": 0.5,
    "trail_start_r": 1.0,
    "partial_tp_at_r": 1.0,
    "partial_tp_fraction": 0.5,
    # --- time management ---------------------------------------------------
    "max_hold_minutes": 15,
    "cooldown_seconds": 60,
    # --- circuit breakers --------------------------------------------------
    "daily_loss_limit_pct": 3.0,
    "max_trades_per_hour": 6,
    "consecutive_loss_pause": 3,
    "pause_minutes_after_losses": 30,
}

# Bounds so a bad edit can never brick the engine.
BOUNDS: Dict[str, tuple[float, float]] = {
    "confidence_threshold": (50.0, 99.0),
    "min_adx": (0.0, 60.0),
    "min_rr": (0.5, 5.0),
    "min_atr_pct": (0.0, 5.0),
    "max_atr_pct": (0.05, 10.0),
    "stale_entry_max_pct": (0.0, 90.0),
    "risk_per_trade_pct": (0.1, 5.0),
    "max_leverage": (1.0, 50.0),
    "atr_sl_mult": (0.3, 4.0),
    "base_rr": (0.8, 6.0),
    "trail_atr_mult": (0.2, 4.0),
    "breakeven_at_r": (0.1, 3.0),
    "trail_start_r": (0.2, 5.0),
    "partial_tp_at_r": (0.2, 5.0),
    "partial_tp_fraction": (0.0, 0.9),
    "max_hold_minutes": (1, 720),
    "cooldown_seconds": (0, 3600),
    "daily_loss_limit_pct": (0.5, 50.0),
    "max_trades_per_hour": (1, 60),
    "consecutive_loss_pause": (1, 20),
    "pause_minutes_after_losses": (1, 720),
}

INT_KEYS = {
    "max_hold_minutes",
    "cooldown_seconds",
    "max_trades_per_hour",
    "consecutive_loss_pause",
    "pause_minutes_after_losses",
}

TIMEFRAMES = ["1m", "5m", "15m", "30m", "1h"]

_cache: Dict[str, Any] | None = None


def _coerce(key: str, value: Any) -> Any:
    if key == "auto_trade_enabled":
        return bool(value)
    if key == "primary_timeframe":
        return value if value in TIMEFRAMES else DEFAULTS["primary_timeframe"]
    try:
        num = float(value)
    except (TypeError, ValueError):
        return DEFAULTS[key]
    lo, hi = BOUNDS.get(key, (float("-inf"), float("inf")))
    num = max(lo, min(hi, num))
    return int(round(num)) if key in INT_KEYS else num


async def get_settings(refresh: bool = False) -> Dict[str, Any]:
    global _cache
    if _cache is not None and not refresh:
        return dict(_cache)
    doc = await db.settings.find_one({"id": SETTINGS_ID})
    merged = dict(DEFAULTS)
    if doc:
        for k in DEFAULTS:
            if k in doc:
                merged[k] = _coerce(k, doc[k])
    else:
        await db.settings.insert_one({"id": SETTINGS_ID, **DEFAULTS})
    _cache = merged
    return dict(merged)


async def update_settings(patch: Dict[str, Any]) -> Dict[str, Any]:
    global _cache
    clean = {k: _coerce(k, v) for k, v in patch.items() if k in DEFAULTS and v is not None}
    if clean:
        await db.settings.update_one({"id": SETTINGS_ID}, {"$set": clean}, upsert=True)
    _cache = None
    return await get_settings(refresh=True)


async def reset_settings() -> Dict[str, Any]:
    global _cache
    await db.settings.delete_many({})
    _cache = None
    return await get_settings(refresh=True)
