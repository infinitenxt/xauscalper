/**
 * TypeScript mirrors of the backend Pydantic models (backend/models/*.py) and
 * the dict-shaped payloads returned by the trading routes. Kept in sync by hand —
 * nothing infers across the HTTP boundary. datetime -> ISO string.
 */

// =====================================================================
// TIMEFRAMES
// =====================================================================

export const TIMEFRAMES = ["1m", "5m", "15m", "30m", "1h"] as const;

export type Timeframe = (typeof TIMEFRAMES)[number];

// =====================================================================
// MARKET DATA
// =====================================================================

export interface Candle {
  time: number;
  open: number;
  high: number;
  low: number;
  close: number;
  volume: number;
}

export interface CandlesResponse {
  symbol: string;
  timeframe: string;
  provider: string;
  candles: Candle[];
}

export interface Ticker {
  symbol: string;
  price: number;
  open_24h: number;
  high_24h: number;
  low_24h: number;
  volume_24h: number;
  change_24h: number;
  change_pct_24h: number;
}

export interface FeedStatus {
  symbol: string;
  display_symbol: string;
  provider: string;
  ws_connected: boolean;
  stale: boolean;
  last_error: string;
  last_price: number;
  tick_age_seconds: number;
  last_update: number;
  is_proxy?: boolean;
  live_source?: string;
  ws_reconnects?: number;
  note?: string;
  provider_label?: string;
  degraded?: boolean;
}

// =====================================================================
// SIGNAL ENGINE
// =====================================================================

export interface Confirmation {
  name: string;
  weight: number;
  vote: number;
  direction: string;
  state: string;
  detail: string;
}

export interface RiskCheck {
  name: string;
  passed: boolean;
  detail: string;
}

export interface Signal {
  symbol: string;
  timeframe: string;
  direction: string;
  confidence: number;
  price: number;
  bull_score: number;
  bear_score: number;
  confirmations: Confirmation[];
  risk_checks: RiskCheck[];
  tradeable: boolean;
  summary: string;
  sl_dist: number | null;
  tp_dist: number | null;
  rr: number;
  atr: number;
  last_closed: number;
  level_reasons: string[];
  structure?: { label?: string; bias?: string; detail?: string };
  pattern?: { label?: string; bias?: string; detail?: string };
  breakout?: {
    label?: string;
    bias?: string;
    detail?: string;
    chop?: boolean;
    fake?: boolean;
    efficiency?: number;
    quality?: number;
  };
  order_book?: {
    symbol: string;
    provider_symbol: string;
    stale: boolean;
    imbalance: number;
    near_imbalance: number;
    spread_bps: number | null;
    bid_notional: number;
    ask_notional: number;
    captured_at: string;
    error: string;
  } | null;
  sl?: number | null;
  tp?: number | null;
  block_reason?: string;
  generated_at?: string;
  data_source?: "public" | "broker";
  broker_symbol?: string;
  broker_data_status?: string;
}

// =====================================================================
// WALLET & TRADES
// =====================================================================

export interface Wallet {
  id: string;
  user_id: string;
  balance: number;
  starting_balance: number;
  realized_pnl: number;
  wins: number;
  losses: number;
  trades_count: number;
  created_at: string | null;
  unrealized_pnl: number;
  equity: number;
  win_rate: number;
  profit_factor: number;
  max_drawdown_pct: number;
  return_pct: number;
  day_pnl: number;
  open_position: boolean;
}

export interface Trade {
  id: string;
  user_id?: string;
  symbol?: string;
  timeframe: string;
  direction: string;
  status: string;
  entry: number;
  sl: number;
  tp: number;
  initial_sl?: number;
  qty?: number;
  confidence: number;
  current_price?: number;
  exit_price?: number | null;
  pnl?: number;
  partial_pnl?: number;
  unrealized_pnl?: number;
  r_multiple?: number;
  age_seconds?: number;
  duration_seconds?: number;
  seconds_to_timeout?: number;
  tp_progress_pct?: number;
  breakeven_done?: boolean;
  partial_done?: boolean;
  trailing_active?: boolean;
  session?: string;
  liquidity?: string;
  entry_reason?: string;
  entry_reasons: string[];
  risk_reasons: string[];
  management_log: string[];
  exit_reason?: string;
  exit_explanation?: string;
  ai_explanation?: string;
  ai_status?: string;
  opened_at?: string | null;
  closed_at?: string | null;
}

// =====================================================================
// GUARDS & ENGINE
// =====================================================================

