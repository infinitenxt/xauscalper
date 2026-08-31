"""Telegram alert service — per-user bot support with symbol"""

import httpx
from typing import Optional


async def send_telegram_alert(
    bot_token: str,
    channel_id: str,
    symbol: str,  # ✅ NEW
    direction: str,
    entry: float,
    tp: float,
    sl: float,
    confidence: float,
    timeframe: str
) -> bool:
    """Send trade alert using user's own bot"""
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
            return response.status_code == 200
            
    except Exception:
        return False


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