"""Private MT5 account configuration and token-authenticated EA bridge."""

from __future__ import annotations

import hashlib
import hmac
import json
import logging
import os
import re
import secrets
from datetime import datetime, timezone
from typing import Any, Dict, List

from fastapi import APIRouter, Depends, Header, HTTPException, Request
from fastapi.responses import FileResponse
from pydantic import ValidationError
from pymongo import ReturnDocument

from lib import auth, broker_market, metaapi, mt5_execution, survival
from lib.db import db
from models.mt5 import (
    AdminMt5Account,
    BridgeAck,
    BridgeHeartbeat,
    BridgeMarketData,
    BridgePollResponse,
    ManagedMt5ConnectRequest,
    Mt5Account,
    Mt5Command,
    Mt5ConnectRequest,
    Mt5ConnectResponse,
    Mt5Position,
    Mt5SettingsPatch,
    SurvivalSettingsPatch,
    SurvivalStatus,
)


router = APIRouter(tags=["mt5"])
logger = logging.getLogger(__name__)


def _hash_token(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def _clean(doc: Dict[str, Any]) -> Dict[str, Any]:
    return {k: v for k, v in doc.items() if k not in ("_id", "token_hash")}


async def _position(account_id: str) -> Dict[str, Any] | None:
    return await db.mt5_positions.find_one(
        {
            "account_id": account_id,
            "status": "OPEN",
        }
    )


async def _public(
    account: Dict[str, Any],
    user: Dict[str, Any] | None = None,
) -> Mt5Account:
    user = (
        user
        or await db.users.find_one({"id": account["user_id"]})
        or {}
    )

    pos = await _position(account["id"])
    connected = mt5_execution.connected(account)

    status = str(account.get("status") or "pending")

    if status == "connected" and not connected:
        status = "offline"

    data = _clean(account)

    data.update(
        {
            "user_email": str(user.get("email") or ""),
            "status": status,
            "connected": connected,
            "live_entitled": auth.is_mt5_provider_entitled(user, str(account.get("provider") or "ea")),
            "position": Mt5Position(**_clean(pos)) if pos else None,
        }
    )

    return Mt5Account(**data)


async def _bridge_account(
    authorization: str | None,
) -> Dict[str, Any]:
    if (
        not authorization
        or not authorization.startswith("Bearer ")
    ):
        raise HTTPException(
            status_code=401,
            detail="bridge token required",
        )

    token = authorization.removeprefix("Bearer ").strip()

    account = await db.mt5_accounts.find_one(
        {
            "token_hash": _hash_token(token),
            "revoked": {"$ne": True},
        }
    )
    if account and account.get("provider") == "metaapi":
        primary = str((await db.settings.find_one({"user_id": user["id"]}) or {}).get("primary_timeframe") or "5m")
        account = await metaapi.sync_account(account, primary)

    if not account:
        raise HTTPException(
            status_code=401,
            detail="bridge token is invalid or revoked",
        )

    return account


# ------------------- User Routes -------------------


@router.get(
    "/mt5/account",
    response_model=Mt5Account | None,
)
async def account_status(
    request: Request,
) -> Mt5Account | None:
    user = await auth.require_subscription(request)

    account = await db.mt5_accounts.find_one(
        {
            "user_id": user["id"],
            "revoked": {"$ne": True},
        }
    )

    return (
        await _public(account, user)
        if account
        else None
    )


@router.post(
    "/mt5/account",
    response_model=Mt5ConnectResponse,
)
async def connect_account(
    body: Mt5ConnectRequest,
    request: Request,
) -> Mt5ConnectResponse:
    user = await auth.require_subscription(request)

    if not auth.is_mt5_basic_entitled(user):
        raise HTTPException(
            status_code=402,
            detail="an active MT5 Basic subscription is required",
        )

    existing = await db.mt5_accounts.find_one(
        {
            "user_id": user["id"],
            "revoked": {"$ne": True},
        }
    )

    if existing and await _position(existing["id"]):
        raise HTTPException(
            status_code=409,
            detail="close the current MT5 position before reconnecting",
        )

    token = secrets.token_urlsafe(36)

    account_id = (
        existing["id"]
        if existing
        else secrets.token_hex(16)
    )

    doc = {
        "id": account_id,
        "user_id": user["id"],
        "provider": "ea",
        "mode": body.mode,
        "account_login": body.account_login.strip(),
        "broker_server": body.broker_server.strip(),
        "symbol": body.symbol,
        "lot_size": float(body.lot_size),
        "auto_trade_enabled": False,
        "status": "pending",
        "resolved_symbol": "",
        "token_hash": _hash_token(token),
        "token_hint": token[-6:],
        "revoked": False,
        "trade_allowed": False,
        "algo_trading": False,
        "balance": 0.0,
        "equity": 0.0,
        "margin": 0.0,
        "free_margin": 0.0,
        "margin_level": 0.0,
        "account_currency": "",
        "daily_profit": 0.0,
        "volume_min": 0.0,
        "volume_max": 0.0,
        "volume_step": 0.0,
        "ea_version": "",
        "last_poll_at": None,
        "last_heartbeat_at": None,
        "last_seen_at": None,
        "last_error": "waiting for the MT5 Expert Advisor",
        "entry_state": "waiting",
        "entry_reason": "Waiting for a validated MT5 heartbeat",
        "broker_data_ready": False,
        "broker_data_source": "public",
        "broker_tick_at": None,
        "broker_bid": 0.0,
        "broker_ask": 0.0,
        "broker_spread_points": 0.0,
        "created_at": (
            existing.get("created_at")
            if existing
            else auth.now()
        ),
        "updated_at": auth.now(),
    }

    await db.mt5_accounts.replace_one(
        {"user_id": user["id"]},
        doc,
        upsert=True,
    )

    bridge_url = "/api/mt5/bridge"

    return Mt5ConnectResponse(
        account=await _public(doc, user),
        bridge_token=token,
        bridge_url=bridge_url,
        setup_steps=[
            "Install the broker's MT5 terminal on a Windows VPS and sign in to this account.",
            "Download UniversalTerminalBridge.mq5, compile it in MetaEditor, and attach it to the broker's BTC/USD chart.",
            "Add this site's HTTPS origin to MT5 Tools → Options → Expert Advisors → Allow WebRequest.",
            "Paste the one-time bridge URL and token into the EA inputs, then enable Algo Trading.",
        ],
    )


@router.post("/mt5/managed/connect", response_model=Mt5Account, status_code=202)
async def connect_managed(body: ManagedMt5ConnectRequest, request: Request) -> Mt5Account:
    user = await auth.require_subscription(request)
    if not auth.is_mt5_managed_entitled(user):
        raise HTTPException(status_code=402, detail="an active MT5 Managed subscription is required")
    if not metaapi.configured():
        raise HTTPException(status_code=503, detail="MT5 Managed is not configured")
    if await _account(user["id"]):
        raise HTTPException(status_code=409, detail="disconnect the current MT5 account before connecting another")
    try:
        provisioned = await metaapi.provision(body)
    except metaapi.MetaApiError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    account_id = secrets.token_hex(16)
    now = auth.now()
    doc = {
        "id": account_id, "user_id": user["id"], "provider": "metaapi", "mode": body.mode,
        "account_login": "Managed account", "broker_server": "MetaApi cloud", "symbol": body.symbol,
        "status": "deploying", "resolved_symbol": "", "lot_size": body.lot_size,
        "auto_trade_enabled": False, "trade_allowed": False, "algo_trading": True,
        "balance": 0.0, "equity": 0.0, "margin": 0.0, "free_margin": 0.0,
        "margin_level": 0.0, "account_currency": "", "daily_profit": 0.0,
        "volume_min": 0.0, "volume_max": 0.0, "volume_step": 0.0,
        "metaapi_account_id": provisioned["account_id"], "metaapi_region": provisioned["region"],
        "metaapi_state": provisioned["state"], "metaapi_connection_status": "DISCONNECTED",
        "broker_data_ready": False, "broker_data_source": "syncing", "revoked": False,
        "entry_state": "waiting", "entry_reason": "MetaApi is deploying the managed terminal",
        "last_error": "", "created_at": now, "updated_at": now,
    }
    try:
        await db.mt5_accounts.replace_one({"user_id": user["id"]}, doc, upsert=True)
    except Exception:
        try:
            await metaapi.remove_account(provisioned["account_id"])
        except Exception:
            pass
        raise
    return await _public(doc, user)


@router.patch(
    "/mt5/account",
    response_model=Mt5Account,
)
async def update_account(
    body: Mt5SettingsPatch,
    request: Request,
) -> Mt5Account:
    user = await auth.require_subscription(request)

    account = await db.mt5_accounts.find_one(
        {
            "user_id": user["id"],
            "revoked": {"$ne": True},
        }
    )

    if not account:
        raise HTTPException(
            status_code=404,
            detail="connect an MT5 account first",
        )

    updates = body.model_dump(
        exclude_none=True
    )

    if "lot_size" in updates:
        trial = {
            **account,
            "lot_size": updates["lot_size"],
        }

        if account.get("volume_min"):
            valid, detail = mt5_execution.lot_valid(trial)

            if not valid:
                raise HTTPException(
                    status_code=422,
                    detail=detail,
                )

    if updates.get("auto_trade_enabled"):
        if not mt5_execution.connected(account):
            raise HTTPException(
                status_code=409,
                detail="MT5 bridge is offline",
            )

        if not auth.is_mt5_provider_entitled(user, str(account.get("provider") or "ea")):
            raise HTTPException(
                status_code=402,
                detail="the matching MT5 plan is required",
            )

        if (
            not account.get("trade_allowed")
            or not account.get("algo_trading")
        ):
            raise HTTPException(
                status_code=409,
                detail="enable trading and Algo Trading in MT5 first",
            )

        valid, detail = mt5_execution.lot_valid(
            {
                **account,
                **updates,
            }
        )

        if not valid:
            raise HTTPException(
                status_code=422,
                detail=detail,
            )

    if updates:
        updates["updated_at"] = auth.now()

        await db.mt5_accounts.update_one(
            {"id": account["id"]},
            {"$set": updates},
        )

    fresh = (
        await db.mt5_accounts.find_one(
            {"id": account["id"]}
        )
        or account
    )

    return await _public(
        fresh,
        user,
    )


@router.get("/mt5/survival", response_model=SurvivalStatus)
async def survival_status(request: Request) -> SurvivalStatus:
    user = await auth.require_subscription(request)
    account = await db.mt5_accounts.find_one({"user_id": user["id"], "revoked": {"$ne": True}})
    if not account:
        raise HTTPException(status_code=404, detail="connect an MT5 account first")
    session = await survival.get_session(account)
    return SurvivalStatus(**survival.public_status(session, account))


@router.patch("/mt5/survival", response_model=SurvivalStatus)
async def update_survival(body: SurvivalSettingsPatch, request: Request) -> SurvivalStatus:
    user = await auth.require_subscription(request)
    account = await db.mt5_accounts.find_one({"user_id": user["id"], "revoked": {"$ne": True}})
    if not account:
        raise HTTPException(status_code=404, detail="connect an MT5 account first")
    if not auth.is_mt5_provider_entitled(user, str(account.get("provider") or "ea")):
        raise HTTPException(status_code=402, detail="the matching MT5 plan is required")
    try:
        session = await survival.configure(account, body)
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    fresh_account = await db.mt5_accounts.find_one({"id": account["id"]}) or account
    return SurvivalStatus(**survival.public_status(session, fresh_account))


@router.delete("/mt5/account")
async def disconnect_account(
    request: Request,
) -> Dict[str, str]:
    user = await auth.require_subscription(request)

    account = await db.mt5_accounts.find_one(
        {
            "user_id": user["id"],
            "revoked": {"$ne": True},
        }
    )

    if not account:
        raise HTTPException(
            status_code=404,
            detail="MT5 account not found",
        )

    position = await _position(account["id"])

    if account.get("provider") == "metaapi" and account.get("metaapi_account_id"):
        try:
            await metaapi.remove_account(str(account["metaapi_account_id"]))
        except metaapi.MetaApiError as exc:
            raise HTTPException(status_code=502, detail=str(exc)) from exc

    await db.mt5_accounts.update_one(
        {"id": account["id"]},
        {
            "$set": {
                "revoked": True,
                "auto_trade_enabled": False,
                "status": "revoked",
                "updated_at": auth.now(),
            }
        },
    )

    await db.mt5_commands.update_many(
        {
            "account_id": account["id"],
            "status": {
                "$in": [
                    "pending",
                    "dispatched",
                    "accepted",
                ]
            },
        },
        {
            "$set": {
                "status": "cancelled",
                "completed_at": auth.now(),
                "broker_message": "account disconnected",
            }
        },
    )

    if position:
        await db.mt5_positions.update_one(
            {
                "account_id": account["id"],
                "ticket": position["ticket"],
            },
            {
                "$set": {
                    "detached": True,
                    "detached_at": auth.now(),
                    "detach_reason": "user immediately revoked the MT5 bridge",
                }
            },
        )

        return {
            "message": (
                "MT5 disconnected immediately. "
                "The app no longer monitors the open trade; "
                "broker SL/TP and the local EA continue managing it."
            )
        }

    return {
        "message": "MT5 account disconnected and bridge token revoked"
    }


@router.get(
    "/mt5/commands",
    response_model=List[Mt5Command],
)
async def command_history(
    request: Request,
) -> List[Mt5Command]:
    user = await auth.require_subscription(request)

    account = await db.mt5_accounts.find_one(
        {
            "user_id": user["id"],
            "revoked": {"$ne": True},
        }
    )

    if not account:
        return []

    docs = await db.mt5_commands.find(
        {"account_id": account["id"]}
    ).sort(
        "created_at",
        -1,
    ).to_list(100)

    return [
        Mt5Command(**_clean(doc))
        for doc in docs
    ]


# ------------------- Bridge Routes -------------------


@router.get("/mt5/bridge/ping")
@router.post("/mt5/bridge/ping")
async def bridge_ping():
    """EA WebRequest connectivity test endpoint"""
    return {
        "ok": True,
        "status": "healthy",
        "server_time": auth.now().isoformat(),
    }


@router.get("/download/bridge-ea")
async def download_bridge_ea():
    """Download UniversalTerminalBridge.mq5 file"""

    possible_paths = [
        "UniversalTerminalBridge.mq5",
        "UniversalTerminalBridge.mq5",
        "frontend/public/UniversalTerminalBridge.mq5",
        "frontend/public/UniversalTerminalBridge.mq5",
        "static/UniversalTerminalBridge.mq5",
        "../frontend/public/UniversalTerminalBridge.mq5",
    ]

    for path in possible_paths:
        if os.path.exists(path):
            return FileResponse(
                path=path,
                filename="UniversalTerminalBridge.mq5",
                media_type="application/octet-stream",
                headers={
                    "Content-Disposition": (
                        "attachment; "
                        "filename=UniversalTerminalBridge.mq5"
                    )
                },
            )

    raise HTTPException(
        status_code=404,
        detail="EA file not found. Please contact support.",
    )


@router.post(
    "/mt5/bridge/heartbeat",
    response_model=Mt5Account,
)
async def bridge_heartbeat(
    body: BridgeHeartbeat,
    authorization: str | None = Header(default=None),
) -> Mt5Account:
    account = await _bridge_account(
        authorization
    )

    expected_login = str(
        account["account_login"]
    )

    reported_login = (
        body.account_login.strip()
    )

    expected_server = str(
        account["broker_server"]
    )

    reported_server = (
        body.broker_server.strip()
    )

    if not hmac.compare_digest(
        expected_login,
        reported_login,
    ):
        detail = (
            f"EA login {reported_login} "
            f"does not match connected login "
            f"{expected_login}"
        )

        await db.mt5_accounts.update_one(
            {"id": account["id"]},
            {
                "$set": {
                    "status": "error",
                    "last_error": detail,
                    "last_poll_at": auth.now(),
                }
            },
        )

        raise HTTPException(
            status_code=403,
            detail=detail,
        )

    if not hmac.compare_digest(
        expected_server.lower(),
        reported_server.lower(),
    ):
        detail = (
            f"EA server '{reported_server}' "
            f"does not match connected server "
            f"'{expected_server}'"
        )

        await db.mt5_accounts.update_one(
            {"id": account["id"]},
            {
                "$set": {
                    "status": "error",
                    "last_error": detail,
                    "last_poll_at": auth.now(),
                }
            },
        )

        raise HTTPException(
            status_code=403,
            detail=detail,
        )

    if (
        account["mode"] == "demo"
    ) != body.is_demo:
        reported_mode = (
            "demo"
            if body.is_demo
            else "live"
        )

        detail = (
            f"EA reports {reported_mode} mode "
            f"but this connection is configured "
            f"as {account['mode']}"
        )

        await db.mt5_accounts.update_one(
            {"id": account["id"]},
            {
                "$set": {
                    "status": "error",
                    "last_error": detail,
                    "last_poll_at": auth.now(),
                }
            },
        )

        raise HTTPException(
            status_code=403,
            detail=detail,
        )

    # Broker symbol must match the instrument family
    # chosen at connect time.
    expected_family = (
        mt5_execution.symbol_family(
            account.get("symbol") or "BTCUSD"
        )
        or "BTC"
    )

    if (
        mt5_execution.symbol_family(
            body.resolved_symbol
        )
        != expected_family
    ):
        detail = (
            f"resolved symbol "
            f"'{body.resolved_symbol}' "
            f"does not match the selected "
            f"{expected_family} instrument"
        )

        await db.mt5_accounts.update_one(
            {"id": account["id"]},
            {
                "$set": {
                    "status": "error",
                    "last_error": detail,
                }
            },
        )

        raise HTTPException(
            status_code=422,
            detail=detail,
        )

    if len(body.positions) > 1:
        raise HTTPException(
            status_code=409,
            detail=(
                "only one bot-managed "
                "BTC/XAU position is allowed"
            ),
        )

    updates = {
        "status": "connected",
        "resolved_symbol": body.resolved_symbol.upper(),
        "balance": body.balance,
        "equity": body.equity,
        "margin": body.margin,
        "free_margin": body.free_margin,
        "margin_level": body.margin_level,
        "account_currency": body.account_currency.upper(),
        "daily_profit": body.daily_profit,
        "volume_min": body.volume_min,
        "volume_max": body.volume_max,
        "volume_step": body.volume_step,
        "trade_allowed": body.trade_allowed,
        "algo_trading": body.algo_trading,
        "terminal_build": body.terminal_build,
        "ea_version": body.ea_version,
        "last_poll_at": auth.now(),
        "last_heartbeat_at": auth.now(),
        "last_seen_at": auth.now(),
        "last_error": (
            ""
            if body.trade_allowed
            and body.algo_trading
            else "trading or Algo Trading is disabled in MT5"
        ),
        "updated_at": auth.now(),
    }

    await db.mt5_accounts.update_one(
        {"id": account["id"]},
        {"$set": updates},
    )

    # Sync positions
    previous_positions = await db.mt5_positions.find(
        {
            "account_id": account["id"],
            "status": "OPEN",
        }
    ).to_list(10)

    open_tickets: List[str] = []

    for pos in body.positions:
        if (
            mt5_execution.symbol_family(
                pos.symbol
            )
            != expected_family
        ):
            continue

        open_tickets.append(
            pos.ticket
        )

        await db.mt5_positions.update_one(
            {
                "account_id": account["id"],
                "ticket": pos.ticket,
            },
            {
                "$set": {
                    **pos.model_dump(),
                    "account_id": account["id"],
                    "user_id": account["user_id"],
                    "status": "OPEN",
                    "updated_at": auth.now(),
                },
                "$setOnInsert": {
                    "created_at": auth.now()
                },
            },
            upsert=True,
        )

        unresolved_entry = (
            await db.mt5_commands.find_one(
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
                    "direction": pos.direction,
                    "$or": [
                        {
                            "broker_ticket": pos.ticket
                        },
                        {
                            "broker_ticket": None
                        },
                        {
                            "broker_ticket": ""
                        },
                    ],
                },
                sort=[
                    ("created_at", -1)
                ],
            )
        )

        if unresolved_entry:
            await db.mt5_commands.update_one(
                {"id": unresolved_entry["id"]},
                {
                    "$set": {
                        "status": "confirmed",
                        "execution_result": "reconciled",
                        "broker_ticket": pos.ticket,
                        "completed_at": auth.now(),
                    }
                },
            )

    close_query: Dict[str, Any] = {
        "account_id": account["id"],
        "status": "OPEN",
    }

    if open_tickets:
        close_query["ticket"] = {
            "$nin": open_tickets
        }

    await db.mt5_positions.update_many(
        close_query,
        {
            "$set": {
                "status": "CLOSED",
                "closed_at": auth.now(),
                "updated_at": auth.now(),
            }
        },
    )

    for previous in previous_positions:
        if previous.get("ticket") in open_tickets:
            continue

        unresolved_close = (
            await db.mt5_commands.find_one(
                {
                    "account_id": account["id"],
                    "action": "CLOSE",
                    "status": {
                        "$in": [
                            "pending",
                            "dispatched",
                            "accepted",
                        ]
                    },
                    "payload.ticket": previous.get(
                        "ticket"
                    ),
                },
                sort=[
                    ("created_at", -1)
                ],
            )
        )

        if unresolved_close:
            await db.mt5_commands.update_one(
                {"id": unresolved_close["id"]},
                {
                    "$set": {
                        "status": "confirmed",
                        "execution_result": "reconciled",
                        "completed_at": auth.now(),
                    }
                },
            )

    fresh = (
        await db.mt5_accounts.find_one(
            {"id": account["id"]}
        )
        or {
            **account,
            **updates,
        }
    )

    return await _public(fresh)


