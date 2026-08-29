"""MT5 command queue and strategy-to-bridge execution coordinator.

New entries require recent browser presence. Existing positions are managed by the
EA even when the browser closes; the backend also queues hard-time and momentum
exits as a redundant control plane.

Each MT5 account uses the trading settings belonging to its owner.

SL/TP for ENTRY commands are sent as DISTANCES:
    sl_dist = distance from live execution price to stop
    tp_dist = distance from live execution price to target

The MT5 EA is responsible for converting these distances into absolute
broker prices using the live ASK/BID price at execution time.
"""
from __future__ import annotations

import math
import uuid
from datetime import timedelta
from typing import Any, Dict, Iterable, Optional

from pymongo import ReturnDocument
from pymongo.errors import DuplicateKeyError

from lib import auth, settings as settings_mod
from lib.db import db

BRIDGE_STALE_SECONDS = 45
ENTRY_TTL_SECONDS = 30


def connected(account: Dict[str, Any]) -> bool:
    seen = auth.aware(account.get("last_heartbeat_at"))
    return bool(
        seen
        and (auth.now() - seen).total_seconds() <= BRIDGE_STALE_SECONDS
    )


def BTC_symbol(symbol: str) -> bool:
    value = symbol.upper().replace("/", "").strip()

    if value in ("BTCUSD", "GOLD"):
        return True

    for root in ("BTCUSD", "GOLD"):
        if value.startswith(root):
            suffix = value[len(root):]
            return (
                0 < len(suffix) <= 7
                and suffix[0] in "._-"
                and suffix[1:].isalnum()
            )

    return False


def lot_valid(account: Dict[str, Any]) -> tuple[bool, str]:
    lot = float(account.get("lot_size") or 0)
    vmin = float(account.get("volume_min") or 0)
    vmax = float(account.get("volume_max") or 0)
    step = float(account.get("volume_step") or 0)

    if not vmin or not vmax or not step:
        return False, "waiting for broker lot limits"

    if lot < vmin or lot > vmax:
        return (
            False,
            f"lot {lot:g} is outside broker range {vmin:g}–{vmax:g}",
        )

    steps = (lot - vmin) / step

    if not math.isclose(steps, round(steps), abs_tol=1e-7):
        return (
            False,
            f"lot {lot:g} does not match broker step {step:g}",
        )

    return True, "lot accepted by broker limits"


async def queue_command(
    account: Dict[str, Any],
    action: str,
    idempotency_key: str,
    payload: Dict[str, Any],
) -> Optional[Dict[str, Any]]:
    expires_at = (
        auth.now() + timedelta(seconds=ENTRY_TTL_SECONDS)
        if action == "ENTRY"
        else None
    )

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

        "sl_dist": float(payload.get("sl_dist") or 0.0),
        "tp_dist": float(payload.get("tp_dist") or 0.0),

        "reason": str(payload.get("reason") or ""),
        "payload": payload,
        "attempts": 0,
        "created_at": auth.now(),
        "expires_at": expires_at,
        "expires_epoch": int(expires_at.timestamp()) if expires_at else 0,
        "execution_result": "",
        "broker_retcode": None,
        "completed_at": None,
    }

    try:
        await db.mt5_commands.insert_one(doc)
        return doc

    except DuplicateKeyError:
        existing = await db.mt5_commands.find_one(
            {"idempotency_key": idempotency_key}
        )

        if (
            existing
            and action == "ENTRY"
            and existing.get("status") in ("cancelled", "expired")
        ):
            refreshed = await db.mt5_commands.find_one_and_update(
                {
                    "id": existing["id"],
                    "status": {"$in": ["cancelled", "expired"]},
                },
                {
                    "$set": {
                        **{
                            k: v
                            for k, v in doc.items()
                            if k not in ("id", "idempotency_key")
                        },
                        "status": "pending",
                        "broker_message": "",
                        "completed_at": None,
                        "rearmed_at": auth.now(),
                    }
                },
                return_document=ReturnDocument.AFTER,
            )

            return refreshed or existing

        return existing


