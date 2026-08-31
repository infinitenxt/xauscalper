"""User settings management — with symbol support"""

from typing import Any, Dict, Optional
from datetime import datetime, timezone

from lib.db import db

# ✅ Default settings with symbol
DEFAULT_SETTINGS = {
    # Entry thresholds
    "confidence_threshold": 70.0,
    "min_adx": 18.0,
    "min_rr": 1.50,
    
    # Risk
    "risk_per_trade_pct": 8.0,
    
    # SL/TP
    "base_rr": 1.80,
    "atr_sl_mult": 1.00,
    
    # Volatility filter
    "min_atr_pct": 0.005,
    "max_atr_pct": 5.000,
    
    # Trailing
    "trail_start_r": 0.80,
    "trail_atr_mult": 0.60,
    "breakeven_at_r": 0.80,
    "profit_lock_r": 0.10,
    
    # Cooldown
    "cooldown_seconds": 45,
    "max_hold_minutes": 20,
    "daily_loss_limit_pct": 20.0,
    "max_trades_per_hour": 8,
    "consecutive_loss_pause": 4,
    "pause_minutes_after_losses": 15,
    "stale_entry_max_pct": 35,
    "auto_trade_enabled": True,
    "session_filter_enabled": False,
    "primary_timeframe": "1m",
    
    # Partial TP
    "partial_tp_at_r": 1.50,
    "partial_tp_fraction": 0.40,
    
    # ✅ Symbol (NEW)
    "symbol": "BTCUSDT",  # Default symbol
}


def now() -> datetime:
    return datetime.now(timezone.utc)


async def get_defaults(refresh: bool = False) -> Dict[str, Any]:
    """Get default settings"""
    return DEFAULT_SETTINGS.copy()


async def get_settings(user_id: str, refresh: bool = False) -> Dict[str, Any]:
    """Get user settings — auto-create if not exists"""
    
    doc = await db.settings.find_one({"user_id": user_id})
    
    if not doc:
        # ✅ Create default settings with symbol
        default_settings = {
            "user_id": user_id,
            **DEFAULT_SETTINGS,
            "created_at": now(),
            "updated_at": now(),
        }
        await db.settings.insert_one(default_settings)
        doc = default_settings
    
    # Remove _id
    doc.pop("_id", None)
    return doc


async def update_settings(user_id: str, updates: Dict[str, Any]) -> Dict[str, Any]:
    """Update user settings"""
    
    updates["updated_at"] = now()
    
    result = await db.settings.find_one_and_update(
        {"user_id": user_id},
        {"$set": updates},
        upsert=True,
        return_document=True,
    )
    
    if result:
        result.pop("_id", None)
    
    return result or await get_settings(user_id)


async def update_symbol(user_id: str, symbol: str) -> Dict[str, Any]:
    """Update user's preferred symbol"""
    
    # ✅ Validate symbol
    valid_symbols = ["BTCUSDT", "XAUUSD"]
    if symbol not in valid_symbols:
        symbol = "BTCUSDT"
    
    return await update_settings(user_id, {"symbol": symbol})