# Gold Paper Terminal — XAUUSDT educational paper-trading SCALPER

## What it is
Single-page MT5-inspired dark trading terminal for XAUUSDT (gold), tuned for
**1-minute scalping**. A backend engine polls real Binance gold market data,
scores an 11-confirmation confluence signal (BUY / SELL / WAIT + confidence %),
and auto-opens **virtual** paper trades when confidence ≥ 80%, every entry gate
passes, and no account circuit breaker is tripped. No real orders, no auth — one
shared paper account. The browser speaks every signal comment and trade
explanation aloud and plays distinct alert tones on entry / TP / SL.

## Market data (IMPORTANT deviation)
`backend/lib/market.py` is a provider chain:
1. `binance-futures` — `https://fapi.binance.com/fapi/v1`, symbol `XAUUSDT` (primary)
2. `binance-gold-spot` — `https://data-api.binance.vision/api/v3`, symbol `PAXGUSDT` (fallback)

Binance Futures answers **HTTP 451 (restricted location)** from this pod's region,
so the chain automatically runs on the fallback: Binance's public spot data mirror
using PAXGUSDT (1:1 physically-backed gold token, ~same price as spot gold per oz).
Prices/candles are therefore **real Binance gold data**, just not the futures book.
The UI shows the active provider in the ticker bar and a visible amber note when
degraded. If the app is ever deployed from an unrestricted region, provider 1 is
picked automatically with no code change. Data is fetched via REST polling (not
WebSocket) — the engine loop is 5s, dashboard refetch 4s, candles 6s.

## Backend
- `lib/market.py` — provider chain, klines/price/24h stats, caching, feed status.
- `lib/indicators.py` — pure functions: EMA, RSI, MACD, Bollinger, ATR, ADX,
  VWAP, swing points, support/resistance clustering, market structure, candle
  patterns, `snapshot()`.
- `lib/settings.py` — **runtime-editable** engine settings persisted in Mongo
  (`settings` collection, doc `id="main"`), with per-key safe bounds so a bad
  edit cannot brick the engine. Scalping defaults: 1m entries, 80% threshold,
  ADX ≥ 20, min R:R 1.3, risk 1%, SL 0.9×ATR, base R:R 1.4, break-even at +0.5R,
  partial TP 50% at +1.0R, trail 0.8×ATR from +1.0R, **max hold 15 min**,
  cooldown 60s, daily loss limit 3%, max 6 trades/hour, 3-loss → 30 min pause,
  stale-entry guard 25%.
- `lib/strategy.py` — the signal engine, now settings-driven. `CONFIRMATIONS` is
  a list of 11 weighted vote functions (weights sum to 100): EMA Trend 14,
  Multi-Timeframe Trend 14, MACD 11, Market Structure 11, RSI 10, ADX 10,
  Support/Resistance 10, VWAP 8, Bollinger 8, Price Action 8, Volume 6.
  Direction = sign of net vote, confidence = |net| × 1.2 capped 97.
  `plan_levels(dir, entry, snap, cfg)` builds SL (max of `atr_sl_mult`×ATR and
  the structure stop, capped 2×ATR) and TP (`base_rr` + ADX bonus, pulled back
  before opposing S/R). 5 entry gates: confidence, ADX, ATR% band, R:R, not WAIT.
  `analyze()` also returns `last_closed` for the stale-entry guard. Adding a
  confirmation = append one function + weight.
- `lib/engine.py` — wallet, trade lifecycle, background loop (3s). Evaluates all
  5 timeframes each cycle; auto-trades only from `settings.primary_timeframe`.
  Risk layer in order: **circuit breakers** (`guards()` — kill switch, daily loss
  cap, trades/hour, consecutive-loss cool-off, cooldown) → **entry gates** →
  **stale-entry guard** (`stale_entry()`, refuses to chase) → **in-trade
  management** (`manage_open_trade()`: SL/TP hit, partial TP, break-even stop,
  trailing stop, hard time cap, momentum-fade exit). Exit reasons are distinct:
  STOP LOSS / BREAK-EVEN STOP / TRAILING STOP / TAKE PROFIT / TIME CAP /
  MOMENTUM FADE / MANUAL CLOSE. Every trade stores `entry_reasons`,
  `risk_reasons`, `management_log`, `exit_reason`, `exit_explanation`.
  Partial TP credits the wallet immediately and stores `partial_pnl`; final
  `pnl` = partial + remaining.
- `routers/trading.py` (all under `/api`): `GET /market/feed`, `/market/ticker`,
  `/market/candles?timeframe&limit`, `/signal?timeframe`, `/wallet`, `/trades`,
  `/engine/config`, `/engine/guards`, `/settings`, `/dashboard?timeframe`;
  `PUT /settings`; `POST /trades/{id}/close`, `/settings/reset`, `/engine/reset`.
- Models in `models/trading.py`, mirrored by `frontend/src/lib/types.ts`.

