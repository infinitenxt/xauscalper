"""MT5 command queue and strategy-to-bridge execution coordinator.

New entries require recent browser presence. Existing positions are managed by the
EA even when the browser closes; the backend also queues hard-time and momentum
exits as a redundant control plane.
"""
from __future__ import annotations

import math
import uuid
from datetime import timedelta
from typing import Any, Dict, Iterable, Optional

from pymongo.errors import DuplicateKeyError

from lib import auth, market_sessions
from lib.db import db

BRIDGE_STALE_SECONDS = 45
ENTRY_TTL_SECONDS = 30


def connected(account: Dict[str, Any]) -> bool:
    seen = auth.aware(account.get("last_seen_at"))
    return bool(seen and (auth.now() - seen).total_seconds() <= BRIDGE_STALE_SECONDS)


def xau_symbol(symbol: str) -> bool:
    value = symbol.upper().replace("/", "").strip()
    if value in ("XAUUSD", "GOLD"):
        return True
    for root in ("XAUUSD", "GOLD"):
        if value.startswith(root):
            suffix = value[len(root):]
            return 0 < len(suffix) <= 7 and suffix[0] in "._-" and suffix[1:].isalnum()
    return False


def lot_valid(account: Dict[str, Any]) -> tuple[bool, str]:
    lot = float(account.get("lot_size") or 0)
    vmin = float(account.get("volume_min") or 0)
    vmax = float(account.get("volume_max") or 0)
    step = float(account.get("volume_step") or 0)
    if not vmin or not vmax or not step:
        return False, "waiting for broker lot limits"
    if lot < vmin or lot > vmax:
        return False, f"lot {lot:g} is outside broker range {vmin:g}–{vmax:g}"
    steps = (lot - vmin) / step
    if not math.isclose(steps, round(steps), abs_tol=1e-7):
        return False, f"lot {lot:g} does not match broker step {step:g}"
    return True, "lot accepted by broker limits"


async def queue_command(
    account: Dict[str, Any], action: str, idempotency_key: str, payload: Dict[str, Any]
) -> Optional[Dict[str, Any]]:
    doc = {
        "id": str(uuid.uuid4()),
        "idempotency_key": idempotency_key,
        "account_id": account["id"],
        "user_id": account["user_id"],
        "action": action,
        "status": "pending",
        "symbol": account.get("resolved_symbol") or "",
        "direction": payload.get("direction", ""),
        "lots": float(payload.get("lots") or 0.0),
        "sl": float(payload.get("sl") or 0.0),
        "tp": float(payload.get("tp") or 0.0),
        "reason": str(payload.get("reason") or ""),
        "payload": payload,
        "attempts": 0,
        "created_at": auth.now(),
        "expires_at": auth.now() + timedelta(seconds=ENTRY_TTL_SECONDS) if action == "ENTRY" else None,
        "completed_at": None,
    }
    try:
        await db.mt5_commands.insert_one(doc)
        return doc
    except DuplicateKeyError:
        return await db.mt5_commands.find_one({"idempotency_key": idempotency_key})


async def _queue_entry(account: Dict[str, Any], signal: Dict[str, Any], cfg: Dict[str, Any]) -> None:
    key = (
        f"{account['id']}:ENTRY:{signal.get('timeframe')}:{signal.get('direction')}:"
        f"{signal.get('last_closed')}"
    )
    await queue_command(
        account,
        "ENTRY",
        key,
        {
            "direction": signal["direction"],
            "lots": float(account["lot_size"]),
            "sl": float(signal["sl"]),
            "tp": float(signal["tp"]),
            "entry_reference": float(signal["price"]),
            "atr": float(signal.get("atr") or 0.0),
            "confidence": float(signal["confidence"]),
            "timeframe": signal["timeframe"],
            "max_hold_seconds": int(float(cfg["max_hold_minutes"]) * 60),
            "breakeven_at_r": float(cfg["breakeven_at_r"]),
            "partial_tp_at_r": float(cfg["partial_tp_at_r"]),
            "partial_tp_fraction": float(cfg["partial_tp_fraction"]),
            "trail_start_r": float(cfg["trail_start_r"]),
            "trail_distance": float(cfg["trail_atr_mult"]) * float(signal.get("atr") or 0.0),
            "reason": signal.get("summary", "confirmed strategy entry"),
        },
    )


