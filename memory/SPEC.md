# Gold Paper Terminal — XAUUSDT educational paper-trading SCALPER

## What it is
Single-page MT5-inspired dark trading terminal for XAUUSDT (gold), tuned for
**1-minute scalping**. A backend engine polls real Binance gold market data,
scores a 12-confirmation confluence signal (BUY / SELL / WAIT + confidence %),
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
  a list of 12 weighted vote functions (weights sum to 120): EMA Trend 14,
  Multi-Timeframe Trend 14, MACD 11, Market Structure 11, RSI 10, ADX 10,
  Support/Resistance 10, VWAP 8, Bollinger 8, Price Action 8, Volume 6,
  Breakout Quality 10.
  Direction = sign of net vote, confidence = |net| × 1.2 capped 97.
  `plan_levels(dir, entry, snap, cfg)` builds SL (max of `atr_sl_mult`×ATR and
  the structure stop, capped 2×ATR) and TP (`base_rr` + ADX bonus, pulled back
  before opposing S/R). 10 entry gates: confidence, ADX, ATR% band, R:R, not WAIT,
  not choppy, no opposing fake breakout, higher-timeframe alignment, extension, volume.
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
- `SignalPanel` — confidence bar, 10 entry gates, 12-confirmation breakdown, SL/TP
  rationale
- `WalletPanel` — wallet stats incl. today's P&L and max hold, active-trade card
  with entry/SL/TP/live, progress bar, held + auto-cut countdown, and
  break-even / partial / trailing state badges
- `SettingsPanel` — dialog: kill switch, entry timeframe, and every entry,
  sizing, management and circuit-breaker value, plus "restore scalping defaults"
- `TradeHistory` — dense blotter, expandable "Why" row (opened / SL-TP / closed +
  management log)
- `lib/speech.ts` — Web Speech API wrapper (no API key). Reads the signal summary,
  all 12 confirmation comments, gate results and SL/TP rationale; auto-announces
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

Startup seeding is non-destructive: it creates missing defaults and indexes but
never deletes legacy wallets or trades, which keeps Atlas data safe across pod restarts.

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

## Update — top-row layout
- The dashboard's top row is now a single grid row: `ActivePositionPanel`
  (left, `lg:col-span-5`, testid `active-position-panel`) beside `SignalBanner`
  (right, `lg:col-span-7`). The active-position block was moved out of
  `WalletPanel`, which is now wallet stats only (`wallet`, `config` props).

## Update — consistent XAU/USD feed + scalping engine upgrade
- **Single gold source.** `lib/market.py` provider chain: `binance-futures`
  (fapi, XAUUSDT) → `binance-futures-www` (https://www.binance.com/fapi/v1 mirror with a browser
  UA, same XAUUSDT market — this is what works from this pod, fapi returns 451) →
  `binance-gold-proxy` (PAXGUSDT, labelled "PAXGUSDT GOLD PROXY (not XAU/USD)", last resort).
  REST candles, WS ticks and the forming candle always come from the SAME provider symbol; live
  data is tagged with its provider id and dropped when the provider changes, and a tick older
  than `STALE_AFTER` (15s) is reported stale instead of being shown as live.
- WebSocket (`fstream`, trade + kline 1m/5m/15m/30m/1h) is rebound to the active provider,
  auto-reconnects with backoff, and `feed_status` exposes display_symbol, is_proxy, live_source,
  ws_connected, ws_reconnects, stale, tick_age_seconds (UI shows "ws live/rest/stale" + a
  "gold proxy" badge).
- Indicators: added EMA21 and `indicators.breakout()` — breakout quality, fake-breakout
  detection, chop via directional efficiency; exposed in the snapshot and Signal (`breakout`).
- Strategy: MTF now 1m→[1m,5m,15m,30m,1h] and 5m→[5m,15m,30m,1h]; new weighted confirmation
  "Breakout Quality" (TOTAL_WEIGHT 120, confidence rescaled); new hard gates — not choppy, no
  fake break against us, higher timeframes not opposed (needs 2+ strong opposing TFs to block),
  price not over-extended (>2.2 ATR from EMA21), volume ≥ 0.6x average. SL/TP rationale now also
  states what invalidates the setup and the main risk.
- Wallet adds `profit_factor` and `max_drawdown_pct`; chart overlays EMA9/21/50/200, VWAP,
  Bollinger, entry/SL/TP plus break-even and trailing-stop lines.

