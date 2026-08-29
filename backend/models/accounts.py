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
    referral_code: Optional[str] = Field(default=None, max_length=32)


class LoginRequest(BaseModel):
    email: EmailStr
    password: str = Field(min_length=1, max_length=128)


class PasswordChangeRequest(BaseModel):
    current_password: str = Field(min_length=1, max_length=128)
    new_password: str = Field(min_length=8, max_length=128)


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


class RegistrationPolicy(BaseModel):
    registration_open: bool = True
    invite_mode_enabled: bool = True


# ----------------------------------------------------------------- billing io
class Plan(BaseModel):
    id: str
    name: str
    price_inr: float
    days: int
    features: List[str] = []
    is_active: bool = True
    highlight: bool = False
    product_type: str = "base"


class PlanPatch(BaseModel):
    name: Optional[str] = None
    price_inr: Optional[float] = None
    days: Optional[int] = None
    features: Optional[List[str]] = None
    is_active: Optional[bool] = None
    highlight: Optional[bool] = None
    product_type: Optional[str] = None


class Mt5LiveEntitlement(BaseModel):
    active: bool = False
    plan_id: Optional[str] = None
    plan_name: Optional[str] = None
    started_at: Optional[datetime] = None
    expires_at: Optional[datetime] = None
    days_left: int = 0


class BillingStatus(BaseModel):
    plans: List[Plan] = []
    subscription: SubscriptionInfo
    razorpay_enabled: bool = False
    razorpay_key_id: Optional[str] = None
    currency: str = "INR"
    message: str = ""
    mt5_live_plan: Optional[Plan] = None
    mt5_live_entitlement: Mt5LiveEntitlement = Field(default_factory=Mt5LiveEntitlement)


class OrderRequest(BaseModel):
    plan_id: str
    coupon_code: Optional[str] = Field(default=None, max_length=32)


class OrderResponse(BaseModel):
    order_id: str
    amount: int
    currency: str
    key_id: str
    plan: Plan
    original_amount_inr: float
    discount_inr: float = 0.0
    coupon_code: Optional[str] = None


class VerifyRequest(BaseModel):
    plan_id: str
    razorpay_order_id: str
    razorpay_payment_id: str
    razorpay_signature: str


class CouponPreviewRequest(BaseModel):
    coupon_code: str = Field(min_length=3, max_length=32)


class CouponPreview(BaseModel):
    code: str
    discount_pct: float
    eligible_plan_ids: List[str] = Field(default_factory=list)
    claims_remaining: int
    expires_at: datetime


# ------------------------------------------------------------------- admin io
class SiteSettings(BaseModel):
    site_name: str = "Gold Paper Terminal"
    tagline: str = "Educational BTCUSDT scalping intelligence"
    support_email: str = ""
    allow_registration: bool = True
    invite_mode_enabled: bool = True
    maintenance_mode: bool = False
    trial_days: int = 0
    affiliate_commission_pct: float = 20.0
    razorpay_key_id: str = ""
    razorpay_key_secret_set: bool = False
    razorpay_enabled: bool = False


class SiteSettingsPatch(BaseModel):
    site_name: Optional[str] = None
    tagline: Optional[str] = None
    support_email: Optional[str] = None
    allow_registration: Optional[bool] = None
    invite_mode_enabled: Optional[bool] = None
    maintenance_mode: Optional[bool] = None
    trial_days: Optional[int] = None
    affiliate_commission_pct: Optional[float] = Field(default=None, ge=0, le=100)


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


class AdminPasswordReset(BaseModel):
    new_password: str = Field(min_length=8, max_length=128)


class InviteCreate(BaseModel):
    email: EmailStr
    note: str = Field(default="", max_length=200)


class InviteRow(BaseModel):
    email: str
    note: str = ""
    used: bool = False
    invited_by: str = ""
    created_at: Optional[datetime] = None
    used_at: Optional[datetime] = None


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
    invites_pending: int = 0


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
    product_type: str = "base"
    amount_inr: float
    original_amount_inr: Optional[float] = None
    discount_inr: float = 0.0
    coupon_code: Optional[str] = None
    affiliate_commission_inr: float = 0.0
    status: str
    provider: str = "razorpay"
    order_id: Optional[str] = None
    payment_id: Optional[str] = None
    created_at: Optional[datetime] = None


# -------------------------------------------------------- coupons / affiliate
class CouponCreate(BaseModel):
    code: str = Field(min_length=3, max_length=32, pattern=r"^[A-Za-z0-9_-]+$")
    discount_pct: float = Field(gt=0, le=99)
    claim_limit: int = Field(ge=1, le=1_000_000)
    expires_at: datetime
    active: bool = True
    eligible_plan_ids: List[str] = Field(default_factory=list)


class CouponPatch(BaseModel):
    discount_pct: Optional[float] = Field(default=None, gt=0, le=99)
    claim_limit: Optional[int] = Field(default=None, ge=1, le=1_000_000)
    expires_at: Optional[datetime] = None
    active: Optional[bool] = None
    eligible_plan_ids: Optional[List[str]] = None


class Coupon(BaseModel):
    id: str
    code: str
    discount_pct: float
    claim_limit: int
    claims_used: int = 0
    claims_reserved: int = 0
    expires_at: datetime
    active: bool = True
    eligible_plan_ids: List[str] = Field(default_factory=list)
    created_at: Optional[datetime] = None


class BankDetailsPatch(BaseModel):
    account_holder: Optional[str] = Field(default=None, min_length=2, max_length=100)
    bank_name: Optional[str] = Field(default=None, min_length=2, max_length=100)
    account_number: Optional[str] = Field(default=None, min_length=6, max_length=32)
    ifsc_code: Optional[str] = Field(default=None, min_length=4, max_length=20)


class BankDetailsPublic(BaseModel):
    account_holder: str = ""
    bank_name: str = ""
    account_last4: str = ""
    ifsc_code: str = ""
    configured: bool = False


class AffiliateSummary(BaseModel):
    referral_code: str
    referral_path: str
    commission_pct: float
    referred_users: int = 0
    paid_referrals: int = 0
    earned_total: float = 0.0
    available_balance: float = 0.0
    pending_withdrawal: float = 0.0
    withdrawn_total: float = 0.0
    bank: BankDetailsPublic = Field(default_factory=BankDetailsPublic)


class AffiliateEarning(BaseModel):
    id: str
    referred_user_email: str = ""
    plan_name: str = ""
    purchase_amount_inr: float
    commission_pct: float
    commission_inr: float
    payment_id: str
    created_at: Optional[datetime] = None


class WithdrawalCreate(BaseModel):
    amount_inr: float = Field(gt=0)


class WithdrawalAction(BaseModel):
    action: str = Field(pattern=r"^(approve|reject|paid)$")
    note: str = Field(default="", max_length=300)


class WithdrawalRow(BaseModel):
    id: str
    user_id: str
    user_email: str = ""
    amount_inr: float
    status: str
    bank: Dict[str, str] = Field(default_factory=dict)
    note: str = ""
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None


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
    session: str = ""


class BacktestPoint(BaseModel):
    time: int
    equity: float


class SessionSplit(BaseModel):
    session: str
    trades: int
    wins: int
    losses: int
    win_rate: float
    net_pnl: float
    avg_r: float
    profit_factor: float
    share_pct: float


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
    session_breakdown: List[SessionSplit] = []
    best_session: str = ""
    worst_session: str = ""
    equity_curve: List[BacktestPoint] = []
    trade_list: List[BacktestTrade] = []
    note: str = ""
    starting_equity: float = 10000.0
    generated_at: Optional[str] = None
    settings_used: Dict[str, Any] = {}
