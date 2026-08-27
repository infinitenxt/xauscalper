"""Session awareness."""
from __future__ import annotations

from fastapi import APIRouter

from lib import market_sessions
from models.accounts import SessionSnapshot

router = APIRouter(tags=["analysis"])


@router.get("/market/sessions", response_model=SessionSnapshot)
async def sessions() -> SessionSnapshot:
    return SessionSnapshot(**market_sessions.snapshot())