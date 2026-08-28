"""Private MT5 account configuration and token-authenticated EA bridge."""
from __future__ import annotations

import hashlib
import hmac
import secrets
from typing import Any, Dict, List

from fastapi import APIRouter, Depends, Header, HTTPException, Request
from pymongo import ReturnDocument

from lib import auth, mt5_execution
from lib.db import db
from models.mt5 import (
    AdminMt5Account,
    BridgeAck,
    BridgeHeartbeat,
    BridgePollResponse,
    Mt5Account,
    Mt5Command,
    Mt5ConnectRequest,
    Mt5ConnectResponse,
    Mt5Position,
    Mt5SettingsPatch,
)

router = APIRouter(tags=["mt5"])


def _hash_token(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def _clean(doc: Dict[str, Any]) -> Dict[str, Any]:
    return {k: v for k, v in doc.items() if k not in ("_id", "token_hash")}


async def _position(account_id: str) -> Dict[str, Any] | None:
    return await db.mt5_positions.find_one({"account_id": account_id, "status": "OPEN"})


async def _public(account: Dict[str, Any], user: Dict[str, Any] | None = None) -> Mt5Account:
    user = user or await db.users.find_one({"id": account["user_id"]}) or {}
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
            "live_entitled": auth.is_mt5_live_entitled(user),
            "position": Mt5Position(**_clean(pos)) if pos else None,
        }
    )
    return Mt5Account(**data)


async def _bridge_account(authorization: str | None) -> Dict[str, Any]:
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="bridge token required")
    token = authorization.removeprefix("Bearer ").strip()
    account = await db.mt5_accounts.find_one({"token_hash": _hash_token(token), "revoked": {"$ne": True}})
    if not account:
        raise HTTPException(status_code=401, detail="bridge token is invalid or revoked")
    return account


@router.get("/mt5/account", response_model=Mt5Account | None)
async def account_status(request: Request) -> Mt5Account | None:
    user = await auth.require_subscription(request)
    account = await db.mt5_accounts.find_one({"user_id": user["id"], "revoked": {"$ne": True}})
    return await _public(account, user) if account else None


@router.post("/mt5/account", response_model=Mt5ConnectResponse)
async def connect_account(body: Mt5ConnectRequest, request: Request) -> Mt5ConnectResponse:
    user = await auth.require_subscription(request)
    if not auth.is_mt5_live_entitled(user):
        raise HTTPException(status_code=402, detail="an active MT5 Auto-Trading subscription is required")
    existing = await db.mt5_accounts.find_one({"user_id": user["id"], "revoked": {"$ne": True}})
    if existing and await _position(existing["id"]):
        raise HTTPException(status_code=409, detail="close the current MT5 position before reconnecting")
    token = secrets.token_urlsafe(36)
    account_id = existing["id"] if existing else secrets.token_hex(16)
    doc = {
        "id": account_id,
        "user_id": user["id"],
        "provider": "ea",
        "mode": body.mode,
        "account_login": body.account_login.strip(),
        "broker_server": body.broker_server.strip(),
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
        "created_at": existing.get("created_at") if existing else auth.now(),
        "updated_at": auth.now(),
    }
    await db.mt5_accounts.replace_one({"user_id": user["id"]}, doc, upsert=True)
    # Keep this host-neutral. The browser expands it against its own trusted origin,
    # avoiding forwarded-host/header injection in the credential users paste into MT5.
    bridge_url = "/api/mt5/bridge"
    return Mt5ConnectResponse(
        account=await _public(doc, user),
        bridge_token=token,
        bridge_url=bridge_url,
        setup_steps=[
            "Install the broker's MT5 terminal on a Windows VPS and sign in to this account.",
            "Download GoldTerminalBridge.mq5, compile it in MetaEditor, and attach it to the broker's XAU/USD chart.",
            "Add this site's HTTPS origin to MT5 Tools → Options → Expert Advisors → Allow WebRequest.",
            "Paste the one-time bridge URL and token into the EA inputs, then enable Algo Trading.",
        ],
    )


@router.patch("/mt5/account", response_model=Mt5Account)
async def update_account(body: Mt5SettingsPatch, request: Request) -> Mt5Account:
    user = await auth.require_subscription(request)
    account = await db.mt5_accounts.find_one({"user_id": user["id"], "revoked": {"$ne": True}})
    if not account:
        raise HTTPException(status_code=404, detail="connect an MT5 account first")
    updates = body.model_dump(exclude_none=True)
    if "lot_size" in updates:
        trial = {**account, "lot_size": updates["lot_size"]}
        if account.get("volume_min"):
            valid, detail = mt5_execution.lot_valid(trial)
            if not valid:
                raise HTTPException(status_code=422, detail=detail)
    if updates.get("auto_trade_enabled"):
        if not mt5_execution.connected(account):
            raise HTTPException(status_code=409, detail="MT5 bridge is offline")
        if not auth.is_mt5_live_entitled(user):
            raise HTTPException(status_code=402, detail="an active MT5 Auto-Trading subscription is required")
        if not account.get("trade_allowed") or not account.get("algo_trading"):
            raise HTTPException(status_code=409, detail="enable trading and Algo Trading in MT5 first")
        valid, detail = mt5_execution.lot_valid({**account, **updates})
        if not valid:
            raise HTTPException(status_code=422, detail=detail)
    if updates:
        updates["updated_at"] = auth.now()
        await db.mt5_accounts.update_one({"id": account["id"]}, {"$set": updates})
    fresh = await db.mt5_accounts.find_one({"id": account["id"]}) or account
    return await _public(fresh, user)


