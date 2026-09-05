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

from lib import auth, broker_market, metaapi, settings as settings_mod, survival
from lib.db import db
from lib import market  # ✅ For DEFAULT_SYMBOL
from lib import strategy  # per-account signal evaluation

BRIDGE_STALE_SECONDS = 45
ENTRY_TTL_SECONDS = 120


def connected(account: Dict[str, Any]) -> bool:
    seen = auth.aware(account.get("last_heartbeat_at"))
    return bool(
        seen
        and (auth.now() - seen).total_seconds() <= BRIDGE_STALE_SECONDS
    )


# ✅ Universal BTC symbol detection (with XAU support)
def BTC_symbol(symbol: str) -> bool:
    """Check if symbol is BTC-related or XAU-related (Universal)"""
    if not symbol:
        return False
    
    value = symbol.upper().replace("/", "").strip()
    
    # ✅ Universal patterns (BTC + XAU)
    patterns = [
        "BTCUSD", "BTCUSDT", "XBTUSD", 
        "BTCUSDP", "XBTUSDT", "BTC",
        "BITCOIN",
        "XAUUSD", "GOLD", "XAUUSDP",
        "XAUEUR", "XAU",
    ]
    
    # Exact match
    for pattern in patterns:
        if value == pattern:
            return True
    
    # Contains BTC and USD
    if "BTC" in value and ("USD" in value or "USDT" in value):
        if "GBTC" not in value and "EBTC" not in value:
            return True
    
    # Contains XAU and USD
    if "XAU" in value and "USD" in value:
        return True
    
    # Contains GOLD
    if "GOLD" in value:
        return True
    
    return False


def symbol_family(symbol: str) -> Optional[str]:
    """Return the instrument family for a raw symbol string: 'BTC', 'XAU' or None."""
    if not symbol:
        return None
    value = symbol.upper().replace("/", "").strip()
    if "XAU" in value or "GOLD" in value:
        return "XAU"
    if "BTC" in value or "XBT" in value or "BITCOIN" in value:
        return "BTC"
    return None


def app_symbol_for(account: Dict[str, Any]) -> str:
    """The canonical app symbol this MT5 account trades (BTCUSDT / XAUUSD)."""
    chosen = str(account.get("symbol") or "").upper()
    if chosen in ("BTCUSDT", "XAUUSD"):
        return chosen
    # Legacy accounts predate the per-connection choice — infer from resolved broker
    # symbol, defaulting to BTCUSDT.
    return "XAUUSD" if symbol_family(account.get("resolved_symbol") or "") == "XAU" else "BTCUSDT"


async def _signal_for(
    account: Dict[str, Any],
    timeframe: str,
    cfg: Dict[str, Any],
) -> Optional[Dict[str, Any]]:
    """Evaluate a fresh signal for an arbitrary app symbol + timeframe on demand.

    Mirrors engine.evaluate() but for the account's chosen instrument so an XAU/USD
    MT5 account trades XAU signals rather than the shared BTC feed.
    """
    try:
        app_symbol = app_symbol_for(account)
        broker = await broker_market.bundle(account, timeframe)
        if broker.get("ready"):
            signal = strategy.analyze(
                symbol=app_symbol,
                timeframe=timeframe,
                candles_by_tf=broker["candles_by_tf"],
                price=float(broker["price"]),
                cfg={**cfg, "order_book": await market.get_order_book(app_symbol)},
            )
            signal["data_source"] = "broker"
            signal["broker_symbol"] = broker.get("broker_symbol") or ""
            return signal

        needed = dict.fromkeys([timeframe] + strategy.MTF_MAP.get(timeframe, []))
        candles_by_tf: Dict[str, Any] = {}
        for tf in needed:
            candles_by_tf[tf] = await market.get_klines(app_symbol, tf, 300)

        primary = candles_by_tf.get(timeframe) or []
        price = await market.get_price(app_symbol) or (
            primary[-1]["close"] if primary else 0.0
        )
        signal = strategy.analyze(
            symbol=app_symbol,
            timeframe=timeframe,
            candles_by_tf=candles_by_tf,
            price=price,
            cfg={**cfg, "order_book": await market.get_order_book(app_symbol)},
        )
        signal["data_source"] = "public"
        signal["broker_data_status"] = "stale" if broker.get("fresh") is False else "syncing"
        return signal
    except Exception:
        return None


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

    result: Optional[Dict[str, Any]] = None
    try:
        await db.mt5_commands.insert_one(doc)
        result = doc

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

            result = refreshed or existing
        else:
            result = existing

    if result and account.get("provider") == "metaapi" and result.get("status") == "pending":
        return await metaapi.execute_command(account, result)
    return result


