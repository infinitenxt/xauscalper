"""Pydantic v2 response models. Mirrored by frontend/src/lib/types.ts."""
from __future__ import annotations

from datetime import datetime
from typing import Dict, List, Optional

from pydantic import BaseModel


class Candle(BaseModel):
    time: int
    open: float
    high: float
    low: float
    close: float
    volume: float


class CandlesResponse(BaseModel):
    symbol: str
    timeframe: str
    provider: str
    candles: List[Candle]


class FeedStatus(BaseModel):
    provider_id: Optional[str] = None
    provider_label: str = ""
    symbol: Optional[str] = None
    kind: Optional[str] = None
    degraded: bool = False
    note: str = ""
    last_error: str = ""


class Ticker(BaseModel):
    symbol: str
    price: Optional[float] = None
    open_24h: Optional[float] = None
    high_24h: Optional[float] = None
    low_24h: Optional[float] = None
    volume_24h: Optional[float] = None
    change_24h: Optional[float] = None
    change_pct_24h: Optional[float] = None


class Confirmation(BaseModel):
    name: str
    weight: float
    vote: float
    direction: str
    state: str
    detail: str


class RiskCheck(BaseModel):
    name: str
    passed: bool
    detail: str


class Levels(BaseModel):
    support: List[float] = []
    resistance: List[float] = []


class Read(BaseModel):
    label: str = "UNCLEAR"
    bias: float = 0.0
    detail: str = ""


class MtfRead(BaseModel):
    trend: str
    rsi: Optional[float] = None
    adx: Optional[float] = None


class Signal(BaseModel):
    timeframe: str
    direction: str
    confidence: float
    price: Optional[float] = None
    last_closed: Optional[float] = None
    bull_score: float = 0.0
    bear_score: float = 0.0
    confirmations: List[Confirmation] = []
    risk_checks: List[RiskCheck] = []
    tradeable: bool = False
    summary: str = ""
    sl: Optional[float] = None
    tp: Optional[float] = None
    rr: float = 0.0
    atr: Optional[float] = None
    level_reasons: List[str] = []
    indicators: Dict[str, float] = {}
    levels: Levels = Levels()
    structure: Read = Read()
    pattern: Read = Read()
    mtf: Dict[str, MtfRead] = {}
    generated_at: Optional[str] = None


class Wallet(BaseModel):
    id: str
    balance: float
    starting_balance: float
    realized_pnl: float
    wins: int
    losses: int
    trades_count: int
    unrealized_pnl: float = 0.0
    equity: float = 0.0
    win_rate: float = 0.0
    return_pct: float = 0.0
    day_pnl: float = 0.0
    open_position: bool = False


class Trade(BaseModel):
    id: str
    symbol: str
    direction: str
    status: str
    timeframe: str
    entry: float
    sl: float
    tp: float
    initial_sl: float
    qty: float
    notional: float
    risk_amount: float
    r_distance: float
    rr_planned: float
    confidence: float
    atr: float
    trailing_active: bool = False
    breakeven_done: bool = False
    partial_done: bool = False
    partial_pnl: float = 0.0
    initial_qty: Optional[float] = None
    max_hold_minutes: Optional[int] = None
    best_r: float = 0.0
    opened_at: datetime
    timeout_at: Optional[datetime] = None
    entry_reasons: List[str] = []
    risk_reasons: List[str] = []
    ai_explanation: Optional[str] = None
    ai_status: str = "pending"
    management_log: List[str] = []
    exit_price: Optional[float] = None
    exit_reason: Optional[str] = None
    exit_explanation: Optional[str] = None
    pnl: Optional[float] = None
    pnl_pct: Optional[float] = None
    r_multiple: Optional[float] = None
    closed_at: Optional[datetime] = None
    duration_seconds: Optional[int] = None
    # live-only decoration
    current_price: Optional[float] = None
    unrealized_pnl: Optional[float] = None
    unrealized_pnl_pct: Optional[float] = None
    tp_progress_pct: Optional[float] = None
    age_seconds: Optional[int] = None
    seconds_to_timeout: Optional[int] = None


class EngineConfig(BaseModel):
    auto_trade_enabled: bool
    primary_timeframe: str
    confidence_threshold: float
    min_adx: float
    min_rr: float
    min_atr_pct: float
    max_atr_pct: float
    stale_entry_max_pct: float
    risk_per_trade_pct: float
    max_leverage: float
    atr_sl_mult: float
    base_rr: float
    trail_atr_mult: float
    breakeven_at_r: float
    trail_start_r: float
    partial_tp_at_r: float
    partial_tp_fraction: float
    max_hold_minutes: int
    cooldown_seconds: int
    daily_loss_limit_pct: float
    max_trades_per_hour: int
    consecutive_loss_pause: int
    pause_minutes_after_losses: int
    starting_balance: float
    timeframes: List[str]
    loop_seconds: float
    disclaimer: str


class SettingsPatch(BaseModel):
    auto_trade_enabled: Optional[bool] = None
    primary_timeframe: Optional[str] = None
    confidence_threshold: Optional[float] = None
    min_adx: Optional[float] = None
    min_rr: Optional[float] = None
    stale_entry_max_pct: Optional[float] = None
    risk_per_trade_pct: Optional[float] = None
    atr_sl_mult: Optional[float] = None
    base_rr: Optional[float] = None
    trail_atr_mult: Optional[float] = None
    breakeven_at_r: Optional[float] = None
    trail_start_r: Optional[float] = None
    partial_tp_at_r: Optional[float] = None
    partial_tp_fraction: Optional[float] = None
    max_hold_minutes: Optional[int] = None
    cooldown_seconds: Optional[int] = None
    daily_loss_limit_pct: Optional[float] = None
    max_trades_per_hour: Optional[int] = None
    consecutive_loss_pause: Optional[int] = None
    pause_minutes_after_losses: Optional[int] = None


class Guards(BaseModel):
    checks: List[RiskCheck] = []
    blocked: bool = False
    block_reason: str = ""
    last_block_reason: str = ""
    day_pnl: float = 0.0
    trades_last_hour: int = 0
    loss_streak: int = 0


class Dashboard(BaseModel):
    feed: FeedStatus
    ticker: Ticker
    signal: Signal
    wallet: Wallet
    open_trade: Optional[Trade] = None
    history: List[Trade] = []
    config: EngineConfig
    guards: Guards
    server_time: str