async def _queue_entry(
    account: Dict[str, Any],
    signal: Dict[str, Any],
    cfg: Dict[str, Any],
) -> Optional[Dict[str, Any]]:
    key = (
        f"{account['id']}:ENTRY:{signal.get('timeframe')}:"
        f"{signal.get('direction')}:{signal.get('last_closed')}"
    )

    return await queue_command(
        account,
        "ENTRY",
        key,
        {
            "direction": signal["direction"],
            "lots": float(account["lot_size"]),

            "sl_dist": float(signal["sl_dist"]),
            "tp_dist": float(signal["tp_dist"]),

            "entry_reference": float(signal["price"]),
            "atr": float(signal.get("atr") or 0.0),
            "confidence": float(signal["confidence"]),
            "timeframe": signal["timeframe"],

            "max_hold_seconds": int(
                float(cfg["max_hold_minutes"]) * 60
            ),

            "breakeven_at_r": float(
                cfg["breakeven_at_r"]
            ),

            "partial_tp_at_r": float(
                cfg["partial_tp_at_r"]
            ),

            "partial_tp_fraction": float(
                cfg["partial_tp_fraction"]
            ),

            "trail_start_r": float(
                cfg["trail_start_r"]
            ),

            "trail_distance": (
                float(cfg["trail_atr_mult"])
                * float(signal.get("atr") or 0.0)
            ),

            "reason": (
                f"MT5 confidence trigger: {signal['direction']} at "
                f"{float(signal['confidence']):.1f}% "
                f"(threshold "
                f"{float(cfg['confidence_threshold']):.1f}%)"
            ),
        },
    )


async def _queue_close(
    account: Dict[str, Any],
    position: Dict[str, Any],
    reason: str,
) -> None:
    key = (
        f"{account['id']}:CLOSE:"
        f"{position['ticket']}:{reason}"
    )

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


async def _entry_status(
    account: Dict[str, Any],
    state: str,
    reason: str,
) -> None:
    if (
        account.get("entry_state") == state
        and account.get("entry_reason") == reason
    ):
        return

    await db.mt5_accounts.update_one(
        {"id": account["id"]},
        {
            "$set": {
                "entry_state": state,
                "entry_reason": reason,
                "entry_status_at": auth.now(),
            }
        },
    )


