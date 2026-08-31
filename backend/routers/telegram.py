"""Telegram alert router — per-user bot settings and test routes"""

from fastapi import APIRouter, Request, HTTPException

from lib import auth

router = APIRouter(tags=["telegram"])


@router.post("/telegram/test")
async def test_telegram_route(request: Request, body: dict):
    """Test Telegram credentials"""
    user = await auth.require_subscription(request)
    
    bot_token = body.get("bot_token")
    channel_id = body.get("channel_id")
    
    if not bot_token or not channel_id:
        raise HTTPException(
            status_code=422,
            detail="bot_token and channel_id are required"
        )
    
    # ✅ Direct Telegram API call
    import httpx
    try:
        url = f"https://api.telegram.org/bot{bot_token}/sendMessage"
        payload = {
            "chat_id": channel_id,
            "text": "✅ Your BTC signal bot is working!",
            "parse_mode": "Markdown"
        }
        
        async with httpx.AsyncClient() as client:
            response = await client.post(url, json=payload, timeout=10)
            
            if response.status_code != 200:
                raise HTTPException(
                    status_code=400,
                    detail="Telegram test failed. Check bot token and channel ID."
                )
            
            return {"status": "ok", "message": "✅ Test message sent to Telegram!"}
            
    except Exception as e:
        raise HTTPException(
            status_code=400,
            detail=f"Telegram test failed: {str(e)}"
        )