export interface GuardCheck {
  name: string;
  passed: boolean;
  detail: string;
}

export interface Guards {
  checks: GuardCheck[];
  blocked: boolean;
  block_reason: string;
  day_pnl: number;
  trades_last_hour: number;
  loss_streak: number;
  present: boolean;
}

export interface EngineConfig {
  user_id: string;
  confidence_threshold: number;
  min_adx: number;
  min_rr: number;
  risk_per_trade_pct: number;
  base_rr: number;
  atr_sl_mult: number;
  min_atr_pct: number;
  max_atr_pct: number;
  trail_start_r: number;
  trail_atr_mult: number;
  trailing_enabled: boolean;
  breakeven_at_r: number;
  profit_lock_r: number;
  reverse_exit_enabled: boolean;
  reverse_exit_confidence: number;
  reverse_exit_min_hold_minutes: number;
  cooldown_seconds: number;
  max_hold_minutes: number;
  daily_loss_limit_pct: number;
  max_trades_per_hour: number;
  consecutive_loss_pause: number;
  pause_minutes_after_losses: number;
  stale_entry_max_pct: number;
  auto_trade_enabled: boolean;
  session_filter_enabled: boolean;
  primary_timeframe: string;
  partial_tp_at_r: number;
  partial_tp_fraction: number;
  symbol: string;
  presence_window_seconds?: number;
  disclaimer?: string;
  created_at?: string;
  updated_at?: string;
}

export type SettingsPatch = Partial<
  Omit<EngineConfig, "user_id" | "symbol" | "created_at" | "updated_at">
>;

export interface EngineHealth {
  started_at: string | null;
  cycles: number;
  last_cycle_at: string | null;
  last_error: string;
  restarts: number;
  running: boolean;
  watchdog_running: boolean;
  loop_seconds: number;
  presence_window_seconds: number;
  server_time: string;
}

export interface Dashboard {
  feed: FeedStatus;
  ticker: Ticker;
  signal: Signal;
  wallet: Wallet;
  open_trade: Trade | null;
  history: Trade[];
  config: EngineConfig;
  guards: Guards;
  sessions: SessionSnapshot;
  engine: EngineHealth;
  server_time: string;
}

// =====================================================================
// SESSIONS
// =====================================================================

export interface TradingSession {
  name: string;
  active: boolean;
  open_utc: string;
  close_utc: string;
  minutes_to_open: number;
  minutes_to_close: number;
}

export interface SessionSnapshot {
  utc_time: string;
  sessions: TradingSession[];
  active: string[];
  liquidity: string;
  tradeable: boolean;
  note: string;
  overlap_active: boolean;
  minutes_to_overlap: number;
}

// =====================================================================
// AUTH & USERS
// =====================================================================

export interface SubscriptionInfo {
  plan_id: string | null;
  plan_name: string | null;
  status: string;
  source: string | null;
  started_at: string | null;
  expires_at: string | null;
  days_left: number;
}

export interface UserPublic {
  id: string;
  email: string;
  username: string;
  role: string;
  is_active: boolean;
  created_at: string | null;
  subscribed: boolean;
  subscription: SubscriptionInfo;
}

export interface AuthResponse {
  user: UserPublic;
  message: string;
}

export interface RegistrationPolicy {
  registration_open: boolean;
  invite_mode_enabled: boolean;
}

// =====================================================================
// BILLING & PLANS
// =====================================================================

export interface Plan {
  id: string;
  name: string;
  price_inr: number;
  days: number;
  features: string[];
  is_active: boolean;
  highlight: boolean;
  product_type: string;
}

export interface Mt5LiveEntitlement {
  active: boolean;
  plan_id: string | null;
  plan_name: string | null;
  started_at: string | null;
  expires_at: string | null;
  days_left: number;
}

export interface BillingStatus {
  plans: Plan[];
  subscription: SubscriptionInfo;
  razorpay_enabled: boolean;
  razorpay_key_id: string | null;
  currency: string;
  message: string;
  mt5_live_plan: Plan | null;
  mt5_live_entitlement: Mt5LiveEntitlement;
}

export interface OrderResponse {
  order_id: string;
  amount: number;
  currency: string;
  key_id: string;
  plan: Plan;
  original_amount_inr: number;
  discount_inr: number;
  coupon_code: string | null;
}

export interface CouponPreview {
  code: string;
  discount_pct: number;
  eligible_plan_ids: string[];
  claims_remaining: number;
  expires_at: string;
}

// =====================================================================
// ADMIN
// =====================================================================