## Update — invite mode, affiliates, coupons and withdrawals
- Admin Website/Invites settings now include `invite_mode_enabled`: ON keeps registration
  invite-only; OFF allows open registration while the separate `allow_registration` switch can
  still close registration completely. `GET /api/auth/registration-policy` keeps register-page
  copy synchronized with both switches.
- Every account has a permanent one-level referral code. `/register?ref=CODE` stores
  `referred_by_user_id` once at account creation; invalid codes and self-referrals are rejected.
  `GET /api/affiliate/summary` exposes the member's link, referred/paid counts and balances.
- The global affiliate rate defaults to 20% and is adjustable in Admin → Affiliate. Commission is
  credited from the final amount only after Razorpay signature verification, for every purchase
  and renewal. Manual admin grants never create commission. `affiliate_earnings` is idempotent by
  payment id and `affiliate_accounts` tracks earned, available, pending and paid balances.
- Admin → Coupons supports percentage discount, total claim limit, expiry, active state and eligible
  plans. Coupon claims are atomically reserved when a Razorpay order is created and converted to
  used only after verified payment; the payment stores original amount, discount and coupon code.
- Members can save bank account holder, bank, account number and IFSC on `/affiliate`, then request
  any amount up to their available commission. Admin → Affiliate can approve, reject or mark each
  request paid; rejection returns the reserved amount to available balance.
- New collections: `coupons`, `affiliate_accounts`, `affiliate_earnings`,
  `affiliate_withdrawals`. New routers: `routers/affiliate.py` and
  `routers/admin_commerce.py`; billing remains the only path that creates paid commission.

## Update — private MT5 Expert Advisor execution
- Paper trading remains unchanged. Subscribed users can open `/mt5` and connect one private MT5
  demo or live account through a custom Expert Advisor bridge. The app never stores the MT5 master
  password: it issues a one-time, tenant-scoped bridge token, stores only its SHA-256 hash, and lets
  the EA poll outbound over HTTPS. Disconnecting revokes the token.
- Initial provider is the downloadable `frontend/public/GoldTerminalBridge.mq5`; MetaApi is a planned
  optional second adapter after the EA rollout is validated. The EA requires the broker's MT5 terminal
  on an always-on Windows VPS, Algo Trading enabled, the app origin added to MT5's WebRequest allowlist,
  and the exact MT5 login/server entered in the web connection form.
- Only the canonical XAU/USD family is permitted. The bridge accepts exact broker-discovered aliases
  `XAUUSD`, `GOLD`, and short suffix forms such as `XAUUSD.m`; arbitrary instruments are rejected by
  both backend and EA. One bot-managed position may be open per connected account.
- Users choose a fixed lot with no SaaS/admin cap. Every entry still must satisfy the broker's volume
  min/max/step, full-trading permission, free margin, spread (maximum 15% of ATR), directional SL/TP,
  minimum stop distance, account trading permission, Algo Trading, session, daily-loss, hourly-trade,
  signal-gate, and one-position checks.
- Dashboard presence controls **new entries only**. `/` and `/mt5` heartbeat every 10 seconds; the
  backend requires presence within 30 seconds both when queuing and when the EA polls an entry.
  Closing/hiding the dashboard therefore blocks and cancels new entries. Existing positions continue
  management regardless of presence.
- The EA places broker-side SL and TP with every entry, then independently manages partial take-profit,
  break-even, ATR trailing stop and the hard max-hold autocut on every tick/timer. The backend also
  queues momentum-fade and time-cap exits. If the API is unavailable, broker SL/TP and local EA rules
  continue; if the Windows VPS/MT5 terminal is offline, only broker-hosted SL/TP can execute.
- Commands are tenant-bound and idempotent (`idempotency_key` unique), expire quickly for entries,
  and move through pending → dispatched → confirmed/rejected/cancelled. The EA treats repeated entry
  and close commands idempotently. Heartbeats reconcile account state and the current MT5 position.
- Demo MT5 is included with a normal subscription. Live MT5 requires a separate `mt5_live` plan,
  seeded as `mt5-live-monthly` and editable in Admin → MT5. Razorpay verification activates or renews
  `mt5_live_subscription`; expiry disables new live entries. Admin can monitor all connected accounts
  and remotely disable auto-entry without interrupting protective management.
- New collections: `mt5_accounts`, `mt5_commands`, `mt5_positions`. New modules:
  `models/mt5.py`, `lib/mt5_execution.py`, `routers/mt5.py`; the engine calls the MT5 coordinator each
  cycle without coupling or disabling the paper-trading path.
