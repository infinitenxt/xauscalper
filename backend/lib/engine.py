"""Paper-trading engine: state, background loop, trade lifecycle.

Educational only — no real orders are ever placed. Tuned for scalping: the
engine evaluates every supported timeframe each cycle so the dashboard can show
a signal for whichever timeframe the user selects, but it only auto-opens trades
from the configured primary timeframe (default 1m).

Risk layer, in the order it applies:
  1. circuit breakers   — kill switch, daily loss cap, trades/hour, loss streak
  2. entry gates        — confluence + ADX + volatility + R:R (lib/strategy.py)
  3. stale-entry guard  — never chase a move that already ran toward target
  4. in-trade managment — break-even, partial TP, trailing stop, hard time cap
"""
from __future__ import annotations

import asyncio
import logging
import time
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

from lib import market, narrator, settings as settings_mod, strategy
from lib.db import db

logger = logging.getLogger("engine")

STARTING_BALANCE = 10_000.0
LOOP_SECONDS = 3.0
WALLET_ID = "main"

_signals: Dict[str, Dict[str, Any]] = {}
_last_eval: Dict[str, float] = {}
_task: Optional[asyncio.Task] = None
_lock = asyncio.Lock()
_last_block_reason: str = ""


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _aware(dt: Any) -> Optional[datetime]:
    if isinstance(dt, datetime):
        return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)
    return None


def _clean(doc: Dict[str, Any]) -> Dict[str, Any]:
    return {k: v for k, v in doc.items() if k != "_id"}


# ------------------------------------------------------------------- wallet
async def get_wallet() -> Dict[str, Any]:
    doc = await db.wallet.find_one({"id": WALLET_ID})
    if not doc:
        doc = {
            "id": WALLET_ID,
            "balance": STARTING_BALANCE,
            "starting_balance": STARTING_BALANCE,
            "realized_pnl": 0.0,
            "wins": 0,
            "losses": 0,
            "trades_count": 0,
            "created_at": _now(),
        }
        await db.wallet.insert_one(dict(doc))
    return _clean(doc)


async def reset_all() -> Dict[str, Any]:
    await db.trades.delete_many({})
    await db.signals.delete_many({})
    await db.wallet.delete_many({})
    return await get_wallet()


async def wallet_view(open_trade: Optional[Dict[str, Any]], price: Optional[float]) -> Dict[str, Any]:
    w = await get_wallet()
    unrealized = _pnl(open_trade, price) if (open_trade and price) else 0.0
    total = w["wins"] + w["losses"]
    return {
        **w,
        "unrealized_pnl": round(unrealized, 2),
        "equity": round(w["balance"] + unrealized, 2),
        "win_rate": round(w["wins"] / total * 100, 1) if total else 0.0,
        "return_pct": round(
            (w["balance"] + unrealized - w["starting_balance"]) / w["starting_balance"] * 100, 2
        ),
        "day_pnl": round(await _day_pnl(), 2),
        "open_position": bool(open_trade),
    }


async def _day_pnl() -> float:
    start = _now().replace(hour=0, minute=0, second=0, microsecond=0)
    docs = await db.trades.find({"status": "CLOSED", "closed_at": {"$gte": start}}).to_list(500)
    return sum(float(d.get("pnl") or 0.0) for d in docs)


# ------------------------------------------------------------------- trades
def _pnl(trade: Optional[Dict[str, Any]], price: Optional[float]) -> float:
    if not trade or not price:
        return 0.0
    sign = 1 if trade["direction"] == "BUY" else -1
    return (price - trade["entry"]) * sign * trade["qty"] + float(trade.get("partial_pnl") or 0.0)


async def get_open_trade() -> Optional[Dict[str, Any]]:
    doc = await db.trades.find_one({"status": "OPEN"})
    return _clean(doc) if doc else None


async def trade_history(limit: int = 60) -> List[Dict[str, Any]]:
    docs = await db.trades.find({"status": "CLOSED"}).sort("closed_at", -1).to_list(limit)
    return [_clean(d) for d in docs]