@router.post("/mt5/bridge/market-data")
async def bridge_market_data(
    request: Request,
    authorization: str | None = Header(default=None),
) -> Dict[str, Any]:
    account = await _bridge_account(authorization)
    try:
        raw = await request.body()
        text = raw.decode("utf-8")
        try:
            body = json.loads(text)
        except json.JSONDecodeError:
            def legacy_datetime(match: re.Match[str]) -> str:
                value = datetime.strptime(match.group(2), "%Y.%m.%d %H:%M:%S").replace(tzinfo=timezone.utc)
                return f'{match.group(1)}:{int(value.timestamp())}'
            repaired = re.sub(
                r'("(?:tick_time|open_time)"):(\d{4}\.\d{2}\.\d{2} \d{2}:\d{2}:\d{2})',
                legacy_datetime,
                text,
            )
            body = json.loads(repaired)
        if not isinstance(body, dict):
            raise ValueError("market-data body must be an object")
        payload = BridgeMarketData.model_validate(body)
        return await broker_market.ingest(account, payload)
    except json.JSONDecodeError as exc:
        logger.warning("MT5 market-data JSON rejected at byte %s: %r", exc.pos, raw[max(0, exc.pos - 80):exc.pos + 80])
        raise HTTPException(status_code=400, detail="invalid broker market-data JSON") from exc
    except ValidationError as exc:
        logger.warning("MT5 market-data validation rejected: %s", exc.errors(include_input=False))
        raise HTTPException(status_code=400, detail="invalid broker market-data payload") from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post(
    "/mt5/bridge/poll",
    response_model=BridgePollResponse,
)
async def bridge_poll(
    authorization: str | None = Header(default=None),
) -> BridgePollResponse:
    account = await _bridge_account(
        authorization
    )

    await db.mt5_accounts.update_one(
        {"id": account["id"]},
        {
            "$set": {
                "last_poll_at": auth.now()
            }
        },
    )

    while True:
        command = await db.mt5_commands.find_one(
            {
                "account_id": account["id"],
                "status": {
                    "$in": [
                        "pending",
                        "dispatched",
                    ]
                },
            },
            sort=[
                ("created_at", 1)
            ],
        )

        if not command:
            return BridgePollResponse(
                command=None,
                server_time=auth.now(),
            )

        expires = auth.aware(
            command.get("expires_at")
        )

        user = (
            await db.users.find_one(
                {"id": account["user_id"]}
            )
            if command["action"] == "ENTRY"
            else None
        )

        expired = bool(
            expires and expires <= auth.now()
        )

        entry_blocked = (
            command["action"] == "ENTRY"
            and (
                expired
                or not account.get(
                    "auto_trade_enabled"
                )
                or not auth.is_subscribed(user)
                or not auth.is_mt5_live_entitled(user)
            )
        )

        # ----------------------------------------------------------
        # IMPORTANT:
        # Return the exact failed gate instead of the old combined
        # "entry blocked" message.
        #
        # Priority:
        # 1. Command expired
        # 2. Auto-trading disabled
        # 3. MT5 entitlement missing
        # 4. Normal subscription missing
        # ----------------------------------------------------------

        if entry_blocked:
            if expired:
                status = "expired"
                broker_message = (
                    "entry blocked: command expired"
                )

            elif not account.get(
                "auto_trade_enabled"
            ):
                status = "cancelled"
                broker_message = (
                    "entry blocked: auto-trading disabled"
                )

            elif not auth.is_mt5_live_entitled(user):
                status = "cancelled"
                broker_message = (
                    "entry blocked: entitlement missing"
                )

            elif not auth.is_subscribed(user):
                status = "cancelled"
                broker_message = (
                    "entry blocked: subscription missing"
                )

            else:
                # Defensive fallback. This should not normally
                # be reachable because entry_blocked is built from
                # the four checks above.
                status = "cancelled"
                broker_message = (
                    "entry blocked: unknown gate failure"
                )

            await db.mt5_commands.update_one(
                {"id": command["id"]},
                {
                    "$set": {
                        "status": status,
                        "completed_at": auth.now(),
                        "broker_message": broker_message,
                    }
                },
            )

            continue

        updated = (
            await db.mt5_commands.find_one_and_update(
                {
                    "id": command["id"],
                    "status": {
                        "$in": [
                            "pending",
                            "dispatched",
                        ]
                    },
                },
                {
                    "$set": {
                        "status": "dispatched",
                        "last_dispatched_at": auth.now(),
                    },
                    "$inc": {
                        "attempts": 1
                    },
                },
                return_document=ReturnDocument.AFTER,
            )
        )

        return BridgePollResponse(
            command=Mt5Command(
                **_clean(
                    updated or command
                )
            ),
            server_time=auth.now(),
        )


