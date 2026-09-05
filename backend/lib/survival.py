"""Dual-model Survival Mode with deterministic MT5 risk shutdowns."""
from __future__ import annotations

import asyncio
import json
import os
import re
import uuid
from typing import Any, Dict, Optional

from emergentintegrations.llm.chat import LlmChat, StreamDone, TextDelta, UserMessage
from pymongo.errors import DuplicateKeyError

from lib import auth
from lib.db import db


GPT_MODEL = "gpt-5.4"
CLAUDE_MODEL = "claude-sonnet-4-6"


def _default(account: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "id": str(uuid.uuid4()),
        "account_id": account["id"],
        "user_id": account["user_id"],
        "enabled": False,
        "activation_requested": False,
        "status": "idle",
        "daily_profit_target_usd": 25.0,
        "daily_drawdown_limit_pct": 3.0,
        "max_drawdown_limit_pct": 10.0,
        "start_balance": float(account.get("balance") or 0.0),
        "start_equity": float(account.get("equity") or 0.0),
        "peak_equity": float(account.get("equity") or 0.0),
        "day_start_equity": float(account.get("equity") or 0.0),
        "broker_day": str(account.get("broker_day") or ""),
        "daily_profit_usd": 0.0,
        "daily_drawdown_pct": 0.0,
        "max_drawdown_pct": 0.0,
        "target_progress_pct": 0.0,
        "gpt": {},
        "claude": {},
        "consensus": "IDLE",
        "last_error": "",
        "created_at": auth.now(),
        "updated_at": auth.now(),
    }


async def get_session(account: Dict[str, Any]) -> Dict[str, Any]:
    return await db.mt5_survival.find_one({"account_id": account["id"]}) or _default(account)


def public_status(session: Dict[str, Any], account: Dict[str, Any]) -> Dict[str, Any]:
    broker_seen = auth.aware(account.get("broker_tick_at"))
    broker_ready = bool(
        account.get("broker_data_ready")
        and broker_seen
        and (auth.now() - broker_seen).total_seconds() <= 10
    )
    return {
        "enabled": bool(session.get("enabled")),
        "activation_requested": bool(session.get("activation_requested")),
        "status": str(session.get("status") or "idle"),
        "balance": float(account.get("balance") or 0.0),
        "equity": float(account.get("equity") or 0.0),
        "daily_profit_target_usd": float(session.get("daily_profit_target_usd") or 25.0),
        "daily_drawdown_limit_pct": float(session.get("daily_drawdown_limit_pct") or 3.0),
        "max_drawdown_limit_pct": float(session.get("max_drawdown_limit_pct") or 10.0),
        "daily_profit_usd": float(session.get("daily_profit_usd") or 0.0),
        "daily_drawdown_pct": float(session.get("daily_drawdown_pct") or 0.0),
        "max_drawdown_pct": float(session.get("max_drawdown_pct") or 0.0),
        "target_progress_pct": float(session.get("target_progress_pct") or 0.0),
        "broker_feed_ready": broker_ready,
        "broker_day": str(session.get("broker_day") or account.get("broker_day") or ""),
        "gpt": session.get("gpt") or {},
        "claude": session.get("claude") or {},
        "consensus": str(session.get("consensus") or "IDLE"),
        "last_error": str(session.get("last_error") or ""),
        "updated_at": session.get("updated_at"),
    }


async def configure(account: Dict[str, Any], body: Any) -> Dict[str, Any]:
    existing = await get_session(account)
    broker_seen = auth.aware(account.get("broker_tick_at"))
    broker_ready = bool(account.get("broker_data_ready") and broker_seen and (auth.now() - broker_seen).total_seconds() <= 10)
    now = auth.now()
    equity = float(account.get("equity") or 0.0)
    updates = {
        "enabled": bool(body.enabled and broker_ready),
        "activation_requested": bool(body.enabled and not broker_ready),
        "status": "active" if body.enabled and broker_ready else "waiting_broker" if body.enabled else "idle",
        "daily_profit_target_usd": float(body.daily_profit_target_usd),
        "daily_drawdown_limit_pct": float(body.daily_drawdown_limit_pct),
        "max_drawdown_limit_pct": float(body.max_drawdown_limit_pct),
        "updated_at": now,
        "last_error": "",
    }
    if body.enabled and not existing.get("enabled"):
        updates.update(
            {
                "start_balance": float(account.get("balance") or 0.0),
                "start_equity": equity,
                "peak_equity": equity,
                "day_start_equity": equity,
                "broker_day": str(account.get("broker_day") or ""),
                "daily_profit_usd": 0.0,
                "daily_drawdown_pct": 0.0,
                "max_drawdown_pct": 0.0,
                "target_progress_pct": 0.0,
                "consensus": "WAITING",
                "gpt": {},
                "claude": {},
                "started_at": now,
            }
        )
    session = await db.mt5_survival.find_one_and_update(
        {"account_id": account["id"]},
        {"$set": updates, "$setOnInsert": {"id": existing["id"], "account_id": account["id"], "user_id": account["user_id"], "created_at": now}},
        upsert=True,
        return_document=True,
    )
    await db.mt5_accounts.update_one(
        {"id": account["id"]},
        {"$set": {"auto_trade_enabled": bool(body.enabled and broker_ready)}},
    )
    return session or {**existing, **updates}