## AI usage (the only LLM in the app)
`backend/lib/narrator.py` — turns the engine's structured entry facts into a
3–4 sentence human explanation of **why the trade was taken**. Uses the Emergent
Universal key (`EMERGENT_LLM_KEY` in `backend/.env`) via `emergentintegrations`
`LlmChat` → `openai / gpt-5.4`. Called fire-and-forget from `engine._narrate()`
after the trade is already inserted, so entry latency is zero; the trade doc is
then patched with `ai_explanation` + `ai_status` (`pending` → `ai` |
`unavailable`). If the key is missing, the call errors or it exceeds a 25s
timeout, the deterministic reason list is used and `ai_status` says
`unavailable`. Everything else — signals, sizing, SL/TP, exits — stays fully
deterministic; no LLM is in the trading path.

## Voice commentary
`frontend/src/lib/commentary.ts` — 50 static hunter-style lines in 11 mood groups
(strong_bull, bull, strong_bear, bear, waiting, volatile, quiet,
in_trade_winning, in_trade_losing, near_target, blocked). `pickMood()` chooses
the group from live direction, confidence, ATR%, guard-blocked state and open-trade
P&L / progress-to-target; `nextComment()` cycles a group before repeating a line.
The dashboard fires every **5 seconds**, shows the line under the banner
(`data-testid="live-commentary"`) and speaks it only when voice is on and nothing
else is already speaking, so announcements never overlap.

## Auth, subscriptions and admin
- **Auth** (`lib/auth.py`, `routers/auth_routes.py`): bcrypt passwords (passlib),
  httpOnly cookie sessions (`gt_session`, 14 days). **One login per device** —
  `create_session()` deletes every other session for that user, so signing in on
  a new device instantly 401s the old one. Dependencies: `require_user` (401),
  `require_admin` (403), `require_subscription` (**402**).
- **Paywall**: the entire `routers/trading.py` router and `GET /backtest` carry
  `Depends(auth.require_subscription)`. Admins always pass. The frontend guards
  (`components/RouteGuards.tsx`) redirect to `/login` or `/subscribe`, and the
  dashboard also reacts to a mid-session 402/401.
- **Billing** (`routers/billing.py`): plans in Mongo; Razorpay order creation and
  HMAC signature verification run through `asyncio.to_thread` (sync SDK). Keys are
  read **from the DB per request** (admin-entered), never from env. With no keys
  the paid flow is cleanly disabled (503) and an admin grants access manually.
  `activate()` extends from the current expiry when still active.
- **Admin** (`routers/admin.py`, `/admin/*`, all behind `require_admin`): stats,
  user search / enable / disable / promote / demote / delete, grant or revoke a
  subscription (by plan or arbitrary days), plan CRUD, payment log, Razorpay key
  management (secret is write-only), website settings, and active-device list with
  force sign-out. Guards prevent an admin disabling, demoting or deleting itself.
- **Seed** (`backend/seed.py`, idempotent, runs each boot): admin account, three
  plans (Monthly ₹999/30d, Quarterly ₹2499/90d, Yearly ₹7999/365d), site settings,
  indexes. Credentials live in `memory/test_credentials.md`.
- Collections added: `users`, `sessions`, `plans`, `payments`, `site_settings`.
- **Deviation**: the paper-trading engine remains a **single shared** bot — all
  subscribers watch the same wallet, signals and trade history. Per-user wallets
  were not built.

## Session awareness
`lib/market_sessions.py` — Sydney / Tokyo / London / New York windows in UTC,
with liquidity graded PEAK (London × New York overlap, 12:00–16:00 UTC) → HIGH →
MEDIUM → LOW. Exposed at `GET /api/market/sessions` and inside `/api/dashboard`.
The engine adds a **Session liquidity** guard: when `session_filter_enabled`
(default on) and liquidity is LOW, no new trade opens. `components/SessionBar.tsx`
shows a chip per session with open/close countdowns, the overlap badge and the
liquidity grade.

## Backtesting
`lib/backtest.py` + `GET /api/backtest?timeframe&days` (subscribers only, cached
120s, run via `asyncio.to_thread`). Replays the **same** `strategy.analyze` and
management stack (break-even, partial TP, trailing, time cap) over real Binance
gold candles. Conservative by design: entries fill at the signal bar's close, and
a bar spanning both levels is scored as a **stop**. Returns trades, win rate, net
P&L, return %, profit factor, avg R, max drawdown, avg hold, exit-reason
breakdown, an equity curve and the trade list. UI: `components/BacktestPanel.tsx`
(timeframe + 12h/1d/3d/7d range switches, equity-curve area chart, trade table).

## Data model (Mongo)
- `wallet` — one doc `id="main"`: balance, starting_balance (10000), realized_pnl,
  wins, losses, trades_count.
- `settings` — one doc `id="main"`: every runtime-editable engine setting.
- `trades` — one doc per paper trade, `status` OPEN | CLOSED, uuid4 `id`.
- `signals` — a log row each time a signal triggers an auto-trade.

