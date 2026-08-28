"""MT5 Expert Advisor bridge request/response models."""
from __future__ import annotations

from datetime import datetime
from typing import Dict, List, Literal, Optional

from pydantic import BaseModel, Field


class Mt5ConnectRequest(BaseModel):
    mode: Literal["demo", "live"]
    account_login: str = Field(min_length=3, max_length=32)
    broker_server: str = Field(min_length=2, max_length=100)
    lot_size: float = Field(gt=0)


class Mt5SettingsPatch(BaseModel):
    lot_size: Optional[float] = Field(default=None, gt=0)
    auto_trade_enabled: Optional[bool] = None


class Mt5Position(BaseModel):
    ticket: str
    symbol: str
    direction: str
    volume: float
    entry_price: float
    current_price: float
    sl: float
    tp: float
    profit: float = 0.0
    opened_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None


class Mt5Command(BaseModel):
    id: str
    idempotency_key: str = ""
    action: str
    status: str
    symbol: str
    direction: str = ""
    lots: float = 0.0
    sl: float = 0.0
    tp: float = 0.0
    reason: str = ""
    payload: Dict[str, object] = Field(default_factory=dict)
    broker_ticket: Optional[str] = None
    broker_deal: Optional[str] = None
    broker_retcode: Optional[int] = None
    execution_result: str = ""
    broker_message: str = ""
    created_at: Optional[datetime] = None
    expires_at: Optional[datetime] = None
    expires_epoch: int = 0
    completed_at: Optional[datetime] = None


class Mt5Account(BaseModel):
    id: str
    user_id: str
    user_email: str = ""
    provider: str = "ea"
    mode: str
    account_login: str
    broker_server: str
    status: str
    connected: bool = False
    resolved_symbol: str = ""
    lot_size: float
    auto_trade_enabled: bool = False
    live_entitled: bool = False
    trade_allowed: bool = False
    algo_trading: bool = False
    balance: float = 0.0
    equity: float = 0.0
    margin: float = 0.0
    free_margin: float = 0.0
    margin_level: float = 0.0
    account_currency: str = ""
    daily_profit: float = 0.0
    volume_min: float = 0.0
    volume_max: float = 0.0
    volume_step: float = 0.0
    ea_version: str = ""
    last_poll_at: Optional[datetime] = None
    last_heartbeat_at: Optional[datetime] = None
    last_seen_at: Optional[datetime] = None
    last_error: str = ""
    entry_state: str = "waiting"
    entry_reason: str = "Waiting for a qualifying signal"
    created_at: Optional[datetime] = None
    position: Optional[Mt5Position] = None


class Mt5ConnectResponse(BaseModel):
    account: Mt5Account
    bridge_token: str
    bridge_url: str
    setup_steps: List[str]


class BridgePosition(BaseModel):
    ticket: str
    symbol: str
    direction: Literal["BUY", "SELL"]
    volume: float = Field(gt=0)
    entry_price: float
    current_price: float
    sl: float
    tp: float
    profit: float = 0.0
    opened_at: Optional[datetime] = None


class BridgeHeartbeat(BaseModel):
    account_login: str
    broker_server: str
    is_demo: bool
    resolved_symbol: str
    balance: float
    equity: float
    margin: float = 0.0
    free_margin: float
    margin_level: float = 0.0
    account_currency: str = Field(default="", max_length=12)
    daily_profit: float = 0.0
    volume_min: float = Field(gt=0)
    volume_max: float = Field(gt=0)
    volume_step: float = Field(gt=0)
    trade_allowed: bool
    algo_trading: bool
    terminal_build: int = 0
    ea_version: str = Field(default="", max_length=32)
    positions: List[BridgePosition] = Field(default_factory=list)


class BridgePollResponse(BaseModel):
    command: Optional[Mt5Command] = None
    server_time: datetime


class BridgeAck(BaseModel):
    command_id: str
    success: Optional[bool] = None
    result: Optional[Literal["accepted", "executed", "rejected", "failed"]] = None
    broker_ticket: Optional[str] = None
    broker_deal: Optional[str] = None
    broker_retcode: Optional[int] = None
    broker_message: str = ""
    filled_price: Optional[float] = None
    filled_volume: Optional[float] = None


class AdminMt5Account(Mt5Account):
    pass