async def _queue_entry(
    account: Dict[str, Any],
    signal: Dict[str, Any],
    cfg: Dict[str, Any],
) -> Optional[Dict[str, Any]]:
    sl_dist = float(signal["sl_dist"])
    rr = float(signal.get("rr") or 0.0)
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

            "sl_dist": sl_dist,
            "tp_dist": sl_dist * rr,

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

            "trailing_enabled": 1.0 if bool(cfg.get("trailing_enabled", True)) else 0.0,

            "profit_lock_r": float(cfg.get("profit_lock_r", 0.10)),

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

    shared_signal = signal  # BTC feed signal computed once by the engine cycle

    for account in accounts:

        user_id = str(account["user_id"])

        try:
            user_cfg = await settings_mod.get_settings(
                user_id,
                refresh=True,
            )
        except Exception:
            user_cfg = cfg or await settings_mod.get_defaults(
                refresh=True
            )

        # Per-account instrument signal (BTCUSDT feed for BTC accounts, XAU feed
        # for XAU accounts). Falls back to the shared signal only if evaluation
        # fails for a BTC account.
        account_symbol = app_symbol_for(account)
        primary_tf = str(user_cfg.get("primary_timeframe", "5m"))
        if account.get("provider") == "metaapi":
            account = await metaapi.sync_account(account, primary_tf)
        account_signal = await _signal_for(account, primary_tf, user_cfg)
        if account_signal is None and account_symbol == "BTCUSDT":
            account_signal = shared_signal
        signal = account_signal

        position = await db.mt5_positions.find_one(
            {
                "account_id": account["id"],
                "status": "OPEN",
            }
        )

        survival_session = await survival.evaluate_limits(account)
        survival_active = bool(survival_session.get("enabled"))
        survival_stop = str(survival_session.get("stop_reason") or "")
        if survival_stop:
            if position:
                await _queue_close(account, position, survival_stop)
            continue

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

            if survival_active and signal and signal.get("data_source") == "broker":
                ai_decision = await survival.consensus(account, survival_session, signal, position)
                if str(ai_decision.get("consensus") or "").startswith("CLOSE:"):
                    await _queue_close(account, position, "AI CONSENSUS CLOSE")
                    continue

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
                bool(user_cfg.get("reverse_exit_enabled", True))
                and
                signal
                and signal.get("data_source") == "broker"
                and elapsed >= max(0.0, float(user_cfg.get("reverse_exit_min_hold_minutes", 1.0)) * 60)
                and signal.get("direction")
                not in (
                    position.get("direction"),
                    "WAIT",
                )
                and float(
                    signal.get("confidence") or 0.0
                ) >= float(user_cfg.get("reverse_exit_confidence", 60.0))
            ):
                await _queue_close(
                    account,
                    position,
                    "MARKET REVERSE",
                )

            continue

        if not signal or signal.get("data_source") != "broker":
            await _entry_status(
                account,
                "blocked",
                "Broker data is syncing or stale; public signals remain view-only",
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

        # ✅ Universal symbol check (BTC + XAU)
        resolved_symbol = str(account.get("resolved_symbol") or "")
        if not BTC_symbol(resolved_symbol):
            await _entry_status(
                account,
                "blocked",
                f"The broker symbol '{resolved_symbol}' is not supported",
            )
            continue

        valid_lot, lot_reason = lot_valid(account)
        if not valid_lot:
            await _entry_status(
                account,
                "blocked",
                lot_reason,
            )
            continue

        if float(account.get("free_margin") or 0.0) <= 0:
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
            or not auth.is_mt5_provider_entitled(user, str(account.get("provider") or "ea"))
        ):
            await db.mt5_accounts.update_one(
                {"id": account["id"]},
                {
                    "$set": {
                        "auto_trade_enabled": False,
                        "last_error": "normal or MT5 subscription inactive",
                    }
                },
            )

            await _entry_status(
                account,
                "blocked",
                "Both the normal and MT5 Auto-Trading subscriptions must be active",
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
                "An MT5 entry command is awaiting broker confirmation",
            )
            continue

        if survival_active:
            ai_decision = await survival.consensus(account, survival_session, signal, None)
            if str(ai_decision.get("consensus") or "") != f"ENTRY:{direction}":
                await _entry_status(
                    account,
                    "waiting",
                    "Survival agents did not reach unanimous entry consensus",
                )
                continue

        # ✅ Queue ENTRY using this user's settings.
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