async def process_cycle(
    signal: Optional[Dict[str, Any]],
    cfg: Optional[Dict[str, Any]],
    _active_user_ids: Iterable[str],
) -> None:
    """Queue MT5 commands using each account owner's personal settings."""

    accounts = await db.mt5_accounts.find(
        {"revoked": {"$ne": True}}
    ).to_list(500)

    for account in accounts:

        # ---------------------------------------------------------------
        # IMPORTANT:
        # Load settings belonging to this MT5 account owner.
        # ---------------------------------------------------------------
        user_id = str(account["user_id"])

        try:
            user_cfg = await settings_mod.get_settings(
                user_id,
                refresh=True,
            )
        except Exception:
            # Keep cycle alive if one user's settings cannot be loaded.
            # Fall back to the supplied config only for this account.
            user_cfg = cfg or await settings_mod.get_defaults(
                refresh=True
            )

        # ---------------------------------------------------------------
        # Existing MT5 position management uses owner's settings.
        # ---------------------------------------------------------------
        position = await db.mt5_positions.find_one(
            {
                "account_id": account["id"],
                "status": "OPEN",
            }
        )

        if position:
            await _entry_status(
                account,
                "in_position",
                f"Managing MT5 ticket {position['ticket']}",
            )

            opened = auth.aware(position.get("opened_at"))

            elapsed = (
                (auth.now() - opened).total_seconds()
                if opened
                else 0
            )

            max_hold = int(
                float(
                    user_cfg.get(
                        "max_hold_minutes",
                        15,
                    )
                )
                * 60
            )

            if max_hold and elapsed >= max_hold:
                await _queue_close(
                    account,
                    position,
                    "TIME CAP",
                )

            elif (
                signal
                and elapsed >= max_hold * 0.35
                and float(position.get("profit") or 0.0) < 0
                and signal.get("direction")
                not in (
                    position.get("direction"),
                    "WAIT",
                )
                and float(
                    signal.get("confidence") or 0.0
                ) >= 55
            ):
                await _queue_close(
                    account,
                    position,
                    "MOMENTUM FADE",
                )

            continue

        # ---------------------------------------------------------------
        # Owner-specific entry threshold.
        # ---------------------------------------------------------------
        threshold = float(
            user_cfg.get(
                "confidence_threshold",
                80.0,
            )
        )

        confidence = float(
            (signal or {}).get("confidence") or 0.0
        )

        direction = str(
            (signal or {}).get("direction") or "WAIT"
        )

        if (
            not signal
            or direction not in ("BUY", "SELL")
            or confidence < threshold
            or signal.get("sl_dist") is None
            or signal.get("tp_dist") is None
        ):
            await _entry_status(
                account,
                "waiting",
                (
                    f"{direction} confidence "
                    f"{confidence:.1f}% — waiting for "
                    f"{threshold:.1f}%"
                ),
            )
            continue

        sl_dist = float(
            signal.get("sl_dist") or 0.0
        )

        tp_dist = float(
            signal.get("tp_dist") or 0.0
        )

        if sl_dist <= 0 or tp_dist <= 0:
            await _entry_status(
                account,
                "blocked",
                "Invalid SL/TP distances",
            )
            continue

        # ---------------------------------------------------------------
        # MT5 account-level kill switch.
        # ---------------------------------------------------------------
        if not account.get("auto_trade_enabled"):
            await _entry_status(
                account,
                "blocked",
                "MT5 auto-trading is switched off",
            )
            continue

        if not connected(account):
            await _entry_status(
                account,
                "blocked",
                "MT5 heartbeat is offline or stale",
            )
            continue

        if (
            not account.get("trade_allowed")
            or not account.get("algo_trading")
        ):
            await _entry_status(
                account,
                "blocked",
                "Trading or Algo Trading is disabled in MT5",
            )
            continue

        # ---------------------------------------------------------------
        # IMPORTANT:
        # This is now the USER'S kill switch, not a global setting.
        # ---------------------------------------------------------------
        if not bool(
            user_cfg.get(
                "auto_trade_enabled",
                True,
            )
        ):
            await _entry_status(
                account,
                "blocked",
                "Your auto-trading setting is switched off",
            )
            continue

        if not BTC_symbol(
            str(
                account.get(
                    "resolved_symbol"
                ) or ""
            )
        ):
            await _entry_status(
                account,
                "blocked",
                (
                    "The broker gold symbol is not an "
                    "approved BTCUSD/GOLD alias"
                ),
            )
            continue

        valid_lot, lot_reason = lot_valid(
            account
        )

        if not valid_lot:
            await _entry_status(
                account,
                "blocked",
                lot_reason,
            )
            continue

        if float(
            account.get("free_margin") or 0.0
        ) <= 0:
            await _entry_status(
                account,
                "blocked",
                "No free margin is available in the MT5 account",
            )
            continue

        user = await db.users.find_one(
            {"id": account["user_id"]}
        )

        if (
            not auth.is_subscribed(user)
            or not auth.is_mt5_live_entitled(user)
        ):
            await db.mt5_accounts.update_one(
                {"id": account["id"]},
                {
                    "$set": {
                        "auto_trade_enabled": False,
                        "last_error": (
                            "normal or MT5 subscription inactive"
                        ),
                    }
                },
            )

            await _entry_status(
                account,
                "blocked",
                (
                    "Both the normal and MT5 Auto-Trading "
                    "subscriptions must be active"
                ),
            )
            continue

        pending = await db.mt5_commands.count_documents(
            {
                "account_id": account["id"],
                "action": "ENTRY",
                "status": {
                    "$in": [
                        "pending",
                        "dispatched",
                        "accepted",
                    ]
                },
            }
        )

        if pending:
            await _entry_status(
                account,
                "queued",
                (
                    "An MT5 entry command is awaiting "
                    "broker confirmation"
                ),
            )
            continue

        # ---------------------------------------------------------------
        # Queue ENTRY using this user's settings.
        # ---------------------------------------------------------------
        await _queue_entry(
            account,
            signal,
            user_cfg,
        )

        await _entry_status(
            account,
            "queued",
            (
                f"{direction} {confidence:.1f}% reached the "
                f"{threshold:.1f}% threshold — sent to MT5"
            ),
        )