async def activate_pending(account: Dict[str, Any]) -> None:
    session = await db.mt5_survival.find_one({"account_id": account["id"], "activation_requested": True})
    if not session:
        return
    equity = float(account.get("equity") or 0.0)
    await db.mt5_survival.update_one(
        {"account_id": account["id"], "activation_requested": True},
        {"$set": {
            "enabled": True, "activation_requested": False, "status": "active",
            "start_balance": float(account.get("balance") or 0.0), "start_equity": equity,
            "peak_equity": equity, "day_start_equity": equity,
            "broker_day": str(account.get("broker_day") or ""), "daily_profit_usd": 0.0,
            "daily_drawdown_pct": 0.0, "max_drawdown_pct": 0.0,
            "target_progress_pct": 0.0, "consensus": "WAITING", "last_error": "",
            "started_at": auth.now(), "updated_at": auth.now(),
        }},
    )
    await db.mt5_accounts.update_one({"id": account["id"]}, {"$set": {"auto_trade_enabled": True}})


async def evaluate_limits(account: Dict[str, Any]) -> Dict[str, Any]:
    session = await get_session(account)
    if not session.get("enabled"):
        return {**session, "stop_reason": ""}

    equity = float(account.get("equity") or 0.0)
    broker_day = str(account.get("broker_day") or session.get("broker_day") or "")
    day_start = float(session.get("day_start_equity") or equity)
    if broker_day and broker_day != session.get("broker_day"):
        day_start = equity
    peak = max(float(session.get("peak_equity") or equity), equity)
    daily_profit = equity - day_start
    daily_dd = max(0.0, (day_start - equity) / day_start * 100) if day_start else 0.0
    max_dd = max(0.0, (peak - equity) / peak * 100) if peak else 0.0
    target = float(session.get("daily_profit_target_usd") or 25.0)
    updates: Dict[str, Any] = {
        "broker_day": broker_day,
        "day_start_equity": day_start,
        "peak_equity": peak,
        "daily_profit_usd": daily_profit,
        "daily_drawdown_pct": daily_dd,
        "max_drawdown_pct": max_dd,
        "target_progress_pct": min(100.0, max(0.0, daily_profit / target * 100)) if target else 0.0,
        "updated_at": auth.now(),
    }
    stop_reason = ""
    if daily_profit >= target:
        updates.update({"enabled": False, "status": "target_reached", "consensus": "HALTED"})
        stop_reason = "SURVIVAL TARGET REACHED"
    elif daily_dd >= float(session.get("daily_drawdown_limit_pct") or 3.0):
        updates.update({"enabled": False, "status": "daily_drawdown_halt", "consensus": "HALTED"})
        stop_reason = "SURVIVAL DAILY DRAWDOWN"
    elif max_dd >= float(session.get("max_drawdown_limit_pct") or 10.0):
        updates.update({"enabled": False, "status": "max_drawdown_halt", "consensus": "HALTED"})
        stop_reason = "SURVIVAL MAX DRAWDOWN"

    fresh = await db.mt5_survival.find_one_and_update(
        {"account_id": account["id"]}, {"$set": updates}, return_document=True
    )
    if stop_reason:
        await db.mt5_accounts.update_one(
            {"id": account["id"]},
            {"$set": {"auto_trade_enabled": False, "entry_state": "blocked", "entry_reason": stop_reason}},
        )
    return {**(fresh or session), "stop_reason": stop_reason}


def _parse_decision(text: str) -> Dict[str, Any]:
    match = re.search(r"\{.*\}", text, flags=re.DOTALL)
    if not match:
        raise ValueError("model returned no JSON object")
    data = json.loads(match.group(0))
    action = str(data.get("action") or "HOLD").upper()
    direction = str(data.get("direction") or "WAIT").upper()
    if action not in ("HOLD", "ENTRY", "CLOSE") or direction not in ("BUY", "SELL", "WAIT"):
        raise ValueError("model returned an unsupported decision")
    return {
        "action": action,
        "direction": direction,
        "confidence": max(0.0, min(100.0, float(data.get("confidence") or 0.0))),
        "reason": str(data.get("reason") or "")[:500],
        "status": "ok",
    }


