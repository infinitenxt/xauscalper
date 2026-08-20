// Hand-written mirrors of backend/models/trading.py — keep both sides in sync.

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

export interface FeedStatus {
  provider_id: string | null;
  provider_label: string;
  symbol: string | null;
  kind: string | null;
  degraded: boolean;
  note: string;
  last_error: string;
}

export interface Ticker {
  symbol: string;
  price: number | null;
  open_24h: number | null;
  high_24h: number | null;
  low_24h: number | null;
  volume_24h: number | null;
  change_24h: number | null;
  change_pct_24h: number | null;
}

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

export interface Levels {
  support: number[];
  resistance: number[];
}

export interface Read {
  label: string;
  bias: number;
  detail: string;
}

export interface MtfRead {
  trend: string;
  rsi: number | null;
  adx: number | null;
}

export interface Signal {
  timeframe: string;
  direction: string;
  confidence: number;
  price: number | null;
  last_closed: number | null;
  bull_score: number;
  bear_score: number;
  confirmations: Confirmation[];
  risk_checks: RiskCheck[];
  tradeable: boolean;
  summary: string;
  sl: number | null;
  tp: number | null;
  rr: number;
  atr: number | null;
  level_reasons: string[];
  indicators: Record<string, number>;
  levels: Levels;
  structure: Read;
  pattern: Read;
  mtf: Record<string, MtfRead>;
  generated_at: string | null;
}

export interface Wallet {
  id: string;
  balance: number;
  starting_balance: number;
  realized_pnl: number;
  wins: number;
  losses: number;
  trades_count: number;
  unrealized_pnl: number;
  equity: number;
  win_rate: number;
  return_pct: number;
  day_pnl: number;
  open_position: boolean;
}

export interface Trade {
  id: string;
  user_id: string;
  symbol: string;
  direction: string;
  status: string;
  timeframe: string;
  session: string;
  liquidity: string;
  entry: number;
  sl: number;
  tp: number;
  initial_sl: number;
  qty: number;
  notional: number;
  risk_amount: number;
  r_distance: number;
  rr_planned: number;
  confidence: number;
  atr: number;
  trailing_active: boolean;
  breakeven_done: boolean;
  partial_done: boolean;
  partial_pnl: number;
  initial_qty: number | null;
  max_hold_minutes: number | null;
  best_r: number;
  opened_at: string;
  timeout_at: string | null;
  entry_reasons: string[];
  risk_reasons: string[];
  ai_explanation: string | null;
  ai_status: string;
  management_log: string[];
  exit_price: number | null;
  exit_reason: string | null;
  exit_explanation: string | null;
  pnl: number | null;
  pnl_pct: number | null;
  r_multiple: number | null;
  closed_at: string | null;
  duration_seconds: number | null;
  current_price: number | null;
  unrealized_pnl: number | null;
  unrealized_pnl_pct: number | null;
  tp_progress_pct: number | null;
  age_seconds: number | null;
  seconds_to_timeout: number | null;
}

export interface EngineConfig {
  auto_trade_enabled: boolean;
  session_filter_enabled: boolean;
  primary_timeframe: string;
  confidence_threshold: number;
  min_adx: number;
  min_rr: number;
  min_atr_pct: number;
  max_atr_pct: number;
  stale_entry_max_pct: number;
  risk_per_trade_pct: number;
  max_leverage: number;
  atr_sl_mult: number;
  base_rr: number;
  trail_atr_mult: number;
  breakeven_at_r: number;
  trail_start_r: number;
  partial_tp_at_r: number;
  partial_tp_fraction: number;
  max_hold_minutes: number;
  cooldown_seconds: number;
  daily_loss_limit_pct: number;
  max_trades_per_hour: number;
  consecutive_loss_pause: number;
  pause_minutes_after_losses: number;
  starting_balance: number;
  timeframes: string[];
  loop_seconds: number;
  presence_window_seconds: number;
  disclaimer: string;
}

