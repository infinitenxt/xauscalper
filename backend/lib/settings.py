"""Per-user runtime trading settings, persisted in Mongo.

Each user gets an independent copy of the trading configuration.

Architecture:
    settings
        ├── user_id = "__defaults__"
        ├── user_id = "<USER_A>"
        ├── user_id = "<USER_B>"
        └── ...

The defaults document is used when a user has no personal settings yet.

Users can only affect their own settings through the user-scoped API.
Admin/default settings do not overwrite existing user settings.
"""
from __future__ import annotations

from typing import Any, Dict, Optional

from lib.db import db


# ---------------------------------------------------------------------------
# Storage
# ---------------------------------------------------------------------------

DEFAULTS_ID = "__defaults__"

# Backwards-compatible alias in case another module imports SETTINGS_ID.
SETTINGS_ID = DEFAULTS_ID


# ---------------------------------------------------------------------------
# Default trading configuration
# ---------------------------------------------------------------------------

DEFAULTS: Dict[str, Any] = {
    # --- general ------------------------------------------------------------
    "auto_trade_enabled": True,
    "primary_timeframe": "1m",
    "session_filter_enabled": True,

    # --- entry quality ------------------------------------------------------
    "confidence_threshold": 80.0,
    "min_adx": 20.0,
    "min_rr": 1.3,
    "min_atr_pct": 0.010,
    "max_atr_pct": 1.600,
    "stale_entry_max_pct": 25.0,

    # --- sizing -------------------------------------------------------------
    "risk_per_trade_pct": 1.0,
    "max_leverage": 10.0,

    # --- stop / target ------------------------------------------------------
    "atr_sl_mult": 0.9,
    "base_rr": 1.4,

    # --- position management -----------------------------------------------
    "trail_atr_mult": 0.8,
    "breakeven_at_r": 0.5,
    "trail_start_r": 1.0,
    "partial_tp_at_r": 1.0,
    "partial_tp_fraction": 0.5,

    # --- time management ----------------------------------------------------
    "max_hold_minutes": 15,
    "cooldown_seconds": 60,

    # --- circuit breakers ---------------------------------------------------
    "daily_loss_limit_pct": 3.0,
    "max_trades_per_hour": 6,
    "consecutive_loss_pause": 3,
    "pause_minutes_after_losses": 30,
}


# ---------------------------------------------------------------------------
# Safety bounds
# ---------------------------------------------------------------------------

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


TIMEFRAMES = [
    "1m",
    "5m",
    "15m",
    "30m",
    "1h",
]


# Cache is now user-scoped.
# Example:
# {
#     "__defaults__": {...},
#     "user-id-1": {...},
#     "user-id-2": {...}
# }
_cache: Dict[str, Dict[str, Any]] = {}


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _clean(doc: Dict[str, Any]) -> Dict[str, Any]:
    return {
        k: v
        for k, v in doc.items()
        if k != "_id"
    }


def _coerce(key: str, value: Any) -> Any:
    """Validate and normalize one setting value."""

    if key in (
        "auto_trade_enabled",
        "session_filter_enabled",
    ):
        if isinstance(value, str):
            return value.strip().lower() in (
                "1",
                "true",
                "yes",
                "on",
            )
        return bool(value)

    if key == "primary_timeframe":
        return (
            value
            if value in TIMEFRAMES
            else DEFAULTS["primary_timeframe"]
        )

    try:
        num = float(value)
    except (TypeError, ValueError):
        return DEFAULTS[key]

    lo, hi = BOUNDS.get(
        key,
        (float("-inf"), float("inf")),
    )

    num = max(lo, min(hi, num))

    if key in INT_KEYS:
        return int(round(num))

    return num


