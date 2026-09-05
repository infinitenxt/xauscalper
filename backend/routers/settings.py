"""User settings router — engine config, symbol and Telegram settings."""

from fastapi import APIRouter, Request

from lib import auth, settings as settings_mod

router = APIRouter(tags=["settings"])

# Fields the user is allowed to tune from the settings panel. Everything else
# (user_id, symbol, telegram_*, timestamps) is managed through dedicated routes.
_ENGINE_FIELDS = set(settings_mod.DEFAULT_SETTINGS.keys()) - {"symbol"}


@router.get("/settings")
async def get_settings(request: Request):
    """Get current user settings (auto-creates defaults on first read)."""
    user = await auth.require_subscription(request)
    return await settings_mod.get_settings(user["id"])


async def _update_engine_settings(request: Request, body: dict):
    user = await auth.require_subscription(request)
    updates = {
        k: v
        for k, v in body.items()
        if k in _ENGINE_FIELDS and v is not None
    }
    if not updates:
        return await settings_mod.get_settings(user["id"])
    return await settings_mod.update_settings(user["id"], updates)


@router.patch("/settings")
async def patch_settings(request: Request, body: dict):
    """Update engine settings (PATCH)."""
    return await _update_engine_settings(request, body)


@router.put("/settings")
async def put_settings(request: Request, body: dict):
    """Update engine settings (PUT) — used by the dashboard 'Save All Settings'."""
    return await _update_engine_settings(request, body)


@router.post("/settings/reset")
async def reset_settings(request: Request):
    """Restore engine settings to defaults, preserving symbol and Telegram config."""
    user = await auth.require_subscription(request)
    existing = await settings_mod.get_settings(user["id"])

    reset_values = {k: v for k, v in settings_mod.DEFAULT_SETTINGS.items() if k != "symbol"}
    # Preserve the user's chosen symbol and Telegram credentials across a reset.
    for keep in ("telegram_bot_token", "telegram_channel_id", "telegram_alerts_enabled"):
        if keep in existing:
            reset_values[keep] = existing[keep]

    return await settings_mod.update_settings(user["id"], reset_values)


@router.patch("/settings/symbol")
async def update_symbol(request: Request, body: dict):
    """Update the user's active trading symbol (BTCUSDT / XAUUSD)."""
    user = await auth.require_subscription(request)
    symbol = str(body.get("symbol") or "BTCUSDT")
    return await settings_mod.update_symbol(user["id"], symbol)


@router.patch("/settings/telegram")
async def update_telegram_settings(request: Request, body: dict):
    """Update Telegram alert settings (auto-creates the settings doc if missing)."""
    user = await auth.require_subscription(request)
    updates = {
        "telegram_bot_token": body.get("bot_token"),
        "telegram_channel_id": body.get("channel_id"),
        "telegram_alerts_enabled": bool(body.get("enabled", False)),
    }
    result = await settings_mod.update_settings(user["id"], updates)
    return {"status": "updated", "settings": result}
