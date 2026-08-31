"""User settings router — includes Telegram settings"""

from fastapi import APIRouter, Request, HTTPException
from pymongo import ReturnDocument

from lib import auth
from lib.db import db
from models.settings import UserSettings, TelegramSettingsUpdate

router = APIRouter(tags=["settings"])


@router.get("/settings")
async def get_settings(request: Request):
    """Get current user settings"""
    user = await auth.require_subscription(request)
    
    doc = await db.settings.find_one({"user_id": user["id"]})
    
    if not doc:
        # Return defaults
        return UserSettings(user_id=user["id"]).model_dump()
    
    doc.pop("_id", None)
    return doc


@router.patch("/settings")
async def update_settings(request: Request, body: dict):
    """Update user settings"""
    user = await auth.require_subscription(request)
    
    updates = {k: v for k, v in body.items() if v is not None}
    updates["updated_at"] = auth.now()
    
    result = await db.settings.find_one_and_update(
        {"user_id": user["id"]},
        {"$set": updates},
        upsert=True,
        return_document=ReturnDocument.AFTER
    )
    
    if result:
        result.pop("_id", None)
    
    return result or {"user_id": user["id"], **updates}


# ✅ Telegram settings route
@router.patch("/settings/telegram")
async def update_telegram_settings(
    request: Request,
    body: dict
):
    """Update Telegram settings only"""
    user = await auth.require_subscription(request)
    
    bot_token = body.get("bot_token")
    channel_id = body.get("channel_id")
    enabled = body.get("enabled", False)
    
    # ✅ Auto-create settings if not exists
    existing = await db.settings.find_one({"user_id": user["id"]})
    
    if not existing:
        # ✅ Create default settings with Telegram fields
        default_settings = {
            "user_id": user["id"],
            "confidence_threshold": 70.0,
            "min_adx": 18.0,
            "min_rr": 1.50,
            "risk_per_trade_pct": 8.0,
            "atr_sl_mult": 1.00,
            "base_rr": 1.80,
            "trail_start_r": 0.80,
            "trail_atr_mult": 0.60,
            "breakeven_at_r": 0.80,
            "profit_lock_r": 0.10,
            "daily_loss_limit_pct": 20.0,
            "max_trades_per_hour": 6,
            "consecutive_loss_pause": 3,
            "pause_minutes_after_losses": 15,
            "max_hold_minutes": 15,
            "cooldown_seconds": 45,
            "stale_entry_max_pct": 30.0,
            "primary_timeframe": "1m",
            "auto_trade_enabled": True,
            "session_filter_enabled": False,
            "telegram_bot_token": bot_token,
            "telegram_channel_id": channel_id,
            "telegram_alerts_enabled": enabled,
            "created_at": auth.now(),
            "updated_at": auth.now()
        }
        await db.settings.insert_one(default_settings)
        default_settaings.pop("_id", None)
        return {"status": "created", "settings": default_settings}
    
    # ✅ Update existing
    updates = {
        "telegram_bot_token": bot_token,
        "telegram_channel_id": channel_id,
        "telegram_alerts_enabled": enabled,
        "updated_at": auth.now()
    }
    
    await db.settings.update_one(
        {"user_id": user["id"]},
        {"$set": updates}
    )
    
    return {"status": "updated", "settings": updates}