export interface SiteSettings {
  site_name: string;
  tagline: string;
  support_email: string;
  allow_registration: boolean;
  invite_mode_enabled: boolean;
  maintenance_mode: boolean;
  trial_days: number;
  affiliate_commission_pct: number;
  razorpay_key_id: string;
  razorpay_key_secret_set: boolean;
  razorpay_enabled: boolean;
}

export interface InviteRow {
  email: string;
  note: string;
  used: boolean;
  invited_by: string;
  created_at: string | null;
  used_at: string | null;
}

export interface AdminStats {
  users_total: number;
  users_active: number;
  subscribers: number;
  admins: number;
  signed_in_now: number;
  new_users_7d: number;
  revenue_inr: number;
  payments: number;
  plans: number;
  invites_pending: number;
}

export interface SessionRow {
  user_id: string;
  email: string;
  username: string;
  user_agent: string;
  ip: string;
  created_at: string | null;
  expires_at: string | null;
}

export interface PaymentRow {
  id: string;
  user_id: string;
  email: string;
  plan_id: string;
  plan_name: string;
  product_type: string;
  amount_inr: number;
  original_amount_inr: number | null;
  discount_inr: number;
  coupon_code: string | null;
  affiliate_commission_inr: number;
  status: string;
  provider: string;
  order_id: string | null;
  payment_id: string | null;
  created_at: string | null;
}

// =====================================================================
// COUPONS & AFFILIATE
// =====================================================================

export interface Coupon {
  id: string;
  code: string;
  discount_pct: number;
  claim_limit: number;
  claims_used: number;
  claims_reserved: number;
  expires_at: string;
  active: boolean;
  eligible_plan_ids: string[];
  created_at: string | null;
}

export interface BankDetailsPublic {
  account_holder: string;
  bank_name: string;
  account_last4: string;
  ifsc_code: string;
  configured: boolean;
}

export interface AffiliateSummary {
  referral_code: string;
  referral_path: string;
  commission_pct: number;
  referred_users: number;
  paid_referrals: number;
  earned_total: number;
  available_balance: number;
  pending_withdrawal: number;
  withdrawn_total: number;
  bank: BankDetailsPublic;
}

export interface AffiliateEarning {
  id: string;
  referred_user_email: string;
  plan_name: string;
  purchase_amount_inr: number;
  commission_pct: number;
  commission_inr: number;
  payment_id: string;
  created_at: string | null;
}

export interface WithdrawalRow {
  id: string;
  user_id: string;
  user_email: string;
  amount_inr: number;
  status: string;
  bank: Record<string, string>;
  note: string;
  created_at: string | null;
  updated_at: string | null;
}

// =====================================================================
// BACKTEST
// =====================================================================

export interface BacktestTrade {
  time: number;
  direction: string;
  entry: number;
  exit: number;
  sl: number;
  tp: number;
  pnl: number;
  r_multiple: number;
  confidence: number;
  exit_reason: string;
  hold_minutes: number;
  session: string;
}

export interface BacktestPoint {
  time: number;
  equity: number;
}

export interface SessionSplit {
  session: string;
  trades: number;
  wins: number;
  losses: number;
  win_rate: number;
  net_pnl: number;
  avg_r: number;
  profit_factor: number;
  share_pct: number;
}

export interface BacktestResult {
  timeframe: string;
  bars_tested: number;
  trades: number;
  wins: number;
  losses: number;
  win_rate: number;
  net_pnl: number;
  return_pct: number;
  profit_factor: number;
  avg_r: number;
  best: number;
  worst: number;
  max_drawdown_pct: number;
  avg_hold_minutes: number;
  exit_reasons: Record<string, number>;
  session_breakdown: SessionSplit[];
  best_session: string;
  worst_session: string;
  equity_curve: BacktestPoint[];
  trade_list: BacktestTrade[];
  note: string;
  starting_equity: number;
  generated_at: string | null;
  settings_used: Record<string, unknown>;
}

// =====================================================================
// MT5
// =====================================================================

export interface Mt5Position {
  ticket: string;
  symbol: string;
  direction: string;
  volume: number;
  entry_price: number;
  current_price: number;
  sl: number;
  tp: number;
  profit: number;
  opened_at: string | null;
  updated_at: string | null;
}

export interface Mt5Command {
  id: string;
  idempotency_key: string;
  action: string;
  status: string;
  symbol: string;
  direction: string;
  lots: number;
  sl_dist: number;
  tp_dist: number;
  reason: string;
  payload: Record<string, unknown>;
  broker_ticket: string | null;
  broker_deal: string | null;
  broker_retcode: number | null;
  execution_result: string;
  broker_message: string;
  created_at: string | null;
  expires_at: string | null;
  expires_epoch: number;
  completed_at: string | null;
}