@router.delete("/mt5/account")
async def disconnect_account(request: Request) -> Dict[str, str]:
    user = await auth.require_subscription(request)
    account = await db.mt5_accounts.find_one({"user_id": user["id"], "revoked": {"$ne": True}})
    if not account:
        raise HTTPException(status_code=404, detail="MT5 account not found")
    position = await _position(account["id"])
    await db.mt5_accounts.update_one(
        {"id": account["id"]},
        {"$set": {"revoked": True, "auto_trade_enabled": False, "status": "revoked", "updated_at": auth.now()}},
    )
    await db.mt5_commands.update_many(
        {"account_id": account["id"], "status": {"$in": ["pending", "dispatched", "accepted"]}},
        {"$set": {"status": "cancelled", "completed_at": auth.now(), "broker_message": "account disconnected"}},
    )
    if position:
        await db.mt5_positions.update_one(
            {"account_id": account["id"], "ticket": position["ticket"]},
            {
                "$set": {
                    "detached": True,
                    "detached_at": auth.now(),
                    "detach_reason": "user immediately revoked the MT5 bridge",
                }
            },
        )
        return {
            "message": "MT5 disconnected immediately. The app no longer monitors the open trade; broker SL/TP and the local EA continue managing it."
        }
    return {"message": "MT5 account disconnected and bridge token revoked"}


@router.get("/mt5/commands", response_model=List[Mt5Command])
async def command_history(request: Request) -> List[Mt5Command]:
    user = await auth.require_subscription(request)
    account = await db.mt5_accounts.find_one({"user_id": user["id"], "revoked": {"$ne": True}})
    if not account:
        return []
    docs = await db.mt5_commands.find({"account_id": account["id"]}).sort("created_at", -1).to_list(100)
    return [Mt5Command(**_clean(doc)) for doc in docs]


