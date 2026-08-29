"""Paper-trading engine: per-user wallets and per-user trading settings.

Educational only — no real orders are ever placed.

Architecture
------------
- Market data / candle fetching is shared.
- Market signals are generated from the shared market data.
- Trading configuration is PRIVATE to each user.
- Every user's:
    * confidence threshold
    * ADX requirement
    * RR requirement
    * ATR filters
    * risk %
    * leverage
    * SL/TP management
    * trailing
    * break-even
    * partial TP
    * time cap
    * cooldown
    * daily loss limit
    * trade/hour limit
    * loss-streak protection
  comes from that user's own settings.

Presence rule
-------------
- Existing trades are ALWAYS managed.
- New paper trades require dashboard presence.
- MT5 execution is delegated to mt5_execution.py.

The loop never sleeps permanently; a watchdog restarts it if it dies.
"""
from __future__ import annotations

import asyncio
import logging
import time
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

from lib import (
    market,
    market_sessions,
    mt5_execution,
    narrator,
    settings as settings_mod,
    strategy,
)
from lib.db import db

logger = logging.getLogger("engine")

STARTING_BALANCE = 10_000.0
LOOP_SECONDS = 3.0
PRESENCE_WINDOW = 25.0
WATCHDOG_SECONDS = 30.0

_signals: Dict[str, Dict[str, Any]] = {}
_last_eval: Dict[str, float] = {}
_block_reason: Dict[str, str] = {}

_task: Optional[asyncio.Task] = None
_watchdog: Optional[asyncio.Task] = None
_lock = asyncio.Lock()

_stats: Dict[str, Any] = {
    "started_at": None,
    "cycles": 0,
    "last_cycle_at": None,
    "last_error": "",
    "restarts": 0,
}


# -------------------------------------------------------------------------
# time helpers
# -------------------------------------------------------------------------

def _now() -> datetime:
    return datetime.now(timezone.utc)


def _aware(dt: Any) -> Optional[datetime]:
    if isinstance(dt, datetime):
        return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)
    return None


def _clean(doc: Dict[str, Any]) -> Dict[str, Any]:
    return {k: v for k, v in doc.items() if k != "_id"}


# -------------------------------------------------------------------------
# presence
# -------------------------------------------------------------------------

async def touch_presence(user_id: str) -> None:
    await db.presence.update_one(
        {"user_id": user_id},
        {"$set": {"last_seen": _now()}},
        upsert=True,
    )


async def active_user_ids() -> List[str]:
    cutoff = _now() - timedelta(seconds=PRESENCE_WINDOW)

    docs = await db.presence.find(
        {"last_seen": {"$gte": cutoff}}
    ).to_list(500)

    return [str(d["user_id"]) for d in docs]


async def is_present(user_id: str) -> bool:
    doc = await db.presence.find_one({"user_id": user_id})

    seen = _aware((doc or {}).get("last_seen"))

    return bool(
        seen
        and (_now() - seen).total_seconds() <= PRESENCE_WINDOW
    )


# -------------------------------------------------------------------------
# wallet
# -------------------------------------------------------------------------

async def get_wallet(user_id: str) -> Dict[str, Any]:
    doc = await db.wallets.find_one({"user_id": user_id})

    if not doc:
        doc = {
            "id": str(uuid.uuid4()),
            "user_id": user_id,
            "balance": STARTING_BALANCE,
            "starting_balance": STARTING_BALANCE,
            "realized_pnl": 0.0,
            "wins": 0,
            "losses": 0,
            "trades_count": 0,
            "created_at": _now(),
        }

        await db.wallets.insert_one(dict(doc))

    return _clean(doc)


async def reset_all(user_id: str) -> Dict[str, Any]:
    await db.trades.delete_many({"user_id": user_id})
    await db.wallets.delete_many({"user_id": user_id})

    return await get_wallet(user_id)


async def _day_pnl(user_id: str) -> float:
    start = _now().replace(
        hour=0,
        minute=0,
        second=0,
        microsecond=0,
    )

    docs = await db.trades.find(
        {
            "user_id": user_id,
            "status": "CLOSED",
            "closed_at": {"$gte": start},
        }
    ).to_list(500)

    return sum(
        float(d.get("pnl") or 0.0)
        for d in docs
    )


async def wallet_view(
    user_id: str,
    open_trade: Optional[Dict[str, Any]],
    price: Optional[float],
) -> Dict[str, Any]:

    w = await get_wallet(user_id)

    unrealized = (
        _pnl(open_trade, price)
        if open_trade and price
        else 0.0
    )

    total = w["wins"] + w["losses"]

    closed = await db.trades.find(
        {
            "user_id": user_id,
            "status": "CLOSED",
        },
        {
            "pnl": 1,
            "closed_at": 1,
        },
    ).sort(
        "closed_at",
        1,
    ).to_list(1000)

    gross_win = sum(
        float(t.get("pnl") or 0.0)
        for t in closed
        if float(t.get("pnl") or 0.0) > 0
    )

    gross_loss = -sum(
        float(t.get("pnl") or 0.0)
        for t in closed
        if float(t.get("pnl") or 0.0) < 0
    )

    equity_run = float(w["starting_balance"])
    peak = equity_run
    max_dd = 0.0

    for t in closed:
        equity_run += float(t.get("pnl") or 0.0)

        peak = max(
            peak,
            equity_run,
        )

        if peak > 0:
            max_dd = max(
                max_dd,
                (peak - equity_run) / peak * 100,
            )

    return {
        **w,
        "id": w["user_id"],
        "unrealized_pnl": round(unrealized, 2),
        "equity": round(
            w["balance"] + unrealized,
            2,
        ),
        "win_rate": round(
            w["wins"] / total * 100,
            1,
        ) if total else 0.0,
        "profit_factor": round(
            gross_win / gross_loss,
            2,
        ) if gross_loss else round(gross_win, 2),
        "max_drawdown_pct": round(
            max_dd,
            2,
        ),
        "return_pct": round(
            (
                w["balance"]
                + unrealized
                - w["starting_balance"]
            )
            / w["starting_balance"]
            * 100,
            2,
        ),
        "day_pnl": round(
            await _day_pnl(user_id),
            2,
        ),
        "open_position": bool(open_trade),
    }