## Frontend
Routes: `/login`, `/register` (`pages/AuthPage.tsx`), `/subscribe`
(`pages/Subscribe.tsx`, plan cards + Razorpay Checkout), `/admin`
(`pages/Admin.tsx`, tabbed panel), `/` → `pages/Dashboard.tsx` behind
`RequireSubscription`. Components:
- `TickerBar` — price with tick flash, 24h stats, equity, today's P&L, AUTO ON/OFF
  badge, feed provider dot, timeframe switcher, reset, settings slot
- `SignalBanner` — compact BUY / SELL / WAIT hero (3xl–4xl type, half its original
  size), colour-flooded frame, glow when armed, confidence with threshold marker,
  ARMED / HOLDING FIRE badge, voice toggle, "Read analysis" button, summary, guard
  block reason, and the rolling 5-second market commentary line
- `PriceChart` — recharts ComposedChart, custom candle shape via range Bar,
  EMA20/EMA50/VWAP/Bollinger, ReferenceLines for Entry/SL/TP (dashed when merely
  planned) **and a live price line** that tracks the current tick, coloured by
  direction and labelled with the price
- `SignalPanel` — confidence bar, 5 entry gates, 11-confirmation breakdown, SL/TP
  rationale
- `WalletPanel` — wallet stats incl. today's P&L and max hold, active-trade card
  with entry/SL/TP/live, progress bar, held + auto-cut countdown, and
  break-even / partial / trailing state badges
- `SettingsPanel` — dialog: kill switch, entry timeframe, and every entry,
  sizing, management and circuit-breaker value, plus "restore scalping defaults"
- `TradeHistory` — dense blotter, expandable "Why" row (opened / SL-TP / closed +
  management log)
- `lib/speech.ts` — Web Speech API wrapper (no API key). Reads the signal summary,
  all 11 confirmation comments, gate results and SL/TP rationale; auto-announces
  on direction change, trade open and trade close. Mute state in localStorage,
  and abbreviations are expanded phonetically (ATR → "A T R", MACD → "mac dee").
- `lib/sound.ts` — WebAudio alert tones: rising two-tone on entry, rising triad on
  take-profit, low descending pair on stop, single blip on neutral exits. Unlocked
  by the first pointer interaction (browser autoplay policy).

Theme: dark by default (`<html class="dark">`), JetBrains Mono Variable.

## Auth / seed
Admin seeded each boot: `admin@goldterminal.app` / `Harsh@10576` (see
`memory/test_credentials.md`). Regular users register at `/register` and need a
subscription — granted by an admin, by a trial-days setting, or via Razorpay.
`POST /api/engine/reset` wipes trades/signals and restores the $10,000 paper
balance (subscribers only).

## Testing notes
- Trades only appear when the live market genuinely produces an 80%+ setup, so
  the history table is legitimately empty on a fresh, quiet market — that is
  correct behaviour, not a bug.
- The 451 futures fallback and REST-instead-of-WebSocket are intentional
  deviations (see above).

## Update — per-user wallets, presence, session backtest split
- Every trading route (`/api/dashboard`, `/api/wallet`, `/api/trades`, `/api/engine/*`,
  `/api/presence`, `/api/backtest`) is scoped to the signed-in subscriber; each user gets
  their own $10,000 paper wallet and private trade history (`trades.user_id`).
- Presence: `db.presence.last_seen` + `PRESENCE_WINDOW=25s`. The engine always manages
  exits (TP/SL/trail/timeout) for open trades, but only OPENS new trades for users seen
  within the window. Frontend pings `POST /api/presence` every 10s while the tab is
  visible and on visibilitychange; `guards.present` drives the header chip
  ("Live · entries armed" / "Idle · exits only", testid `presence-indicator`).
- Backtest returns `session_breakdown[]` (Asian, London, London × New York, New York,
  Off-session) plus `best_session`/`worst_session`, rendered in BacktestPanel
  (testid `backtest-session-split`).
- Frontend `lib/types.ts` mirrors the updated Pydantic models (Trade.user_id/session/
  liquidity, Guards.present, EngineHealth, EngineConfig.presence_window_seconds,
  SessionSplit).

## Update — admin identity, password changes, invite-only sign-up
- Seeded admin is now `Admin` / `admin@infinitenxt.com` / `Harsh@10576`
  (seed.py migrates the legacy `admin@goldterminal.app` doc in place and clears its sessions).
- `POST /api/auth/password` {current_password,new_password}: self-service change, revokes
  other sessions and re-issues the caller's cookie. UI: `ChangePasswordDialog` in the
  dashboard and admin headers (testid `change-password-open-button`).
- `POST /api/admin/users/{id}/password` {new_password}: admin force-reset (Users tab →
  `reset-password-button`).
- Invite-only registration: `db.invites` {email, note, used, invited_by, created_at, used_at}.
  Admin CRUD at `GET/POST /api/admin/invites`, `DELETE /api/admin/invites/{email}`
  (Invites tab). `POST /api/auth/register` returns 403 for an uninvited email, 409 for a
  used invite, and marks the invite used on success. AdminStats gains `invites_pending`.
