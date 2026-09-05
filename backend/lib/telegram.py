"""Telegram alert service with durable per-signal cooldown reservations."""

import httpx
import uuid
from datetime import timedelta
from typing import Optional

from pymongo import ReturnDocument
from pymongo.errors import DuplicateKeyError

from lib import auth
from lib.db import db


ALERT_COOLDOWN_SECONDS = 600
RESERVATION_LEASE_SECONDS = 30


async def _reserve_alert(key: str) -> Optional[str]:
    """Atomically reserve one alert key across every app replica."""
    now = auth.now()
    reservation_id = str(uuid.uuid4())
    try:
        row = await db.telegram_alert_cooldowns.find_one_and_update(
            {
                "key": key,
                "$or": [
                    {"next_allowed_at": {"$lte": now}},
                    {"next_allowed_at": {"$exists": False}},
                ],
            },
            {
                "$set": {
                    "status": "sending",
                    "reservation_id": reservation_id,
                    "reserved_at": now,
                    "next_allowed_at": now + timedelta(seconds=RESERVATION_LEASE_SECONDS),
                    "expires_at": now + timedelta(days=1),
                },
                "$setOnInsert": {"key": key, "created_at": now},
            },
            upsert=True,
            return_document=ReturnDocument.AFTER,
        )
    except DuplicateKeyError:
        return None
    return reservation_id if row and row.get("reservation_id") == reservation_id else None


async def _finish_alert(key: str, reservation_id: str, sent: bool) -> None:
    now = auth.now()
    await db.telegram_alert_cooldowns.update_one(
        {"key": key, "reservation_id": reservation_id},
        {
            "$set": {
                "status": "sent" if sent else "failed",
                "last_sent_at": now if sent else None,
                "next_allowed_at": now + timedelta(seconds=ALERT_COOLDOWN_SECONDS) if sent else now,
                "expires_at": now + timedelta(days=1),
            },
            "$unset": {"reservation_id": ""},
        },
    )


async def send_telegram_alert(
    bot_token: str,
    channel_id: str,
    symbol: str,  # ✅ NEW
    direction: str,
    entry: float,
    tp: float,
    sl: float,
    confidence: float,
    timeframe: str,
    user_id: str = "",
) -> bool:
    """Send trade alert using user's own bot"""
    key = "|".join((user_id, symbol.upper(), timeframe, direction.upper()))
    reservation_id = await _reserve_alert(key)
    if reservation_id is None:
        return False
    sent = False
    try:
        # ✅ Symbol mapping for display
        symbol_map = {
            "BTCUSDT": "BTC/USD",
            "XAUUSD": "XAU/USD",
        }
        display_symbol = symbol_map.get(symbol, symbol)
        
        message = f"""
📊 *{display_symbol} Signal Alert*

🎯 *Direction:* {direction}
💰 *Entry:* {entry:.2f}
🎯 *Take Profit:* {tp:.2f}
🛑 *Stop Loss:* {sl:.2f}
📈 *Confidence:* {confidence:.1f}%
⏰ *Timeframe:* {timeframe}

#{symbol} #Signal #Trading
"""
        url = f"https://api.telegram.org/bot{bot_token}/sendMessage"
        payload = {
            "chat_id": channel_id,
            "text": message,
            "parse_mode": "Markdown"
        }
        
        async with httpx.AsyncClient() as client:
            response = await client.post(url, json=payload, timeout=10)
            sent = response.status_code == 200
            return sent
            
    except Exception:
        return False
    finally:
        await _finish_alert(key, reservation_id, sent)


async def test_telegram_alert(bot_token: str, channel_id: str) -> bool:
    """Send test message to verify credentials"""
    try:
        url = f"https://api.telegram.org/bot{bot_token}/sendMessage"
        payload = {
            "chat_id": channel_id,
            "text": "✅ Your BTC signal bot is working!",
            "parse_mode": "Markdown"
        }
        
        async with httpx.AsyncClient() as client:
            response = await client.post(url, json=payload, timeout=10)
            return response.status_code == 200
            
    except Exception:
        return False