@router.post(
    "/mt5/bridge/ack",
    response_model=Mt5Command,
)
async def bridge_ack(
    body: BridgeAck,
    authorization: str | None = Header(default=None),
) -> Mt5Command:
    account = await _bridge_account(
        authorization
    )

    command = await db.mt5_commands.find_one(
        {
            "id": body.command_id,
            "account_id": account["id"],
        }
    )

    if not command:
        raise HTTPException(
            status_code=404,
            detail="command not found",
        )

    result = body.result

    if result is None:
        if body.success is None:
            raise HTTPException(
                status_code=422,
                detail="result or success is required",
            )

        result = (
            "executed"
            if body.success
            else "rejected"
        )

    status = (
        "confirmed"
        if result == "executed"
        else "accepted"
        if result == "accepted"
        else "rejected"
    )

    if command.get("status") in (
        "confirmed",
        "cancelled",
        "expired",
    ):
        return Mt5Command(
            **_clean(command)
        )

    updated = (
        await db.mt5_commands.find_one_and_update(
            {
                "id": command["id"],
                "status": {
                    "$in": [
                        "pending",
                        "dispatched",
                        "accepted",
                        "rejected",
                    ]
                },
            },
            {
                "$set": {
                    "status": status,
                    "execution_result": result,
                    "broker_ticket": body.broker_ticket,
                    "broker_deal": body.broker_deal,
                    "broker_retcode": body.broker_retcode,
                    "broker_message": body.broker_message[:500],
                    "filled_price": body.filled_price,
                    "filled_volume": body.filled_volume,
                    "completed_at": auth.now(),
                }
            },
            return_document=ReturnDocument.AFTER,
        )
    )

    return Mt5Command(
        **_clean(
            updated or command
        )
    )


# ------------------- Admin Routes -------------------


@router.get(
    "/admin/mt5/accounts",
    response_model=List[AdminMt5Account],
    dependencies=[Depends(auth.require_admin)],
)
async def admin_accounts() -> List[AdminMt5Account]:
    docs = await db.mt5_accounts.find(
        {
            "revoked": {
                "$ne": True
            }
        }
    ).sort(
        "created_at",
        -1,
    ).to_list(500)

    return [
        AdminMt5Account(
            **(
                await _public(doc)
            ).model_dump()
        )
        for doc in docs
    ]


@router.post(
    "/admin/mt5/accounts/{account_id}/disable",
    response_model=Mt5Account,
    dependencies=[Depends(auth.require_admin)],
)
async def admin_disable(
    account_id: str,
) -> Mt5Account:
    account = (
        await db.mt5_accounts.find_one_and_update(
            {"id": account_id},
            {
                "$set": {
                    "auto_trade_enabled": False,
                    "last_error": "disabled by admin",
                    "updated_at": auth.now(),
                }
            },
            return_document=ReturnDocument.AFTER,
        )
    )

    if not account:
        raise HTTPException(
            status_code=404,
            detail="MT5 account not found",
        )

    return await _public(account)