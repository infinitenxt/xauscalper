from typing import Optional
from pydantic import BaseModel
from datetime import datetime


class UserSettings(BaseModel):
    user_id: str
    confidence_threshold: float = 80.0
    min_adx: float = 18.0
    min_rr: float = 1.50
    risk_per_trade_pct: float = 8.0
    atr_sl_mult: float = 1.00
    base_rr: float = 1.80
    trail_start_r: float = 0.80
    trail_atr_mult: float = 0.60
    trailing_enabled: bool = True
    breakeven_at_r: float = 0.80
    profit_lock_r: float = 0.10
    reverse_exit_enabled: bool = True
    reverse_exit_confidence: float = 60.0
    reverse_exit_min_hold_minutes: float = 1.0
    daily_loss_limit_pct: float = 20.0
    max_trades_per_hour: int = 6
    consecutive_loss_pause: int = 3
    pause_minutes_after_losses: int = 15
    max_hold_minutes: int = 15
    cooldown_seconds: int = 45
    stale_entry_max_pct: float = 30.0
    primary_timeframe: str = "5m"
    auto_trade_enabled: bool = True
    session_filter_enabled: bool = False
    telegram_bot_token: Optional[str] = None
    telegram_channel_id: Optional[str] = None
    telegram_alerts_enabled: bool = False
    created_at: datetime = datetime.utcnow()
    updated_at: datetime = datetime.utcnow()


class TelegramSettingsUpdate(BaseModel):
    bot_token: Optional[str] = None
    channel_id: Optional[str] = None
    enabled: bool = False