# -------------------------------------------------------------------------
# trades
# -------------------------------------------------------------------------

def _pnl(
    trade: Optional[Dict[str, Any]],
    price: Optional[float],
) -> float:

    if not trade or not price:
        return 0.0

    sign = (
        1
        if trade["direction"] == "BUY"
        else -1
    )

    return (
        (price - trade["entry"])
        * sign
        * trade["qty"]
        + float(trade.get("partial_pnl") or 0.0)
    )


async def get_open_trade(
    user_id: str,
) -> Optional[Dict[str, Any]]:

    doc = await db.trades.find_one(
        {
            "user_id": user_id,
            "status": "OPEN",
        }
    )

    return _clean(doc) if doc else None


async def trade_history(
    user_id: str,
    limit: int = 60,
) -> List[Dict[str, Any]]:

    docs = (
        await db.trades.find(
            {
                "user_id": user_id,
                "status": "CLOSED",
            }
        )
        .sort("closed_at", -1)
        .to_list(limit)
    )

    return [
        _clean(d)
        for d in docs
    ]


def _decorate_open(
    trade: Dict[str, Any],
    price: Optional[float],
) -> Dict[str, Any]:

    out = dict(trade)

    if price:
        pnl = _pnl(
            trade,
            price,
        )

        out["current_price"] = price

        out["unrealized_pnl"] = round(
            pnl,
            2,
        )

        out["unrealized_pnl_pct"] = (
            round(
                pnl / trade["risk_amount"] * 100,
                2,
            )
            if trade["risk_amount"]
            else 0.0
        )

        out["r_multiple"] = (
            round(
                (
                    (price - trade["entry"])
                    * (
                        1
                        if trade["direction"] == "BUY"
                        else -1
                    )
                    / trade["r_distance"]
                ),
                2,
            )
            if trade.get("r_distance")
            else 0.0
        )

        span = abs(
            trade["tp"] - trade["entry"]
        ) or 1

        prog = (
            (price - trade["entry"])
            * (
                1
                if trade["direction"] == "BUY"
                else -1
            )
            / span
        )

        out["tp_progress_pct"] = round(
            max(
                0.0,
                min(
                    100.0,
                    prog * 100,
                ),
            ),
            1,
        )

    opened = _aware(
        trade.get("opened_at")
    )

    timeout = _aware(
        trade.get("timeout_at")
    )

    now = _now()

    out["age_seconds"] = (
        int(
            (now - opened).total_seconds()
        )
        if opened
        else 0
    )

    out["seconds_to_timeout"] = (
        max(
            0,
            int(
                (timeout - now).total_seconds()
            ),
        )
        if timeout
        else 0
    )

    return out


# -------------------------------------------------------------------------
# open trade
# -------------------------------------------------------------------------