async def _queue_close(account: Dict[str, Any], position: Dict[str, Any], reason: str) -> None:
    key = f"{account['id']}:CLOSE:{position['ticket']}:{reason}"
    await queue_command(
        account,
        "CLOSE",
        key,
        {
            "ticket": position["ticket"],
            "direction": position.get("direction", ""),
            "lots": float(position.get("volume") or 0.0),
            "reason": reason,
        },
    )


async def process_cycle(
    signal: Optional[Dict[str, Any]], cfg: Dict[str, Any], active_user_ids: Iterable[str]
) -> None:
    """Queue remote management and entry commands without blocking paper trading."""
    active = set(active_user_ids)
    accounts = await db.mt5_accounts.find({"revoked": {"$ne": True}}).to_list(500)
    session = market_sessions.snapshot()

    for account in accounts:
        position = await db.mt5_positions.find_one({"account_id": account["id"], "status": "OPEN"})

        # Existing positions remain managed with no dashboard presence requirement.
        if position:
            opened = auth.aware(position.get("opened_at"))
            elapsed = (auth.now() - opened).total_seconds() if opened else 0
            max_hold = int(float(cfg.get("max_hold_minutes", 15)) * 60)
            if max_hold and elapsed >= max_hold:
                await _queue_close(account, position, "TIME CAP")
            elif (
                signal
                and elapsed >= max_hold * 0.35
                and float(position.get("profit") or 0.0) < 0
                and signal.get("direction") not in (position.get("direction"), "WAIT")
                and float(signal.get("confidence") or 0.0) >= 55
            ):
                await _queue_close(account, position, "MOMENTUM FADE")
            continue

        if not signal or not signal.get("tradeable") or account["user_id"] not in active:
            continue
        if not account.get("auto_trade_enabled") or not connected(account):
            continue
        if not account.get("trade_allowed") or not account.get("algo_trading"):
            continue
        if not bool(cfg.get("auto_trade_enabled", True)):
            continue
        if bool(cfg.get("session_filter_enabled", True)) and not session["tradeable"]:
            continue
        if not xau_symbol(str(account.get("resolved_symbol") or "")):
            continue
        valid_lot, _ = lot_valid(account)
        if not valid_lot or float(account.get("free_margin") or 0.0) <= 0:
            continue
        if account.get("mode") == "live":
            user = await db.users.find_one({"id": account["user_id"]})
            if not auth.is_mt5_live_entitled(user):
                await db.mt5_accounts.update_one(
                    {"id": account["id"]},
                    {"$set": {"auto_trade_enabled": False, "last_error": "live MT5 add-on expired"}},
                )
                continue
        daily_limit = -float(account.get("balance") or 0.0) * float(cfg.get("daily_loss_limit_pct", 3)) / 100
        if float(account.get("daily_profit") or 0.0) <= daily_limit:
            continue
        hour_ago = auth.now() - timedelta(hours=1)
        entries = await db.mt5_commands.count_documents(
            {"account_id": account["id"], "action": "ENTRY", "status": "confirmed", "completed_at": {"$gte": hour_ago}}
        )
        if entries >= int(cfg.get("max_trades_per_hour", 6)):
            continue
        pending = await db.mt5_commands.count_documents(
            {"account_id": account["id"], "action": "ENTRY", "status": {"$in": ["pending", "dispatched"]}}
        )
        if pending:
            continue
        await _queue_entry(account, signal, cfg)