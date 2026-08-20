"""Accounts, subscriptions, billing and site-settings models.

Mirrored by frontend/src/lib/types.ts.
"""
from __future__ import annotations

from datetime import datetime
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, EmailStr, Field


# ------------------------------------------------------------------- auth io
class RegisterRequest(BaseModel):
    email: EmailStr
    username: str = Field(min_length=3, max_length=32)
    password: str = Field(min_length=8, max_length=128)


class LoginRequest(BaseModel):
    email: EmailStr
    password: str = Field(min_length=1, max_length=128)


class SubscriptionInfo(BaseModel):
    plan_id: Optional[str] = None
    plan_name: Optional[str] = None
    status: str = "none"
    source: Optional[str] = None
    started_at: Optional[datetime] = None
    expires_at: Optional[datetime] = None
    days_left: int = 0


class UserPublic(BaseModel):
    id: str
    email: str
    username: str
    role: str
    is_active: bool
    created_at: Optional[datetime] = None
    subscribed: bool
    subscription: SubscriptionInfo


class AuthResponse(BaseModel):
    user: UserPublic
    message: str


# ----------------------------------------------------------------- billing io
class Plan(BaseModel):
    id: str
    name: str
    price_inr: float
    days: int
    features: List[str] = []
    is_active: bool = True
    highlight: bool = False


class PlanPatch(BaseModel):
    name: Optional[str] = None
    price_inr: Optional[float] = None
    days: Optional[int] = None
    features: Optional[List[str]] = None
    is_active: Optional[bool] = None
    highlight: Optional[bool] = None


class BillingStatus(BaseModel):
    plans: List[Plan] = []
    subscription: SubscriptionInfo
    razorpay_enabled: bool = False
    razorpay_key_id: Optional[str] = None
    currency: str = "INR"
    message: str = ""


class OrderRequest(BaseModel):
    plan_id: str


class OrderResponse(BaseModel):
    order_id: str
    amount: int
    currency: str
    key_id: str
    plan: Plan


class VerifyRequest(BaseModel):
    plan_id: str
    razorpay_order_id: str
    razorpay_payment_id: str
    razorpay_signature: str


# ------------------------------------------------------------------- admin io
class SiteSettings(BaseModel):
    site_name: str = "Gold Paper Terminal"
    tagline: str = "Educational XAUUSDT scalping intelligence"
    support_email: str = ""
    allow_registration: bool = True
    maintenance_mode: bool = False
    trial_days: int = 0
    razorpay_key_id: str = ""
    razorpay_key_secret_set: bool = False
    razorpay_enabled: bool = False


class SiteSettingsPatch(BaseModel):
    site_name: Optional[str] = None
    tagline: Optional[str] = None
    support_email: Optional[str] = None
    allow_registration: Optional[bool] = None
    maintenance_mode: Optional[bool] = None
    trial_days: Optional[int] = None


class RazorpayKeysPatch(BaseModel):
    razorpay_key_id: Optional[str] = None
    razorpay_key_secret: Optional[str] = None


class UserPatch(BaseModel):
    is_active: Optional[bool] = None
    role: Optional[str] = None


class GrantRequest(BaseModel):
    plan_id: Optional[str] = None
    days: Optional[int] = None
    revoke: bool = False


class AdminStats(BaseModel):
    users_total: int
    users_active: int
    subscribers: int
    admins: int
    signed_in_now: int
    new_users_7d: int
    revenue_inr: float
    payments: int
    plans: int


class SessionRow(BaseModel):
    user_id: str
    email: str
    username: str
    user_agent: str
    ip: str
    created_at: Optional[datetime] = None
    expires_at: Optional[datetime] = None


class PaymentRow(BaseModel):
    id: str
    user_id: str
    email: str = ""
    plan_id: str
    plan_name: str = ""
    amount_inr: float
    status: str
    provider: str = "razorpay"
    order_id: Optional[str] = None
    payment_id: Optional[str] = None
    created_at: Optional[datetime] = None


# ------------------------------------------------------- sessions / backtest
class TradingSession(BaseModel):
    name: str
    active: bool
    open_utc: str
    close_utc: str
    minutes_to_open: int
    minutes_to_close: int


class SessionSnapshot(BaseModel):
    utc_time: str
    sessions: List[TradingSession]
    active: List[str]
    liquidity: str
    tradeable: bool
    note: str
    overlap_active: bool
    minutes_to_overlap: int


class BacktestTrade(BaseModel):
    time: int
    direction: str
    entry: float
    exit: float
    sl: float
    tp: float
    pnl: float
    r_multiple: float
    confidence: float
    exit_reason: str
    hold_minutes: int


class BacktestPoint(BaseModel):
    time: int
    equity: float


class BacktestResult(BaseModel):
    timeframe: str = ""
    bars_tested: int = 0
    trades: int
    wins: int
    losses: int
    win_rate: float
    net_pnl: float
    return_pct: float
    profit_factor: float
    avg_r: float
    best: float
    worst: float
    max_drawdown_pct: float
    avg_hold_minutes: float
    exit_reasons: Dict[str, int] = {}
    equity_curve: List[BacktestPoint] = []
    trade_list: List[BacktestTrade] = []
    note: str = ""
    starting_equity: float = 10000.0
    generated_at: Optional[str] = None
    settings_used: Dict[str, Any] = {}