@router.post("/mt5/bridge/heartbeat", response_model=Mt5Account)
async def bridge_heartbeat(
    body: BridgeHeartbeat, authorization: str | None = Header(default=None)
) -> Mt5Account:
    account = await _bridge_account(authorization)
    expected_login = str(account["account_login"])
    reported_login = body.account_login.strip()
    expected_server = str(account["broker_server"])
    reported_server = body.broker_server.strip()
    if not hmac.compare_digest(expected_login, reported_login):
        detail = f"EA login {reported_login} does not match connected login {expected_login}"
        await db.mt5_accounts.update_one(
            {"id": account["id"]},
            {"$set": {"status": "error", "last_error": detail, "last_poll_at": auth.now()}},
        )
        raise HTTPException(status_code=403, detail=detail)
    if not hmac.compare_digest(expected_server.lower(), reported_server.lower()):
        detail = f"EA server '{reported_server}' does not match connected server '{expected_server}'"
        await db.mt5_accounts.update_one(
            {"id": account["id"]},
            {"$set": {"status": "error", "last_error": detail, "last_poll_at": auth.now()}},
        )
        raise HTTPException(status_code=403, detail=detail)
    if (account["mode"] == "demo") != body.is_demo:
        reported_mode = "demo" if body.is_demo else "live"
        detail = f"EA reports {reported_mode} mode but this connection is configured as {account['mode']}"
        await db.mt5_accounts.update_one(
            {"id": account["id"]},
            {"$set": {"status": "error", "last_error": detail, "last_poll_at": auth.now()}},
        )
        raise HTTPException(status_code=403, detail=detail)
    if not mt5_execution.xau_symbol(body.resolved_symbol):
        await db.mt5_accounts.update_one(
            {"id": account["id"]}, {"$set": {"status": "error", "last_error": "broker XAU/USD symbol not found"}}
        )
        raise HTTPException(status_code=422, detail="resolved symbol is not an approved XAU/USD alias")
    if len(body.positions) > 1:
        raise HTTPException(status_code=409, detail="only one bot-managed XAU/USD position is allowed")
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
        "last_error": "" if body.trade_allowed and body.algo_trading else "trading or Algo Trading is disabled in MT5",
        "updated_at": auth.now(),
    }
    await db.mt5_accounts.update_one({"id": account["id"]}, {"$set": updates})
    previous_positions = await db.mt5_positions.find(
        {"account_id": account["id"], "status": "OPEN"}
    ).to_list(10)
    open_tickets: List[str] = []
    for pos in body.positions:
        if not mt5_execution.xau_symbol(pos.symbol):
            continue
        open_tickets.append(pos.ticket)
        await db.mt5_positions.update_one(
            {"account_id": account["id"], "ticket": pos.ticket},
            {
                "$set": {
                    **pos.model_dump(),
                    "account_id": account["id"],
                    "user_id": account["user_id"],
                    "status": "OPEN",
                    "updated_at": auth.now(),
                },
                "$setOnInsert": {"created_at": auth.now()},
            },
            upsert=True,
        )
        unresolved_entry = await db.mt5_commands.find_one(
            {
                "account_id": account["id"],
                "action": "ENTRY",
                "status": {"$in": ["pending", "dispatched", "accepted"]},
                "direction": pos.direction,
                "$or": [{"broker_ticket": pos.ticket}, {"broker_ticket": None}, {"broker_ticket": ""}],
            },
            sort=[("created_at", -1)],
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
    close_query: Dict[str, Any] = {"account_id": account["id"], "status": "OPEN"}
    if open_tickets:
        close_query["ticket"] = {"$nin": open_tickets}
    await db.mt5_positions.update_many(
        close_query, {"$set": {"status": "CLOSED", "closed_at": auth.now(), "updated_at": auth.now()}}
    )
    for previous in previous_positions:
        if previous.get("ticket") in open_tickets:
            continue
        unresolved_close = await db.mt5_commands.find_one(
            {
                "account_id": account["id"],
                "action": "CLOSE",
                "status": {"$in": ["pending", "dispatched", "accepted"]},
                "payload.ticket": previous.get("ticket"),
            },
            sort=[("created_at", -1)],
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
    fresh = await db.mt5_accounts.find_one({"id": account["id"]}) or {**account, **updates}
    return await _public(fresh)


@router.post("/mt5/bridge/poll", response_model=BridgePollResponse)
async def bridge_poll(authorization: str | None = Header(default=None)) -> BridgePollResponse:
    account = await _bridge_account(authorization)
    await db.mt5_accounts.update_one({"id": account["id"]}, {"$set": {"last_poll_at": auth.now()}})
    while True:
        command = await db.mt5_commands.find_one(
            {"account_id": account["id"], "status": {"$in": ["pending", "dispatched"]}},
            sort=[("created_at", 1)],
        )
        if not command:
            return BridgePollResponse(command=None, server_time=auth.now())
        expires = auth.aware(command.get("expires_at"))
        user = await db.users.find_one({"id": account["user_id"]}) if command["action"] == "ENTRY" else None
        expired = bool(expires and expires <= auth.now())
        entry_blocked = command["action"] == "ENTRY" and (
            expired
            or not account.get("auto_trade_enabled")
            or not auth.is_subscribed(user)
            or not auth.is_mt5_live_entitled(user)
        )
        if entry_blocked:
            status = "expired" if expired else "cancelled"
            await db.mt5_commands.update_one(
                {"id": command["id"]},
                {"$set": {"status": status, "completed_at": auth.now(), "broker_message": "entry blocked: normal/MT5 entitlement missing, command expired, or auto-trading disabled"}},
            )
            continue
        updated = await db.mt5_commands.find_one_and_update(
            {"id": command["id"], "status": {"$in": ["pending", "dispatched"]}},
            {"$set": {"status": "dispatched", "last_dispatched_at": auth.now()}, "$inc": {"attempts": 1}},
            return_document=ReturnDocument.AFTER,
        )
        return BridgePollResponse(command=Mt5Command(**_clean(updated or command)), server_time=auth.now())


@router.post("/mt5/bridge/ack", response_model=Mt5Command)
async def bridge_ack(body: BridgeAck, authorization: str | None = Header(default=None)) -> Mt5Command:
    account = await _bridge_account(authorization)
    command = await db.mt5_commands.find_one({"id": body.command_id, "account_id": account["id"]})
    if not command:
        raise HTTPException(status_code=404, detail="command not found")
    result = body.result
    if result is None:
        if body.success is None:
            raise HTTPException(status_code=422, detail="result or success is required")
        result = "executed" if body.success else "rejected"
    status = "confirmed" if result == "executed" else "accepted" if result == "accepted" else "rejected"
    if command.get("status") in ("confirmed", "cancelled", "expired"):
        return Mt5Command(**_clean(command))
    updated = await db.mt5_commands.find_one_and_update(
        {"id": command["id"], "status": {"$in": ["pending", "dispatched", "accepted", "rejected"]}},
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
    return Mt5Command(**_clean(updated or command))


@router.get("/admin/mt5/accounts", response_model=List[AdminMt5Account], dependencies=[Depends(auth.require_admin)])
async def admin_accounts() -> List[AdminMt5Account]:
    docs = await db.mt5_accounts.find({"revoked": {"$ne": True}}).sort("created_at", -1).to_list(500)
    return [AdminMt5Account(**(await _public(doc)).model_dump()) for doc in docs]


@router.post("/admin/mt5/accounts/{account_id}/disable", response_model=Mt5Account, dependencies=[Depends(auth.require_admin)])
async def admin_disable(account_id: str) -> Mt5Account:
    account = await db.mt5_accounts.find_one_and_update(
        {"id": account_id},
        {"$set": {"auto_trade_enabled": False, "last_error": "disabled by admin", "updated_at": auth.now()}},
        return_document=ReturnDocument.AFTER,
    )
    if not account:
        raise HTTPException(status_code=404, detail="MT5 account not found")
    return await _public(account)