export interface Mt5Account {
  id: string;
  user_id: string;
  user_email: string;
  provider: string;
  mode: string;
  account_login: string;
  broker_server: string;
  status: string;
  connected: boolean;
  resolved_symbol: string;
  lot_size: number;
  auto_trade_enabled: boolean;
  live_entitled: boolean;
  trade_allowed: boolean;
  algo_trading: boolean;
  balance: number;
  equity: number;
  margin: number;
  free_margin: number;
  margin_level: number;
  account_currency: string;
  daily_profit: number;
  volume_min: number;
  volume_max: number;
  volume_step: number;
  ea_version: string;
  last_poll_at: string | null;
  last_heartbeat_at: string | null;
  last_seen_at: string | null;
  last_error: string;
  entry_state: string;
  entry_reason: string;
  broker_data_ready: boolean;
  broker_data_source: string;
  broker_tick_at: string | null;
  broker_bid: number;
  broker_ask: number;
  broker_spread_points: number;
  created_at: string | null;
  position: Mt5Position | null;
}

export interface Mt5ConnectResponse {
  account: Mt5Account;
  bridge_token: string;
  bridge_url: string;
  setup_steps: string[];
}

export interface SurvivalStatus {
  enabled: boolean;
  activation_requested: boolean;
  status: string;
  balance: number;
  equity: number;
  daily_profit_target_usd: number;
  daily_drawdown_limit_pct: number;
  max_drawdown_limit_pct: number;
  daily_profit_usd: number;
  daily_drawdown_pct: number;
  max_drawdown_pct: number;
  target_progress_pct: number;
  broker_feed_ready: boolean;
  broker_day: string;
  gpt: Record<string, unknown>;
  claude: Record<string, unknown>;
  consensus: string;
  last_error: string;
  updated_at: string | null;
}

// =====================================================================
// UTILITY FUNCTIONS
// =====================================================================

export const fmt = (value: number | null | undefined, decimals: number = 2): string => {
  if (value === null || value === undefined) return "—";
  if (!isFinite(value)) return "—";
  return Number(value).toFixed(decimals);
};

export const money = (value: number | null | undefined): string => {
  if (value === null || value === undefined) return "—";
  if (!isFinite(value)) return "—";
  return `$${fmt(value)}`;
};

export const rupees = (value: number | null | undefined): string => {
  if (value === null || value === undefined) return "—";
  if (!isFinite(value)) return "—";
  return `₹${fmt(value)}`;
};

export const duration = (seconds: number | null | undefined): string => {
  if (seconds === null || seconds === undefined || !isFinite(seconds)) return "—";
  if (seconds < 0) return "—";

  const hrs = Math.floor(seconds / 3600);
  const mins = Math.floor((seconds % 3600) / 60);
  const secs = Math.floor(seconds % 60);

  if (hrs > 0) {
    return `${hrs}h ${mins}m ${secs}s`;
  }
  if (mins > 0) {
    return `${mins}m ${secs}s`;
  }
  return `${secs}s`;
};

export const signed = (value: number | null | undefined, decimals: number = 2): string => {
  if (value === null || value === undefined) return "—";
  if (!isFinite(value)) return "—";
  if (value > 0) return `+${value.toFixed(decimals)}`;
  if (value < 0) return `${value.toFixed(decimals)}`;
  return (0).toFixed(decimals);
};

export const signedMoney = (value: number | null | undefined): string => {
  if (value === null || value === undefined) return "—";
  if (!isFinite(value)) return "—";
  if (value > 0) return `+$${value.toFixed(2)}`;
  if (value < 0) return `-$${Math.abs(value).toFixed(2)}`;
  return "$0.00";
};

export const signedPct = (value: number | null | undefined): string => {
  if (value === null || value === undefined) return "—";
  if (!isFinite(value)) return "—";
  if (value > 0) return `+${value.toFixed(2)}%`;
  if (value < 0) return `${value.toFixed(2)}%`;
  return "0.00%";
};

// =====================================================================
// API ERROR
// =====================================================================

export class ApiError extends Error {
  status: number;
  detail?: unknown;
  body?: unknown;

  constructor(status: number, message: string, body?: unknown) {
    super(message);
    this.status = status;
    this.body = body ?? null;
    this.detail = body;
    this.name = "ApiError";
  }
}