def _normalize(doc: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    """Merge a stored document over DEFAULTS and validate every value."""

    merged = dict(DEFAULTS)

    if doc:
        for key in DEFAULTS:
            if key in doc:
                merged[key] = _coerce(
                    key,
                    doc[key],
                )

    return merged


# ---------------------------------------------------------------------------
# Default settings
# ---------------------------------------------------------------------------

async def get_defaults(
    refresh: bool = False,
) -> Dict[str, Any]:
    """Return the global/default trading configuration."""

    if (
        not refresh
        and DEFAULTS_ID in _cache
    ):
        return dict(_cache[DEFAULTS_ID])

    doc = await db.settings.find_one(
        {"user_id": DEFAULTS_ID}
    )

    if not doc:
        doc = {
            "id": DEFAULTS_ID,
            "user_id": DEFAULTS_ID,
            **DEFAULTS,
        }

        await db.settings.update_one(
            {"user_id": DEFAULTS_ID},
            {"$set": doc},
            upsert=True,
        )

    merged = _normalize(doc)

    _cache[DEFAULTS_ID] = merged

    return dict(merged)


async def update_defaults(
    patch: Dict[str, Any],
) -> Dict[str, Any]:
    """Update global defaults.

    This affects only the defaults document.
    Existing users keep their own settings.
    """

    clean = {
        key: _coerce(key, value)
        for key, value in patch.items()
        if key in DEFAULTS
        and value is not None
    }

    if clean:
        await db.settings.update_one(
            {"user_id": DEFAULTS_ID},
            {
                "$set": {
                    **clean,
                    "id": DEFAULTS_ID,
                    "user_id": DEFAULTS_ID,
                }
            },
            upsert=True,
        )

    _cache.pop(DEFAULTS_ID, None)

    return await get_defaults(
        refresh=True
    )


# ---------------------------------------------------------------------------
# User settings
# ---------------------------------------------------------------------------

async def get_settings(
    user_id: str,
    refresh: bool = False,
) -> Dict[str, Any]:
    """Return settings for one specific user.

    If the user has no personal settings yet, a copy of the current defaults
    is created for that user.

    This is important: once created, later admin/default changes do NOT
    silently overwrite this user's personal configuration.
    """

    if not user_id:
        raise ValueError(
            "user_id is required for user-scoped settings"
        )

    if (
        not refresh
        and user_id in _cache
    ):
        return dict(_cache[user_id])

    doc = await db.settings.find_one(
        {"user_id": user_id}
    )

    if not doc:
        defaults = await get_defaults()

        user_doc = {
            "id": user_id,
            "user_id": user_id,
            **defaults,
        }

        await db.settings.update_one(
            {"user_id": user_id},
            {"$set": user_doc},
            upsert=True,
        )

        merged = dict(defaults)
    else:
        merged = _normalize(doc)

    _cache[user_id] = merged

    return dict(merged)


async def update_settings(
    user_id: str,
    patch: Dict[str, Any],
) -> Dict[str, Any]:
    """Update one user's personal settings."""

    if not user_id:
        raise ValueError(
            "user_id is required for user-scoped settings"
        )

    # Ensure the user's settings document exists first.
    await get_settings(user_id)

    clean = {
        key: _coerce(key, value)
        for key, value in patch.items()
        if key in DEFAULTS
        and value is not None
    }

    if clean:
        await db.settings.update_one(
            {"user_id": user_id},
            {
                "$set": clean,
            },
            upsert=True,
        )

    _cache.pop(user_id, None)

    return await get_settings(
        user_id,
        refresh=True,
    )


async def reset_settings(
    user_id: str,
) -> Dict[str, Any]:
    """Reset one user's settings to the current defaults."""

    if not user_id:
        raise ValueError(
            "user_id is required for user-scoped settings"
        )

    defaults = await get_defaults(
        refresh=True
    )

    await db.settings.update_one(
        {"user_id": user_id},
        {
            "$set": {
                "id": user_id,
                "user_id": user_id,
                **defaults,
            }
        },
        upsert=True,
    )

    _cache.pop(user_id, None)

    return await get_settings(
        user_id,
        refresh=True,
    )


# ---------------------------------------------------------------------------
# Optional compatibility helper
# ---------------------------------------------------------------------------

async def get_default_settings(
    refresh: bool = False,
) -> Dict[str, Any]:
    """Compatibility alias for code that wants the global defaults."""

    return await get_defaults(
        refresh=refresh
    )