def _decorate_open(trade: Dict[str, Any], price: Optional[float]) -> Dict[str, Any]:
    out = dict(trade)
    if price:
        pnl = _pnl(trade, price)
        out["current_price"] = price
        out["unrealized_pnl"] = round(pnl, 2)
        out["unrealized_pnl_pct"] = round(pnl / trade["risk_amount"] * 100, 2) if trade["risk_amount"] else 0.0
        out["r_multiple"] = (
            round((price - trade["entry"]) * (1 if trade["direction"] == "BUY" else -1) / trade["r_distance"], 2)
            if trade.get("r_distance")
            else 0.0
        )
        span = abs(trade["tp"] - trade["entry"]) or 1
        prog = (price - trade["entry"]) * (1 if trade["direction"] == "BUY" else -1) / span
        out["tp_progress_pct"] = round(max(0.0, min(100.0, prog * 100)), 1)
    opened = _aware(trade.get("opened_at"))
    timeout = _aware(trade.get("timeout_at"))
    now = _now()
    out["age_seconds"] = int((now - opened).total_seconds()) if opened else 0
    out["seconds_to_timeout"] = max(0, int((timeout - now).total_seconds())) if timeout else 0
    return out


async def open_trade(signal: Dict[str, Any], price: float, cfg: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    wallet = await get_wallet()
    sl, tp = signal.get("sl"), signal.get("tp")
    if sl is None or tp is None:
        return None
    sl_dist = abs(price - sl)
    if sl_dist <= 0:
        return None
    risk_pct = float(cfg["risk_per_trade_pct"]) / 100
    risk_amount = wallet["balance"] * risk_pct
    qty = risk_amount / sl_dist
    notional = qty * price
    cap = wallet["balance"] * float(cfg["max_leverage"])
    capped = False
    if notional > cap:
        qty = cap / price
        notional = cap
        risk_amount = qty * sl_dist
        capped = True

    direction = signal["direction"]
    aligned = [
        c for c in signal["confirmations"]
        if c["direction"] == ("BULLISH" if direction == "BUY" else "BEARISH")
    ]
    entry_reasons = [
        signal["summary"],
        f"Confluence score {signal['confidence']:.1f}% (bull {signal['bull_score']} vs bear "
        f"{signal['bear_score']}) on the {signal['timeframe']} timeframe, above the "
        f"{float(cfg['confidence_threshold']):.0f}% auto-trade threshold.",
    ] + [f"{c['name']}: {c['detail']}" for c in aligned]
    risk_reasons = list(signal.get("level_reasons", [])) + [
        f"Position sized to risk {float(cfg['risk_per_trade_pct']):.2f}% of the ${wallet['balance']:,.2f} "
        f"paper balance (${risk_amount:,.2f}) over a {sl_dist:.2f} stop distance → {qty:.4f} oz "
        f"(${notional:,.2f} notional).",
        f"Planned reward:risk is {signal['rr']:.2f}, so one winner covers "
        f"{signal['rr']:.2f} losers of the same size.",
        f"Scalp plan: break even at +{float(cfg['breakeven_at_r']):.2f}R, bank "
        f"{float(cfg['partial_tp_fraction']) * 100:.0f}% at +{float(cfg['partial_tp_at_r']):.2f}R, "
        f"trail {float(cfg['trail_atr_mult'])}x ATR from +{float(cfg['trail_start_r']):.2f}R, and cut the "
        f"trade at {int(cfg['max_hold_minutes'])} minutes whatever happens.",
    ]
    if capped:
        risk_reasons.append(f"Size capped at {float(cfg['max_leverage']):.0f}x notional leverage.")

    hold_seconds = strategy.timeout_seconds(signal["timeframe"], float(cfg["max_hold_minutes"]))
    trade = {
        "id": str(uuid.uuid4()),
        "symbol": market.feed_status.get("symbol") or "XAUUSDT",
        "direction": direction,
        "status": "OPEN",
        "timeframe": signal["timeframe"],
        "entry": round(price, 2),
        "sl": round(sl, 2),
        "tp": round(tp, 2),
        "initial_sl": round(sl, 2),
        "qty": round(qty, 5),
        "initial_qty": round(qty, 5),
        "notional": round(notional, 2),
        "risk_amount": round(risk_amount, 2),
        "r_distance": round(sl_dist, 4),
        "rr_planned": signal["rr"],
        "confidence": signal["confidence"],
        "atr": round(signal.get("atr") or 0.0, 4),
        "trailing_active": False,
        "breakeven_done": False,
        "partial_done": False,
        "partial_pnl": 0.0,
        "best_r": 0.0,
        "max_hold_minutes": int(cfg["max_hold_minutes"]),
        "opened_at": _now(),
        "timeout_at": _now() + timedelta(seconds=hold_seconds),
        "entry_reasons": entry_reasons,
        "risk_reasons": risk_reasons,
        "ai_explanation": None,
        "ai_status": "pending",
        "management_log": [
            f"{_now().strftime('%H:%M:%S')} UTC — opened {direction} {qty:.4f} oz at {price:.2f} "
            f"(SL {sl:.2f} / TP {tp:.2f}), hard time cap {int(cfg['max_hold_minutes'])} min."
        ],
        "exit_price": None,
        "exit_reason": None,
        "exit_explanation": None,
        "pnl": None,
        "pnl_pct": None,
        "r_multiple": None,
        "closed_at": None,
        "duration_seconds": None,
    }
    await db.trades.insert_one(dict(trade))
    logger.info("paper trade opened: %s %s @ %s", direction, trade["qty"], price)
    # AI explanation is generated out-of-band so entry latency stays at zero.
    asyncio.create_task(_narrate(trade, signal, aligned))
    return _clean(trade)


async def _narrate(
    trade: Dict[str, Any], signal: Dict[str, Any], aligned: List[Dict[str, Any]]
) -> None:
    """Ask the LLM why this trade was taken, then patch the trade document."""
    try:
        text, status = await narrator.explain_trade(
            {
                "trade_id": trade["id"],
                "symbol": trade["symbol"],
                "direction": trade["direction"],
                "timeframe": trade["timeframe"],
                "entry": trade["entry"],
                "sl": trade["sl"],
                "tp": trade["tp"],
                "rr": trade["rr_planned"],
                "confidence": trade["confidence"],
                "atr": trade["atr"],
                "qty": trade["qty"],
                "risk_amount": trade["risk_amount"],
                "bull_score": signal.get("bull_score"),
                "bear_score": signal.get("bear_score"),
                "aligned_confirmations": aligned,
                "structure": signal.get("structure"),
                "pattern": signal.get("pattern"),
                "level_reasons": signal.get("level_reasons"),
                "entry_reasons": trade["entry_reasons"],
                "risk_reasons": trade["risk_reasons"],
            }
        )
        await db.trades.update_one(
            {"id": trade["id"]}, {"$set": {"ai_explanation": text, "ai_status": status}}
        )
    except Exception as exc:  # noqa: BLE001
        logger.warning("narration task failed: %s", exc)
        await db.trades.update_one({"id": trade["id"]}, {"$set": {"ai_status": "unavailable"}})


async def close_trade(trade: Dict[str, Any], price: float, reason: str, explanation: str) -> Dict[str, Any]:
    remaining = (price - trade["entry"]) * (1 if trade["direction"] == "BUY" else -1) * trade["qty"]
    total = remaining + float(trade.get("partial_pnl") or 0.0)
    opened = _aware(trade.get("opened_at")) or _now()
    duration = int((_now() - opened).total_seconds())
    r_mult = total / trade["risk_amount"] if trade.get("risk_amount") else 0.0
    wallet = await get_wallet()
    new_balance = wallet["balance"] + remaining
    update = {
        "status": "CLOSED",
        "exit_price": round(price, 2),
        "exit_reason": reason,
        "exit_explanation": explanation,
        "pnl": round(total, 2),
        "pnl_pct": round(total / wallet["balance"] * 100, 3) if wallet["balance"] else 0.0,
        "r_multiple": round(r_mult, 2),
        "closed_at": _now(),
        "duration_seconds": duration,
        "management_log": list(trade.get("management_log", []))
        + [f"{_now().strftime('%H:%M:%S')} UTC — closed at {price:.2f} ({reason}), total P&L ${total:,.2f}."],
    }
    await db.trades.update_one({"id": trade["id"]}, {"$set": update})
    await db.wallet.update_one(
        {"id": WALLET_ID},
        {
            "$set": {"balance": round(new_balance, 2)},
            "$inc": {
                "realized_pnl": round(total, 2),
                "trades_count": 1,
                "wins": 1 if total > 0 else 0,
                "losses": 0 if total > 0 else 1,
            },
        },
    )
    logger.info("paper trade closed: %s pnl=%.2f", reason, total)
    return {**trade, **update}


async def manage_open_trade(
    trade: Dict[str, Any], price: float, signal: Optional[Dict[str, Any]], cfg: Dict[str, Any]
) -> None:
    """SL/TP hits, break-even, partial TP, trailing stop, hard time cap."""
    long = trade["direction"] == "BUY"
    r = trade.get("r_distance") or 1.0
    favorable = (price - trade["entry"]) * (1 if long else -1)
    r_mult = favorable / r

    # ---- stop hit
    if (long and price <= trade["sl"]) or (not long and price >= trade["sl"]):
        moved = abs(trade["sl"] - trade["initial_sl"]) > 1e-9
        at_be = trade.get("breakeven_done") and not trade.get("trailing_active")
        if not moved:
            reason = "STOP LOSS"
            expl = (
                f"Price traded through the protective stop at {trade['sl']:.2f}. The setup was invalidated: "
                "the volatility- and structure-based stop was breached, so the engine took the pre-defined "
                f"1-unit loss (about ${trade['risk_amount']:,.2f}) rather than hoping for a recovery."
            )
        elif at_be:
            reason = "BREAK-EVEN STOP"
            expl = (
                f"The stop had already been pulled to break-even at {trade['sl']:.2f} after the trade went "
                f"{float(cfg['breakeven_at_r']):.2f}R in profit. Price came back, so the trade was closed for "
                "roughly nothing instead of a full loss — this is the break-even rule doing its job."
            )
        else:
            reason = "TRAILING STOP"
            expl = (
                f"Price hit the trailing stop at {trade['sl']:.2f}, advanced from the original "
                f"{trade['initial_sl']:.2f}. The move reversed after running in our favour, so the engine "
                "banked the protected portion of the run instead of giving it all back."
            )
        await close_trade(trade, trade["sl"], reason, expl)
        return

    # ---- target hit
    if (long and price >= trade["tp"]) or (not long and price <= trade["tp"]):
        await close_trade(
            trade,
            trade["tp"],
            "TAKE PROFIT",
            f"Target reached at {trade['tp']:.2f}. This was the level chosen at entry from the "
            f"{trade['rr_planned']:.2f} reward:risk plan and the nearest opposing structure, so the engine "
            "banked the planned reward rather than pressing for more.",
        )
        return

    # ---- hard scalper time cap
    timeout_at = _aware(trade.get("timeout_at"))
    if timeout_at and _now() >= timeout_at:
        await close_trade(
            trade,
            price,
            "TIME CAP",
            f"Hard scalper time cap: the trade held {int(trade.get('max_hold_minutes') or 0)} minutes without "
            f"reaching target or stop. A scalp that has not paid out in that window has lost its edge and is "
            f"only tying up risk, so the engine closed it at {price:.2f}.",
        )
        return

    updates: Dict[str, Any] = {}
    log: List[str] = []
    best_r = max(float(trade.get("best_r") or 0.0), r_mult)
    if best_r > float(trade.get("best_r") or 0.0):
        updates["best_r"] = round(best_r, 3)

    # ---- partial take-profit
    partial_at = float(cfg["partial_tp_at_r"])
    fraction = float(cfg["partial_tp_fraction"])
    if not trade.get("partial_done") and fraction > 0 and r_mult >= partial_at:
        close_qty = trade["qty"] * fraction
        booked = (price - trade["entry"]) * (1 if long else -1) * close_qty
        wallet = await get_wallet()
        updates["qty"] = round(trade["qty"] - close_qty, 5)
        updates["partial_done"] = True
        updates["partial_pnl"] = round(float(trade.get("partial_pnl") or 0.0) + booked, 2)
        await db.wallet.update_one(
            {"id": WALLET_ID},
            {"$set": {"balance": round(wallet["balance"] + booked, 2)}, "$inc": {"realized_pnl": round(booked, 2)}},
        )
        log.append(
            f"{_now().strftime('%H:%M:%S')} UTC — hit +{partial_at:.2f}R, banked {fraction * 100:.0f}% of the "
            f"position ({close_qty:.4f} oz) at {price:.2f} for ${booked:,.2f}; the rest runs to target."
        )
        trade = {**trade, **updates}

    # ---- break-even stop
    be_at = float(cfg["breakeven_at_r"])
    if not trade.get("breakeven_done") and r_mult >= be_at:
        buffer_ = 0.05 * r
        be_sl = trade["entry"] + buffer_ if long else trade["entry"] - buffer_
        improved = be_sl > trade["sl"] if long else be_sl < trade["sl"]
        if improved:
            updates["sl"] = round(be_sl, 2)
            updates["breakeven_done"] = True
            log.append(
                f"{_now().strftime('%H:%M:%S')} UTC — reached +{be_at:.2f}R, stop moved to break-even "
                f"{be_sl:.2f}. From here the worst case is a scratch, not a loss."
            )
            trade = {**trade, **updates}

    # ---- trailing stop
    if r_mult >= float(cfg["trail_start_r"]):
        atr_val = trade.get("atr") or r
        mult = float(cfg["trail_atr_mult"])
        candidate = price - mult * atr_val if long else price + mult * atr_val
        floor_ = trade["entry"] + 0.3 * r if long else trade["entry"] - 0.3 * r
        new_sl = max(candidate, floor_) if long else min(candidate, floor_)
        improved = new_sl > trade["sl"] + 1e-9 if long else new_sl < trade["sl"] - 1e-9
        if improved:
            updates["sl"] = round(new_sl, 2)
            updates["trailing_active"] = True
            log.append(
                f"{_now().strftime('%H:%M:%S')} UTC — {r_mult:.2f}R in profit, trailing stop advanced to "
                f"{new_sl:.2f} ({mult}x ATR behind price) to protect gains."
            )

    # ---- momentum fade early exit
    opened = _aware(trade.get("opened_at")) or _now()
    elapsed = (_now() - opened).total_seconds()
    total_hold = strategy.timeout_seconds(trade["timeframe"], float(trade.get("max_hold_minutes") or 15))
    if (
        signal
        and elapsed > total_hold * 0.35
        and favorable < 0
        and signal.get("direction") not in (trade["direction"], "WAIT")
        and float(signal.get("confidence", 0)) >= 55
    ):
        await close_trade(
            trade,
            price,
            "MOMENTUM FADE",
            f"The signal engine flipped to {signal['direction']} at {signal['confidence']:.1f}% confidence "
            f"while this {trade['direction']} was underwater. Holding against a confirmed opposite read is "
            f"worse risk than taking a partial loss, so the engine exited early at {price:.2f}.",
        )
        return

    if updates:
        if log:
            updates["management_log"] = list(trade.get("management_log", [])) + log
        await db.trades.update_one({"id": trade["id"]}, {"$set": updates})


# ------------------------------------------------------------ circuit breakers
async def guards(cfg: Dict[str, Any]) -> Dict[str, Any]:
    """Account-level protections evaluated before any entry."""
    wallet = await get_wallet()
    now = _now()
    checks: List[Dict[str, Any]] = []

    enabled = bool(cfg["auto_trade_enabled"])
    checks.append(
        {
            "name": "Auto-trading enabled",
            "passed": enabled,
            "detail": "kill switch is ON — engine will not open trades" if not enabled else "engine armed",
        }
    )

    day_pnl = await _day_pnl()
    limit = -wallet["starting_balance"] * float(cfg["daily_loss_limit_pct"]) / 100
    checks.append(
        {
            "name": f"Daily loss under {float(cfg['daily_loss_limit_pct']):.2f}%",
            "passed": day_pnl > limit,
            "detail": f"today's realized P&L ${day_pnl:,.2f} vs limit ${limit:,.2f}",
        }
    )

    hour_ago = now - timedelta(hours=1)
    recent = await db.trades.count_documents({"opened_at": {"$gte": hour_ago}})
    max_per_hour = int(cfg["max_trades_per_hour"])
    checks.append(
        {
            "name": f"Under {max_per_hour} trades/hour",
            "passed": recent < max_per_hour,
            "detail": f"{recent} trade(s) opened in the last 60 minutes",
        }
    )

    streak_needed = int(cfg["consecutive_loss_pause"])
    pause_min = int(cfg["pause_minutes_after_losses"])
    last = await db.trades.find({"status": "CLOSED"}).sort("closed_at", -1).to_list(streak_needed)
    streak = 0
    for d in last:
        if float(d.get("pnl") or 0.0) <= 0:
            streak += 1
        else:
            break
    paused = False
    detail = f"current losing streak {streak}/{streak_needed}"
    if streak >= streak_needed and last:
        last_close = _aware(last[0].get("closed_at"))
        if last_close and now < last_close + timedelta(minutes=pause_min):
            paused = True
            mins = int((last_close + timedelta(minutes=pause_min) - now).total_seconds() // 60) + 1
            detail = f"{streak} losses in a row — cooling off for another ~{mins} min"
    checks.append({"name": f"No {streak_needed}-loss cool-off", "passed": not paused, "detail": detail})

    cooldown = int(cfg["cooldown_seconds"])
    last_closed = await db.trades.find({"status": "CLOSED"}).sort("closed_at", -1).to_list(1)
    cd_ok, cd_detail = True, f"cooldown {cooldown}s after each close"
    if last_closed:
        lc = _aware(last_closed[0].get("closed_at"))
        if lc and (now - lc).total_seconds() < cooldown:
            cd_ok = False
            cd_detail = f"{int(cooldown - (now - lc).total_seconds())}s left of the {cooldown}s cooldown"
    checks.append({"name": "Cooldown elapsed", "passed": cd_ok, "detail": cd_detail})

    blocked = [c for c in checks if not c["passed"]]
    return {
        "checks": checks,
        "blocked": bool(blocked),
        "block_reason": blocked[0]["name"] if blocked else "",
        "day_pnl": round(day_pnl, 2),
        "trades_last_hour": recent,
        "loss_streak": streak,
    }


def stale_entry(signal: Dict[str, Any], price: float, cfg: Dict[str, Any]) -> Optional[str]:
    """Refuse to chase: has price already run too far toward target since the last close?"""
    ref = signal.get("last_closed")
    tp = signal.get("tp")
    if ref is None or tp is None or tp == ref:
        return None
    progress = (price - ref) / (tp - ref) * 100
    limit = float(cfg["stale_entry_max_pct"])
    if progress > limit:
        return (
            f"price already travelled {progress:.0f}% of the way from {ref:.2f} to target {tp:.2f} "
            f"(limit {limit:.0f}%) — entering here pays the worst price of the move"
        )
    return None


# --------------------------------------------------------------------- loop
async def evaluate(timeframe: str, cfg: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    cfg = cfg or await settings_mod.get_settings()
    needed = dict.fromkeys([timeframe] + strategy.MTF_MAP.get(timeframe, []))
    candles_by_tf: Dict[str, List[Dict[str, float]]] = {}
    for tf in needed:
        candles_by_tf[tf] = await market.get_klines(tf, 300)
    price = await market.get_price() or (
        candles_by_tf[timeframe][-1]["close"] if candles_by_tf.get(timeframe) else 0.0
    )
    signal = strategy.analyze(timeframe, candles_by_tf, price, cfg)
    signal["generated_at"] = _now().isoformat()
    _signals[timeframe] = signal
    _last_eval[timeframe] = time.time()
    return signal


async def get_signal(timeframe: str, max_age: float = 10.0) -> Dict[str, Any]:
    cached = _signals.get(timeframe)
    if cached and (time.time() - _last_eval.get(timeframe, 0)) < max_age:
        return cached
    return await evaluate(timeframe)


async def cycle() -> None:
    global _last_block_reason
    async with _lock:
        cfg = await settings_mod.get_settings(refresh=True)
        for tf in market.INTERVALS:
            try:
                await evaluate(tf, cfg)
            except Exception as exc:  # noqa: BLE001
                logger.warning("evaluate %s failed: %s", tf, exc)

        primary_tf = str(cfg["primary_timeframe"])
        primary = _signals.get(primary_tf)
        price = await market.get_price()
        if not price:
            return

        open_t = await get_open_trade()
        if open_t:
            await manage_open_trade(open_t, price, primary, cfg)
            return

        if not primary or not primary.get("tradeable"):
            _last_block_reason = "" if not primary else "entry gates not met"
            return

        g = await guards(cfg)
        if g["blocked"]:
            _last_block_reason = g["block_reason"]
            return

        stale = stale_entry(primary, price, cfg)
        if stale:
            _last_block_reason = f"stale entry: {stale}"
            return

        _last_block_reason = ""
        trade = await open_trade(primary, price, cfg)
        if trade:
            await db.signals.insert_one(
                {
                    "id": str(uuid.uuid4()),
                    "timeframe": primary["timeframe"],
                    "direction": primary["direction"],
                    "confidence": primary["confidence"],
                    "price": price,
                    "trade_id": trade["id"],
                    "created_at": _now(),
                }
            )


async def _loop() -> None:
    await asyncio.sleep(2)
    while True:
        try:
            await cycle()
        except asyncio.CancelledError:
            raise
        except Exception as exc:  # noqa: BLE001
            logger.warning("engine cycle error: %s", exc)
        await asyncio.sleep(LOOP_SECONDS)


def start() -> None:
    global _task
    if _task is None or _task.done():
        _task = asyncio.create_task(_loop())


async def stop() -> None:
    global _task
    if _task and not _task.done():
        _task.cancel()
        try:
            await _task
        except (asyncio.CancelledError, Exception):  # noqa: BLE001
            pass
    _task = None


async def config() -> Dict[str, Any]:
    cfg = await settings_mod.get_settings()
    return {
        **cfg,
        "starting_balance": STARTING_BALANCE,
        "timeframes": market.INTERVALS,
        "loop_seconds": LOOP_SECONDS,
        "disclaimer": (
            "Educational paper trading only. No real orders are placed and no signal is a "
            "guarantee — gold can move against any confirmed setup."
        ),
    }


async def dashboard(timeframe: str) -> Dict[str, Any]:
    cfg = await settings_mod.get_settings()
    signal = await get_signal(timeframe)
    price = await market.get_price()
    open_t = await get_open_trade()
    g = await guards(cfg)
    return {
        "feed": dict(market.feed_status),
        "ticker": {
            "symbol": market.feed_status.get("symbol") or "XAUUSDT",
            "price": price,
            **(await market.get_stats_24h()),
        },
        "signal": signal,
        "wallet": await wallet_view(open_t, price),
        "open_trade": _decorate_open(open_t, price) if open_t else None,
        "history": await trade_history(40),
        "config": await config(),
        "guards": {**g, "last_block_reason": _last_block_reason},
        "server_time": _now().isoformat(),
    }