async def open_trade(
    user_id: str,
    signal: Dict[str, Any],
    price: float,
    cfg: Dict[str, Any],
) -> Optional[Dict[str, Any]]:

    wallet = await get_wallet(user_id)

    sl = signal.get("sl")
    tp = signal.get("tp")

    if sl is None or tp is None:
        return None

    sl_dist = abs(
        price - sl
    )

    if sl_dist <= 0:
        return None

    risk_pct = (
        float(cfg["risk_per_trade_pct"])
        / 100
    )

    risk_amount = (
        wallet["balance"]
        * risk_pct
    )

    qty = (
        risk_amount
        / sl_dist
    )

    notional = qty * price

    cap = (
        wallet["balance"]
        * float(cfg["max_leverage"])
    )

    capped = False

    if notional > cap:
        qty = cap / price
        notional = cap
        risk_amount = qty * sl_dist
        capped = True

    direction = signal["direction"]

    aligned = [
        c
        for c in signal.get(
            "confirmations",
            [],
        )
        if c["direction"]
        == (
            "BULLISH"
            if direction == "BUY"
            else "BEARISH"
        )
    ]

    entry_reasons = [
        signal.get(
            "summary",
            "",
        ),
        (
            f"Confluence score "
            f"{signal['confidence']:.1f}% "
            f"(bull {signal.get('bull_score', 0)} "
            f"vs bear {signal.get('bear_score', 0)}) "
            f"on the {signal['timeframe']} timeframe, "
            f"above the "
            f"{float(cfg['confidence_threshold']):.0f}% "
            "auto-trade threshold."
        ),
    ]

    entry_reasons += [
        f"{c['name']}: {c['detail']}"
        for c in aligned
    ]

    sess = market_sessions.snapshot()

    risk_reasons = list(
        signal.get(
            "level_reasons",
            [],
        )
    )

    risk_reasons += [
        (
            f"Position sized to risk "
            f"{float(cfg['risk_per_trade_pct']):.2f}% "
            f"of your "
            f"${wallet['balance']:,.2f} "
            f"paper balance "
            f"(${risk_amount:,.2f}) "
            f"over a {sl_dist:.2f} stop distance "
            f"→ {qty:.4f} oz "
            f"(${notional:,.2f} notional)."
        ),
        (
            f"Planned reward:risk is "
            f"{signal['rr']:.2f}, so one winner covers "
            f"{signal['rr']:.2f} losers of the same size."
        ),
        (
            f"Taken during "
            f"{', '.join(sess['active']) or 'no major session'} "
            f"({sess['liquidity']} liquidity)."
        ),
        (
            f"Scalp plan: break even at "
            f"+{float(cfg['breakeven_at_r']):.2f}R, "
            f"bank "
            f"{float(cfg['partial_tp_fraction']) * 100:.0f}% "
            f"at +{float(cfg['partial_tp_at_r']):.2f}R, "
            f"trail "
            f"{float(cfg['trail_atr_mult']):.2f}x ATR "
            f"from +{float(cfg['trail_start_r']):.2f}R, "
            f"and cut the trade at "
            f"{int(cfg['max_hold_minutes'])} minutes."
        ),
    ]

    if capped:
        risk_reasons.append(
            f"Size capped at "
            f"{float(cfg['max_leverage']):.0f}x "
            "notional leverage."
        )

    hold_seconds = strategy.timeout_seconds(
        signal["timeframe"],
        float(
            cfg["max_hold_minutes"]
        ),
    )

    now = _now()

    trade = {
        "id": str(uuid.uuid4()),
        "user_id": user_id,
        "symbol": (
            market.feed_status.get("symbol")
            or "BTCUSDT"
        ),
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
        "atr": round(
            signal.get("atr") or 0.0,
            4,
        ),
        "session": (
            ", ".join(sess["active"])
            or "off-session"
        ),
        "liquidity": sess["liquidity"],
        "trailing_active": False,
        "breakeven_done": False,
        "partial_done": False,
        "partial_pnl": 0.0,
        "best_r": 0.0,
        "max_hold_minutes": int(
            cfg["max_hold_minutes"]
        ),
        "opened_at": now,
        "timeout_at": (
            now
            + timedelta(
                seconds=hold_seconds
            )
        ),
        "entry_reasons": entry_reasons,
        "risk_reasons": risk_reasons,
        "ai_explanation": None,
        "ai_status": "pending",
        "management_log": [
            (
                f"{now.strftime('%H:%M:%S')} UTC — "
                f"opened {direction} "
                f"{qty:.4f} oz at {price:.2f} "
                f"(SL {sl:.2f} / TP {tp:.2f}), "
                f"hard time cap "
                f"{int(cfg['max_hold_minutes'])} min. "
                "Exits are managed server-side even "
                "if the dashboard is closed."
            )
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

    await db.trades.insert_one(
        dict(trade)
    )

    logger.info(
        "trade opened for %s: %s %s @ %s",
        user_id,
        direction,
        trade["qty"],
        price,
    )

    asyncio.create_task(
        _narrate(
            trade,
            signal,
            aligned,
        )
    )

    return _clean(trade)


async def _narrate(
    trade: Dict[str, Any],
    signal: Dict[str, Any],
    aligned: List[Dict[str, Any]],
) -> None:

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
            {"id": trade["id"]},
            {
                "$set": {
                    "ai_explanation": text,
                    "ai_status": status,
                }
            },
        )

    except Exception as exc:
        logger.warning(
            "narration task failed: %s",
            exc,
        )

        await db.trades.update_one(
            {"id": trade["id"]},
            {
                "$set": {
                    "ai_status": "unavailable"
                }
            },
        )


# -------------------------------------------------------------------------
# close trade
# -------------------------------------------------------------------------

async def close_trade(
    trade: Dict[str, Any],
    price: float,
    reason: str,
    explanation: str,
) -> Dict[str, Any]:

    user_id = trade["user_id"]

    remaining = (
        (price - trade["entry"])
        * (
            1
            if trade["direction"] == "BUY"
            else -1
        )
        * trade["qty"]
    )

    total = (
        remaining
        + float(
            trade.get("partial_pnl")
            or 0.0
        )
    )

    opened = (
        _aware(trade.get("opened_at"))
        or _now()
    )

    duration = int(
        (_now() - opened).total_seconds()
    )

    r_mult = (
        total / trade["risk_amount"]
        if trade.get("risk_amount")
        else 0.0
    )

    wallet = await get_wallet(user_id)

    now = _now()

    update = {
        "status": "CLOSED",
        "exit_price": round(price, 2),
        "exit_reason": reason,
        "exit_explanation": explanation,
        "pnl": round(total, 2),
        "pnl_pct": round(
            total / wallet["balance"] * 100,
            3,
        ) if wallet["balance"] else 0.0,
        "r_multiple": round(
            r_mult,
            2,
        ),
        "closed_at": now,
        "duration_seconds": duration,
        "management_log": list(
            trade.get(
                "management_log",
                [],
            )
        ) + [
            (
                f"{now.strftime('%H:%M:%S')} UTC — "
                f"closed at {price:.2f} "
                f"({reason}), "
                f"total P&L ${total:,.2f}."
            )
        ],
    }

    await db.trades.update_one(
        {"id": trade["id"]},
        {"$set": update},
    )

    await db.wallets.update_one(
        {"user_id": user_id},
        {
            "$set": {
                "balance": round(
                    wallet["balance"]
                    + remaining,
                    2,
                )
            },
            "$inc": {
                "realized_pnl": round(
                    total,
                    2,
                ),
                "trades_count": 1,
                "wins": (
                    1
                    if total > 0
                    else 0
                ),
                "losses": (
                    0
                    if total > 0
                    else 1
                ),
            },
        },
    )

    logger.info(
        "trade closed for %s: %s pnl=%.2f",
        user_id,
        reason,
        total,
    )

    return {
        **trade,
        **update,
    }


# -------------------------------------------------------------------------
# open trade management
# -------------------------------------------------------------------------

async def manage_open_trade(
    trade: Dict[str, Any],
    price: float,
    signal: Optional[Dict[str, Any]],
    cfg: Dict[str, Any],
) -> None:

    long = trade["direction"] == "BUY"

    r = (
        trade.get("r_distance")
        or 1.0
    )

    favorable = (
        (price - trade["entry"])
        * (
            1
            if long
            else -1
        )
    )

    r_mult = favorable / r

    # --------------------------------------------------------------
    # stop loss
    # --------------------------------------------------------------

    if (
        long and price <= trade["sl"]
    ) or (
        not long and price >= trade["sl"]
    ):

        moved = (
            abs(
                trade["sl"]
                - trade["initial_sl"]
            )
            > 1e-9
        )

        at_be = (
            trade.get("breakeven_done")
            and not trade.get("trailing_active")
        )

        if not moved:
            reason = "STOP LOSS"

            expl = (
                f"Price traded through the protective "
                f"stop at {trade['sl']:.2f}. "
                "The setup was invalidated and the "
                "pre-defined risk was taken."
            )

        elif at_be:
            reason = "BREAK-EVEN STOP"

            expl = (
                f"The stop had already been moved "
                f"to break-even at {trade['sl']:.2f} "
                f"after +{float(cfg['breakeven_at_r']):.2f}R. "
                "Price returned, so the trade exited "
                "without taking the original loss."
            )

        else:
            reason = "TRAILING STOP"

            expl = (
                f"Price hit the trailing stop at "
                f"{trade['sl']:.2f}. "
                f"The stop had advanced from the original "
                f"{trade['initial_sl']:.2f}, protecting "
                "part of the favorable move."
            )

        await close_trade(
            trade,
            trade["sl"],
            reason,
            expl,
        )

        return

    # --------------------------------------------------------------
    # take profit
    # --------------------------------------------------------------

    if (
        long and price >= trade["tp"]
    ) or (
        not long and price <= trade["tp"]
    ):

        await close_trade(
            trade,
            trade["tp"],
            "TAKE PROFIT",
            (
                f"Target reached at "
                f"{trade['tp']:.2f}. "
                f"The planned reward:risk was "
                f"{trade['rr_planned']:.2f}."
            ),
        )

        return

    # --------------------------------------------------------------
    # time cap
    # --------------------------------------------------------------

    timeout_at = _aware(
        trade.get("timeout_at")
    )

    if timeout_at and _now() >= timeout_at:

        await close_trade(
            trade,
            price,
            "TIME CAP",
            (
                f"Hard scalper time cap reached. "
                f"The trade held for "
                f"{int(trade.get('max_hold_minutes') or 0)} "
                "minutes without reaching SL or TP."
            ),
        )

        return

    updates: Dict[str, Any] = {}
    log: List[str] = []

    # --------------------------------------------------------------
    # best R
    # --------------------------------------------------------------

    best_r = max(
        float(
            trade.get("best_r")
            or 0.0
        ),
        r_mult,
    )

    if best_r > float(
        trade.get("best_r")
        or 0.0
    ):
        updates["best_r"] = round(
            best_r,
            3,
        )

    # --------------------------------------------------------------
    # partial TP
    # --------------------------------------------------------------

    partial_at = float(
        cfg["partial_tp_at_r"]
    )

    fraction = float(
        cfg["partial_tp_fraction"]
    )

    if (
        not trade.get("partial_done")
        and fraction > 0
        and r_mult >= partial_at
    ):

        close_qty = (
            trade["qty"]
            * fraction
        )

        booked = (
            (price - trade["entry"])
            * (
                1
                if long
                else -1
            )
            * close_qty
        )

        wallet = await get_wallet(
            trade["user_id"]
        )

        updates["qty"] = round(
            trade["qty"]
            - close_qty,
            5,
        )

        updates["partial_done"] = True

        updates["partial_pnl"] = round(
            float(
                trade.get("partial_pnl")
                or 0.0
            )
            + booked,
            2,
        )

        await db.wallets.update_one(
            {"user_id": trade["user_id"]},
            {
                "$set": {
                    "balance": round(
                        wallet["balance"]
                        + booked,
                        2,
                    )
                },
                "$inc": {
                    "realized_pnl": round(
                        booked,
                        2,
                    )
                },
            },
        )

        log.append(
            (
                f"{_now().strftime('%H:%M:%S')} UTC — "
                f"hit +{partial_at:.2f}R, "
                f"banked {fraction * 100:.0f}% "
                f"of the position "
                f"({close_qty:.4f} oz) "
                f"at {price:.2f} "
                f"for ${booked:,.2f}; "
                "the rest runs."
            )
        )

        trade = {
            **trade,
            **updates,
        }

    # --------------------------------------------------------------
    # break even
    # --------------------------------------------------------------

    be_at = float(
        cfg["breakeven_at_r"]
    )

    if (
        not trade.get("breakeven_done")
        and r_mult >= be_at
    ):

        buffer_ = 0.05 * r

        be_sl = (
            trade["entry"]
            + buffer_
            if long
            else trade["entry"]
            - buffer_
        )

        if (
            long
            and be_sl > trade["sl"]
        ) or (
            not long
            and be_sl < trade["sl"]
        ):

            updates["sl"] = round(
                be_sl,
                2,
            )

            updates["breakeven_done"] = True

            log.append(
                (
                    f"{_now().strftime('%H:%M:%S')} UTC — "
                    f"reached +{be_at:.2f}R, "
                    f"stop moved to break-even "
                    f"{be_sl:.2f}."
                )
            )

            trade = {
                **trade,
                **updates,
            }

    # --------------------------------------------------------------
    # trailing stop
    # --------------------------------------------------------------

    if r_mult >= float(
        cfg["trail_start_r"]
    ):

        atr_val = (
            trade.get("atr")
            or r
        )

        mult = float(
            cfg["trail_atr_mult"]
        )

        candidate = (
            price - mult * atr_val
            if long
            else price + mult * atr_val
        )

        floor_ = (
            trade["entry"]
            + 0.3 * r
            if long
            else trade["entry"]
            - 0.3 * r
        )

        new_sl = (
            max(candidate, floor_)
            if long
            else min(candidate, floor_)
        )

        if (
            long
            and new_sl > trade["sl"] + 1e-9
        ) or (
            not long
            and new_sl < trade["sl"] - 1e-9
        ):

            updates["sl"] = round(
                new_sl,
                2,
            )

            updates["trailing_active"] = True

            log.append(
                (
                    f"{_now().strftime('%H:%M:%S')} UTC — "
                    f"{r_mult:.2f}R in profit, "
                    f"trailing stop advanced to "
                    f"{new_sl:.2f} "
                    f"({mult}x ATR behind price)."
                )
            )

    # --------------------------------------------------------------
    # momentum fade
    # --------------------------------------------------------------

    opened = (
        _aware(
            trade.get("opened_at")
        )
        or _now()
    )

    elapsed = (
        _now()
        - opened
    ).total_seconds()

    total_hold = strategy.timeout_seconds(
        trade["timeframe"],
        float(
            trade.get(
                "max_hold_minutes",
                15,
            )
        ),
    )

    if (
        signal
        and elapsed > total_hold * 0.35
        and favorable < 0
        and signal.get("direction")
        not in (
            trade["direction"],
            "WAIT",
        )
        and float(
            signal.get(
                "confidence",
                0,
            )
        ) >= 55
    ):

        await close_trade(
            trade,
            price,
            "MOMENTUM FADE",
            (
                f"The signal engine flipped to "
                f"{signal['direction']} at "
                f"{signal['confidence']:.1f}% confidence "
                f"while this {trade['direction']} trade "
                "was underwater."
            ),
        )

        return

    # --------------------------------------------------------------
    # persist management changes
    # --------------------------------------------------------------

    if updates:

        if log:
            updates["management_log"] = (
                list(
                    trade.get(
                        "management_log",
                        [],
                    )
                )
                + log
            )

        await db.trades.update_one(
            {"id": trade["id"]},
            {"$set": updates},
        )


# -------------------------------------------------------------------------
# circuit breakers
# -------------------------------------------------------------------------

async def guards(
    user_id: str,
    cfg: Dict[str, Any],
    present: Optional[bool] = None,
) -> Dict[str, Any]:

    wallet = await get_wallet(
        user_id
    )

    now = _now()

    checks: List[Dict[str, Any]] = []

    # --------------------------------------------------------------
    # auto trade
    # --------------------------------------------------------------

    enabled = bool(
        cfg["auto_trade_enabled"]
    )

    checks.append(
        {
            "name": "Auto-trading enabled",
            "passed": enabled,
            "detail": (
                "engine armed"
                if enabled
                else "kill switch is OFF"
            ),
        }
    )

    # --------------------------------------------------------------
    # presence
    # --------------------------------------------------------------

    if present is None:
        present = await is_present(
            user_id
        )

    checks.append(
        {
            "name": "Dashboard open (new entries)",
            "passed": bool(present),
            "detail": (
                "dashboard is open, so new entries are allowed"
                if present
                else (
                    "dashboard is closed — existing trades "
                    "are still managed, but no new trade starts"
                )
            ),
        }
    )

    # --------------------------------------------------------------
    # session
    # --------------------------------------------------------------

    sess = market_sessions.snapshot()

    session_ok = (
        not bool(
            cfg.get(
                "session_filter_enabled",
                True,
            )
        )
        or bool(
            sess["tradeable"]
        )
    )

    checks.append(
        {
            "name": "Session liquidity",
            "passed": session_ok,
            "detail": (
                f"{sess['liquidity']} liquidity "
                f"at {sess['utc_time']} UTC"
                + (
                    f" — {', '.join(sess['active'])} open"
                    if sess["active"]
                    else " — no major session open"
                )
                + (
                    ""
                    if bool(
                        cfg.get(
                            "session_filter_enabled",
                            True,
                        )
                    )
                    else " (filter off)"
                )
            ),
        }
    )

    # --------------------------------------------------------------
    # daily loss
    # --------------------------------------------------------------

    day_pnl = await _day_pnl(
        user_id
    )

    limit = (
        -wallet["starting_balance"]
        * float(
            cfg["daily_loss_limit_pct"]
        )
        / 100
    )

    checks.append(
        {
            "name": (
                f"Daily loss under "
                f"{float(cfg['daily_loss_limit_pct']):.2f}%"
            ),
            "passed": day_pnl > limit,
            "detail": (
                f"today's realized P&L "
                f"${day_pnl:,.2f} "
                f"vs limit ${limit:,.2f}"
            ),
        }
    )

    # --------------------------------------------------------------
    # hourly trade limit
    # --------------------------------------------------------------

    hour_ago = (
        now
        - timedelta(hours=1)
    )

    recent = await db.trades.count_documents(
        {
            "user_id": user_id,
            "opened_at": {
                "$gte": hour_ago
            },
        }
    )

    max_per_hour = int(
        cfg["max_trades_per_hour"]
    )

    checks.append(
        {
            "name": (
                f"Under {max_per_hour} trades/hour"
            ),
            "passed": recent < max_per_hour,
            "detail": (
                f"{recent} trade(s) opened "
                "in the last 60 minutes"
            ),
        }
    )

    # --------------------------------------------------------------
    # loss streak
    # --------------------------------------------------------------

    streak_needed = int(
        cfg["consecutive_loss_pause"]
    )

    pause_min = int(
        cfg["pause_minutes_after_losses"]
    )

    last = (
        await db.trades.find(
            {
                "user_id": user_id,
                "status": "CLOSED",
            }
        )
        .sort(
            "closed_at",
            -1,
        )
        .to_list(
            streak_needed
        )
    )

    streak = 0

    for d in last:
        if float(
            d.get("pnl") or 0.0
        ) <= 0:
            streak += 1
        else:
            break

    paused = False

    detail = (
        f"current losing streak "
        f"{streak}/{streak_needed}"
    )

    if streak >= streak_needed and last:

        last_close = _aware(
            last[0].get(
                "closed_at"
            )
        )

        if (
            last_close
            and now
            < last_close
            + timedelta(
                minutes=pause_min
            )
        ):

            paused = True

            mins = int(
                (
                    last_close
                    + timedelta(
                        minutes=pause_min
                    )
                    - now
                ).total_seconds()
                // 60
            ) + 1

            detail = (
                f"{streak} losses in a row — "
                f"cooling off for another ~{mins} min"
            )

    checks.append(
        {
            "name": (
                f"No {streak_needed}-loss cool-off"
            ),
            "passed": not paused,
            "detail": detail,
        }
    )

    # --------------------------------------------------------------
    # cooldown
    # --------------------------------------------------------------

    cooldown = int(
        cfg["cooldown_seconds"]
    )

    last_closed = (
        await db.trades.find(
            {
                "user_id": user_id,
                "status": "CLOSED",
            }
        )
        .sort(
            "closed_at",
            -1,
        )
        .to_list(1)
    )

    cd_ok = True

    cd_detail = (
        f"cooldown {cooldown}s after each close"
    )

    if last_closed:

        lc = _aware(
            last_closed[0].get(
                "closed_at"
            )
        )

        if (
            lc
            and (
                now - lc
            ).total_seconds()
            < cooldown
        ):

            cd_ok = False

            cd_detail = (
    f"{int(cooldown - (now - lc).total_seconds())}s "
    f"left of the {cooldown}s cooldown"
)

    checks.append(
        {
            "name": "Cooldown elapsed",
            "passed": cd_ok,
            "detail": cd_detail,
        }
    )

    blocked = [
        c
        for c in checks
        if not c["passed"]
    ]

    return {
        "checks": checks,
        "blocked": bool(blocked),
        "block_reason": (
            blocked[0]["name"]
            if blocked
            else ""
        ),
        "day_pnl": round(
            day_pnl,
            2,
        ),
        "trades_last_hour": recent,
        "loss_streak": streak,
        "present": bool(present),
    }


# -------------------------------------------------------------------------
# stale entry
# -------------------------------------------------------------------------

def stale_entry(
    signal: Dict[str, Any],
    price: float,
    cfg: Dict[str, Any],
) -> Optional[str]:

    ref = signal.get(
        "last_closed"
    )

    tp = signal.get(
        "tp"
    )

    if (
        ref is None
        or tp is None
        or tp == ref
    ):
        return None

    progress = (
        (price - ref)
        / (tp - ref)
        * 100
    )

    limit = float(
        cfg["stale_entry_max_pct"]
    )

    if progress > limit:
        return (
            f"price already travelled "
            f"{progress:.0f}% of the way "
            f"from {ref:.2f} to target {tp:.2f} "
            f"(limit {limit:.0f}%)"
        )

    return None


# -------------------------------------------------------------------------
# shared market evaluation
# -------------------------------------------------------------------------

async def evaluate(
    timeframe: str,
    cfg: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:

    cfg = (
        cfg
        or await settings_mod.get_defaults()
    )

    needed = dict.fromkeys(
        [timeframe]
        + strategy.MTF_MAP.get(
            timeframe,
            [],
        )
    )

    candles_by_tf: Dict[
        str,
        List[Dict[str, float]],
    ] = {}

    for tf in needed:
        candles_by_tf[tf] = (
            await market.get_klines(
                tf,
                300,
            )
        )

    price = (
        await market.get_price()
        or (
            candles_by_tf[timeframe][-1]["close"]
            if candles_by_tf.get(timeframe)
            else 0.0
        )
    )

    signal = strategy.analyze(
        timeframe,
        candles_by_tf,
        price,
        cfg,
    )

    signal["generated_at"] = (
        _now().isoformat()
    )

    _signals[timeframe] = signal
    _last_eval[timeframe] = time.time()

    return signal


async def get_signal(
    timeframe: str,
    max_age: float = 10.0,
) -> Dict[str, Any]:

    cached = _signals.get(
        timeframe
    )

    if (
        cached
        and (
            time.time()
            - _last_eval.get(
                timeframe,
                0,
            )
        )
        < max_age
    ):
        return cached

    return await evaluate(
        timeframe
    )


# -------------------------------------------------------------------------
# cycle
# -------------------------------------------------------------------------

async def cycle() -> None:

    async with _lock:

        # ==============================================================
        # 1. Load default/shared settings.
        #
        # These are ONLY used for shared market-analysis generation.
        # They are NOT used as a user's trading settings.
        # ==============================================================

        default_cfg = (
            await settings_mod.get_defaults(
                refresh=True
            )
        )

        # ==============================================================
        # 2. Generate market signals once per timeframe.
        # ==============================================================

        for tf in market.INTERVALS:

            try:
                await evaluate(
                    tf,
                    default_cfg,
                )

            except Exception as exc:
                logger.warning(
                    "evaluate %s failed: %s",
                    tf,
                    exc,
                )

        # ==============================================================
        # 3. Find users with dashboard presence.
        # ==============================================================

        active_users = (
            await active_user_ids()
        )

        # ==============================================================
        # 4. Manage ALL existing paper trades.
        #
        # IMPORTANT:
        # Every trade loads its owner's settings.
        # ==============================================================

        open_docs = (
            await db.trades.find(
                {"status": "OPEN"}
            ).to_list(500)
        )

        managed: set[str] = set()

        price = await market.get_price()

        if price:

            for doc in open_docs:

                trade = _clean(doc)

                user_id = str(
                    trade["user_id"]
                )

                managed.add(
                    user_id
                )

                try:

                    user_cfg = (
                        await settings_mod.get_settings(
                            user_id,
                            refresh=True,
                        )
                    )

                    trade_signal = _signals.get(
                        trade.get(
                            "timeframe"
                        )
                    )

                    await manage_open_trade(
                        trade,
                        price,
                        trade_signal,
                        user_cfg,
                    )

                except Exception as exc:
                    logger.warning(
                        "manage trade %s failed: %s",
                        trade.get("id"),
                        exc,
                    )

        # ==============================================================
        # 5. MT5 execution.
        #
        # mt5_execution.py should load each account owner's settings.
        # default_cfg is only shared fallback/market context.
        # ==============================================================

        primary_tf = str(
            default_cfg[
                "primary_timeframe"
            ]
        )

        primary_signal = _signals.get(
            primary_tf
        )

        try:

            await mt5_execution.process_cycle(
                primary_signal,
                default_cfg,
                active_users,
            )

        except Exception as exc:
            logger.warning(
                "MT5 execution cycle failed: %s",
                exc,
            )

        # ==============================================================
        # 6. Paper entries.
        #
        # Each user gets:
        #   - own settings
        #   - own timeframe
        #   - own strategy calculation
        #   - own guards
        #   - own risk
        # ==============================================================

        for user_id in active_users:

            if user_id in managed:
                continue

            try:

                # ------------------------------------------------------
                # Load PERSONAL settings
                # ------------------------------------------------------

                user_cfg = (
                    await settings_mod.get_settings(
                        user_id,
                        refresh=True,
                    )
                )

                primary_tf = str(
                    user_cfg[
                        "primary_timeframe"
                    ]
                )

                # ------------------------------------------------------
                # Load candles for this user's timeframe.
                # ------------------------------------------------------

                needed = dict.fromkeys(
                    [primary_tf]
                    + strategy.MTF_MAP.get(
                        primary_tf,
                        [],
                    )
                )

                candles_by_tf: Dict[
                    str,
                    List[Dict[str, float]],
                ] = {}

                for tf in needed:
                    candles_by_tf[tf] = (
                        await market.get_klines(
                            tf,
                            300,
                        )
                    )

                user_price = (
                    await market.get_price()
                )

                if not user_price:

                    user_price = (
                        candles_by_tf[
                            primary_tf
                        ][-1]["close"]
                        if candles_by_tf.get(
                            primary_tf
                        )
                        else 0.0
                    )

                if not user_price:

                    _block_reason[user_id] = (
                        "market price unavailable"
                    )

                    continue

                # ------------------------------------------------------
                # CRITICAL:
                # Analyze using THIS USER'S configuration.
                # ------------------------------------------------------

                user_signal = (
                    strategy.analyze(
                        primary_tf,
                        candles_by_tf,
                        user_price,
                        user_cfg,
                    )
                )

                user_signal[
                    "generated_at"
                ] = _now().isoformat()

                direction = str(
                    user_signal.get(
                        "direction"
                    )
                    or "WAIT"
                )

                confidence = float(
                    user_signal.get(
                        "confidence"
                    )
                    or 0.0
                )

                # ------------------------------------------------------
                # User-specific entry gates.
                #
                # strategy.analyze() already receives user_cfg,
                # so confidence / ADX / RR / ATR filters can be
                # different for every user.
                # ------------------------------------------------------

                threshold = float(
                    user_cfg.get(
                        "confidence_threshold",
                        80.0,
                    )
                )

                if (
                    direction
                    not in (
                        "BUY",
                        "SELL",
                    )
                    or confidence < threshold
                    or not user_signal.get(
                        "tradeable"
                    )
                ):

                    _block_reason[user_id] = (
                        f"{direction} confidence "
                        f"{confidence:.1f}% — waiting for "
                        f"{threshold:.1f}%"
                    )

                    continue

                # ------------------------------------------------------
                # User-specific guards.
                # ------------------------------------------------------

                g = await guards(
                    user_id,
                    user_cfg,
                    present=True,
                )

                if g["blocked"]:

                    _block_reason[user_id] = (
                        g["block_reason"]
                    )

                    continue

                # ------------------------------------------------------
                # User-specific stale entry.
                # ------------------------------------------------------

                stale = stale_entry(
                    user_signal,
                    user_price,
                    user_cfg,
                )

                if stale:

                    _block_reason[user_id] = (
                        f"stale entry: {stale}"
                    )

                    continue

                # ------------------------------------------------------
                # Open personal trade.
                # ------------------------------------------------------

                _block_reason[user_id] = ""

                trade = await open_trade(
                    user_id,
                    user_signal,
                    user_price,
                    user_cfg,
                )

                if trade:

                    await db.signals.insert_one(
                        {
                            "id": str(
                                uuid.uuid4()
                            ),
                            "user_id": user_id,
                            "timeframe": user_signal[
                                "timeframe"
                            ],
                            "direction": user_signal[
                                "direction"
                            ],
                            "confidence": user_signal[
                                "confidence"
                            ],
                            "price": user_price,
                            "trade_id": trade[
                                "id"
                            ],
                            "created_at": _now(),
                        }
                    )

            except Exception as exc:

                logger.warning(
                    "user %s cycle failed: %s",
                    user_id,
                    exc,
                )


# -------------------------------------------------------------------------
# engine loop
# -------------------------------------------------------------------------

async def _loop() -> None:

    await asyncio.sleep(2)

    _stats[
        "started_at"
    ] = _now().isoformat()

    while True:

        try:

            await cycle()

            _stats[
                "cycles"
            ] = int(
                _stats["cycles"]
            ) + 1

            _stats[
                "last_cycle_at"
            ] = _now().isoformat()

        except asyncio.CancelledError:
            raise

        except Exception as exc:

            _stats[
                "last_error"
            ] = str(exc)

            logger.warning(
                "engine cycle error: %s",
                exc,
            )

        await asyncio.sleep(
            LOOP_SECONDS
        )


async def _watch() -> None:

    while True:

        await asyncio.sleep(
            WATCHDOG_SECONDS
        )

        global _task

        if (
            _task is None
            or _task.done()
        ):

            _stats[
                "restarts"
            ] = int(
                _stats["restarts"]
            ) + 1

            logger.warning(
                "engine loop was down — "
                "restarting (restart #%s)",
                _stats["restarts"],
            )

            _task = asyncio.create_task(
                _loop()
            )


def start() -> None:

    global _task, _watchdog

    if (
        _task is None
        or _task.done()
    ):
        _task = asyncio.create_task(
            _loop()
        )

    if (
        _watchdog is None
        or _watchdog.done()
    ):
        _watchdog = asyncio.create_task(
            _watch()
        )


async def stop() -> None:

    global _task, _watchdog

    for task in (
        _watchdog,
        _task,
    ):

        if task and not task.done():

            task.cancel()

            try:
                await task

            except (
                asyncio.CancelledError,
                Exception,
            ):
                pass

    _task = None
    _watchdog = None


# -------------------------------------------------------------------------
# health
# -------------------------------------------------------------------------

def health() -> Dict[str, Any]:

    return {
        **_stats,
        "running": bool(
            _task
            and not _task.done()
        ),
        "watchdog_running": bool(
            _watchdog
            and not _watchdog.done()
        ),
        "loop_seconds": LOOP_SECONDS,
        "presence_window_seconds": PRESENCE_WINDOW,
        "server_time": _now().isoformat(),
    }


# -------------------------------------------------------------------------
# user config
# -------------------------------------------------------------------------

async def config(
    user_id: str,
) -> Dict[str, Any]:

    cfg = await settings_mod.get_settings(
        user_id,
        refresh=True,
    )

    return {
        **cfg,
        "starting_balance": STARTING_BALANCE,
        "timeframes": market.INTERVALS,
        "loop_seconds": LOOP_SECONDS,
        "presence_window_seconds": PRESENCE_WINDOW,
        "disclaimer": (
            "The built-in account is educational paper trading. "
            "Real MT5 orders are placed only when a user separately "
            "connects an MT5 account and enables MT5 auto-trading; "
            "no signal is a guarantee."
        ),
    }


# -------------------------------------------------------------------------
# dashboard
# -------------------------------------------------------------------------

async def dashboard(
    user_id: str,
    timeframe: str,
) -> Dict[str, Any]:

    await touch_presence(
        user_id
    )

    cfg = await settings_mod.get_settings(
        user_id,
        refresh=True,
    )

    signal = await get_signal(
        timeframe
    )

    price = await market.get_price()

    open_t = await get_open_trade(
        user_id
    )

    g = await guards(
        user_id,
        cfg,
        present=True,
    )

    return {
        "feed": dict(
            market.feed_status
        ),

        "ticker": {
            "symbol": (
                market.feed_status.get(
                    "symbol"
                )
                or "BTCUSDT"
            ),
            "price": price,
            **(
                await market.get_stats_24h()
            ),
        },

        "signal": signal,

        "wallet": await wallet_view(
            user_id,
            open_t,
            price,
        ),

        "open_trade": (
            _decorate_open(
                open_t,
                price,
            )
            if open_t
            else None
        ),

        "history": await trade_history(
            user_id,
            40,
        ),

        "config": await config(
            user_id
        ),

        "guards": {
            **g,
            "last_block_reason": (
                _block_reason.get(
                    user_id,
                    "",
                )
            ),
        },

        "sessions": (
            market_sessions.snapshot()
        ),

        "engine": health(),

        "server_time": (
            _now().isoformat()
        ),
    }