export type SettingsPatch = Partial<
  Pick<
    EngineConfig,
    | "auto_trade_enabled"
    | "session_filter_enabled"
    | "primary_timeframe"
    | "confidence_threshold"
    | "min_adx"
    | "min_rr"
    | "stale_entry_max_pct"
    | "risk_per_trade_pct"
    | "atr_sl_mult"
    | "base_rr"
    | "trail_atr_mult"
    | "breakeven_at_r"
    | "trail_start_r"
    | "partial_tp_at_r"
    | "partial_tp_fraction"
    | "max_hold_minutes"
    | "cooldown_seconds"
    | "daily_loss_limit_pct"
    | "max_trades_per_hour"
    | "consecutive_loss_pause"
    | "pause_minutes_after_losses"
  >
>;

export interface Guards {
  checks: RiskCheck[];
  blocked: boolean;
  block_reason: string;
  last_block_reason: string;
  day_pnl: number;
  trades_last_hour: number;
  loss_streak: number;
  present: boolean;
}

export interface EngineHealth {
  running: boolean;
  watchdog_running: boolean;
  started_at: string | null;
  cycles: number;
  last_cycle_at: string | null;
  last_error: string;
  restarts: number;
  loop_seconds: number;
  presence_window_seconds: number;
  server_time: string | null;
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

// ---------------------------------------------------------------- accounts
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

export interface Plan {
  id: string;
  name: string;
  price_inr: number;
  days: number;
  features: string[];
  is_active: boolean;
  highlight: boolean;
}

export interface BillingStatus {
  plans: Plan[];
  subscription: SubscriptionInfo;
  razorpay_enabled: boolean;
  razorpay_key_id: string | null;
  currency: string;
  message: string;
}

export interface OrderResponse {
  order_id: string;
  amount: number;
  currency: string;
  key_id: string;
  plan: Plan;
}

export interface SiteSettings {
  site_name: string;
  tagline: string;
  support_email: string;
  allow_registration: boolean;
  maintenance_mode: boolean;
  trial_days: number;
  razorpay_key_id: string;
  razorpay_key_secret_set: boolean;
  razorpay_enabled: boolean;
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

export interface InviteRow {
  email: string;
  note: string;
  used: boolean;
  invited_by: string;
  created_at: string | null;
  used_at: string | null;
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
  amount_inr: number;
  status: string;
  provider: string;
  order_id: string | null;
  payment_id: string | null;
  created_at: string | null;
}

// -------------------------------------------------------- sessions/backtest
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
  settings_used: Record<string, number>;
}

export const rupees = (v: number | null | undefined): string =>
  v === null || v === undefined || Number.isNaN(v)
    ? "—"
    : `₹${v.toLocaleString("en-IN", { maximumFractionDigits: 0 })}`;

export const TIMEFRAMES = ["1m", "5m", "15m", "30m", "1h"] as const;

export const fmt = (v: number | null | undefined, digits = 2): string =>
  v === null || v === undefined || Number.isNaN(v) ? "—" : v.toFixed(digits);

export const money = (v: number | null | undefined): string =>
  v === null || v === undefined || Number.isNaN(v)
    ? "—"
    : `${v < 0 ? "-" : ""}$${Math.abs(v).toLocaleString("en-US", {
        minimumFractionDigits: 2,
        maximumFractionDigits: 2,
      })}`;

export const signed = (v: number | null | undefined, digits = 2): string =>
  v === null || v === undefined || Number.isNaN(v) ? "—" : `${v >= 0 ? "+" : ""}${v.toFixed(digits)}`;

export const duration = (seconds: number | null | undefined): string => {
  if (seconds === null || seconds === undefined) return "—";
  const h = Math.floor(seconds / 3600);
  const m = Math.floor((seconds % 3600) / 60);
  const s = Math.floor(seconds % 60);
  return h > 0 ? `${h}h ${m}m` : m > 0 ? `${m}m ${s}s` : `${s}s`;
};