async def _agent(provider: str, model: str, session_id: str, payload: Dict[str, Any]) -> Dict[str, Any]:
    key = os.environ.get("EMERGENT_LLM_KEY", "")
    if not key:
        return {"action": "HOLD", "direction": "WAIT", "confidence": 0.0, "reason": "LLM key unavailable", "status": "error"}
    system = (
        "You are one member of a two-model MT5 risk committee. Return exactly one JSON object with "
        "action HOLD, ENTRY, or CLOSE; direction BUY, SELL, or WAIT; confidence 0-100; and a short reason. "
        "Never invent prices. Never override risk limits. If evidence is uncertain, stale, or conflicting, HOLD."
    )
    chat = LlmChat(api_key=key, session_id=session_id, system_message=system).with_model(provider, model).with_params(max_tokens=300)

    async def collect() -> str:
        parts = []
        async for event in chat.stream_message(UserMessage(text=json.dumps(payload, separators=(",", ":"), default=str))):
            if isinstance(event, TextDelta):
                parts.append(event.content)
            elif isinstance(event, StreamDone):
                break
        return "".join(parts)

    try:
        return _parse_decision(await asyncio.wait_for(collect(), timeout=30))
    except Exception as exc:
        return {"action": "HOLD", "direction": "WAIT", "confidence": 0.0, "reason": f"{type(exc).__name__}: decision unavailable"[:500], "status": "error"}


async def consensus(account: Dict[str, Any], session: Dict[str, Any], signal: Dict[str, Any], position: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    candle = int(signal.get("last_closed") or 0)
    ticket = str((position or {}).get("ticket") or "flat")
    decision_key = f"{account['id']}:{candle}:{ticket}"
    existing = await db.mt5_survival_decisions.find_one({"decision_key": decision_key})
    if existing:
        return existing
    pending = {
        "id": str(uuid.uuid4()), "decision_key": decision_key, "account_id": account["id"],
        "user_id": account["user_id"], "status": "pending", "created_at": auth.now(),
    }
    try:
        await db.mt5_survival_decisions.insert_one(pending)
    except DuplicateKeyError:
        return await db.mt5_survival_decisions.find_one({"decision_key": decision_key}) or pending

    payload = {
        "mode": "manage_position" if position else "consider_entry",
        "symbol": signal.get("symbol"), "timeframe": signal.get("timeframe"),
        "market_direction": signal.get("direction"), "market_confidence": signal.get("confidence"),
        "price": signal.get("price"), "sl_distance": signal.get("sl_dist"), "tp_distance": signal.get("tp_dist"),
        "order_book": signal.get("order_book"),
        "position": None if not position else {k: position.get(k) for k in ("ticket", "direction", "entry_price", "current_price", "sl", "tp", "profit")},
        "risk": {
            "equity": account.get("equity"), "daily_profit_usd": session.get("daily_profit_usd"),
            "daily_drawdown_pct": session.get("daily_drawdown_pct"), "max_drawdown_pct": session.get("max_drawdown_pct"),
            "daily_target_usd": session.get("daily_profit_target_usd"),
        },
    }
    gpt, claude = await asyncio.gather(
        _agent("openai", GPT_MODEL, f"survival-gpt-{decision_key}", payload),
        _agent("anthropic", CLAUDE_MODEL, f"survival-claude-{decision_key}", payload),
    )
    gpt["model"] = GPT_MODEL
    claude["model"] = CLAUDE_MODEL
    agreed = gpt["action"] == claude["action"] and gpt["direction"] == claude["direction"]
    action = gpt["action"] if agreed else "HOLD"
    direction = gpt["direction"] if agreed else "WAIT"
    if not position and (action != "ENTRY" or direction != signal.get("direction")):
        action, direction = "HOLD", "WAIT"
    if position and action not in ("CLOSE", "HOLD"):
        action, direction = "HOLD", "WAIT"
    consensus_value = f"{action}:{direction}"
    updates = {
        "status": "complete", "gpt": gpt, "claude": claude, "agreed": agreed,
        "consensus": consensus_value, "completed_at": auth.now(),
    }
    await db.mt5_survival_decisions.update_one({"decision_key": decision_key}, {"$set": updates})
    await db.mt5_survival.update_one(
        {"account_id": account["id"]},
        {"$set": {"gpt": gpt, "claude": claude, "consensus": consensus_value, "last_decision_at": auth.now(), "last_error": "" if agreed else "Models did not agree", "updated_at": auth.now()}},
    )
    return {**pending, **updates}