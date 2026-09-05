"""Server-only MetaApi provisioning, synchronization and execution client."""
from __future__ import annotations

import asyncio
import os
import secrets
import time
from typing import Any, Dict, List, Optional
from urllib.parse import quote

import httpx

from lib import auth, strategy
from lib.db import db


class MetaApiError(RuntimeError):
    pass


PROVISIONING_URL = os.environ.get("METAAPI_PROVISIONING_URL", "https://mt-provisioning-api-v1.agiliumtrade.agiliumtrade.ai").rstrip("/")
CLIENT_URL_TEMPLATE = os.environ.get("METAAPI_CLIENT_URL_TEMPLATE", "https://mt-client-api-v1.{region}.agiliumtrade.ai")
_sync_locks: Dict[str, asyncio.Lock] = {}
_last_sync: Dict[str, float] = {}
TIMEFRAME_SECONDS = {"1m": 60, "5m": 300, "15m": 900, "30m": 1800, "1h": 3600}


def configured() -> bool:
    return bool(os.environ.get("METAAPI_TOKEN"))


def _headers(transaction_id: str = "") -> Dict[str, str]:
    token = os.environ.get("METAAPI_TOKEN", "")
    if not token:
        raise MetaApiError("MetaApi is not configured")
    headers = {"auth-token": token, "accept": "application/json", "content-type": "application/json"}
    if transaction_id:
        headers["transaction-id"] = transaction_id
    return headers


async def _request(method: str, url: str, *, payload: Optional[Dict[str, Any]] = None, transaction_id: str = "") -> Any:
    try:
        async with httpx.AsyncClient(timeout=httpx.Timeout(30.0, connect=10.0), follow_redirects=False) as client:
            response = await client.request(method, url, headers=_headers(transaction_id), json=payload)
    except httpx.HTTPError as exc:
        raise MetaApiError("MetaApi network request failed") from exc
    if response.status_code == 429:
        raise MetaApiError("MetaApi rate limit reached; retry shortly")
    if response.status_code >= 400:
        message = "MetaApi request failed"
        try:
            message = str(response.json().get("message") or message)
        except Exception:
            pass
        raise MetaApiError(message[:300])
    if not response.content:
        return {}
    return response.json()


async def list_accounts() -> List[Dict[str, Any]]:
    result = await _request("GET", f"{PROVISIONING_URL}/users/current/accounts")
    return result if isinstance(result, list) else []


async def provision(body: Any) -> Dict[str, Any]:
    transaction_id = secrets.token_hex(16)
    payload = {
        "login": body.login,
        "password": body.password,
        "name": body.account_name,
        "server": body.server,
        "platform": "mt5",
        "type": "cloud-g2",
        "region": body.region,
        "magic": 860081,
        "manualTrades": False,
        "reliability": "high",
    }
    result = await _request(
        "POST", f"{PROVISIONING_URL}/users/current/accounts", payload=payload, transaction_id=transaction_id
    )
    account_id = str(result.get("id") or result.get("_id") or "")
    if not account_id:
        raise MetaApiError("MetaApi did not return an account id")
    await _request("POST", f"{PROVISIONING_URL}/users/current/accounts/{account_id}/deploy")
    return {"account_id": account_id, "region": str(result.get("region") or body.region), "state": str(result.get("state") or "DEPLOYING")}


async def provisioning_account(account_id: str) -> Dict[str, Any]:
    result = await _request("GET", f"{PROVISIONING_URL}/users/current/accounts/{account_id}")
    return result if isinstance(result, dict) else {}


async def remove_account(account_id: str) -> None:
    try:
        await _request("POST", f"{PROVISIONING_URL}/users/current/accounts/{account_id}/undeploy")
    except MetaApiError:
        pass
    await _request("DELETE", f"{PROVISIONING_URL}/users/current/accounts/{account_id}")


def _client_base(region: str) -> str:
    return CLIENT_URL_TEMPLATE.format(region=region).rstrip("/")


async def _client(account: Dict[str, Any], method: str, path: str, payload: Optional[Dict[str, Any]] = None) -> Any:
    return await _request(method, f"{_client_base(account['metaapi_region'])}{path}", payload=payload)


async def _resolve_symbol(account: Dict[str, Any]) -> str:
    if account.get("resolved_symbol"):
        return str(account["resolved_symbol"])
    aid = account["metaapi_account_id"]
    symbols = await _client(account, "GET", f"/users/current/accounts/{aid}/symbols")
    wanted_xau = account.get("symbol") == "XAUUSD"
    for item in symbols if isinstance(symbols, list) else []:
        value = str(item if isinstance(item, str) else item.get("symbol") or "")
        upper = value.upper()
        if (wanted_xau and ("XAU" in upper or "GOLD" in upper)) or (not wanted_xau and ("BTC" in upper or "XBT" in upper)):
            return value
    raise MetaApiError("MetaApi account does not expose the selected broker symbol")


def _as_epoch(value: Any) -> int:
    if isinstance(value, (int, float)):
        return int(value / 1000 if value > 10_000_000_000 else value)
    if isinstance(value, str):
        try:
            from datetime import datetime
            return int(datetime.fromisoformat(value.replace("Z", "+00:00")).timestamp())
        except ValueError:
            return 0
    return 0


async def sync_account(account: Dict[str, Any], primary_timeframe: str = "5m", force: bool = False) -> Dict[str, Any]:
    aid = str(account.get("metaapi_account_id") or "")
    if not aid:
        return account
    if not force and time.time() - _last_sync.get(aid, 0.0) < 4.0:
        return await db.mt5_accounts.find_one({"id": account["id"]}) or account
    lock = _sync_locks.setdefault(aid, asyncio.Lock())
    async with lock:
        if not force and time.time() - _last_sync.get(aid, 0.0) < 4.0:
            return await db.mt5_accounts.find_one({"id": account["id"]}) or account
        try:
            provisioned = await provisioning_account(aid)
            state = str(provisioned.get("state") or "")
            connection = str(provisioned.get("connectionStatus") or "")
            base_updates = {"metaapi_state": state, "metaapi_connection_status": connection, "status": "connected" if connection == "CONNECTED" else state.lower() or "deploying", "updated_at": auth.now()}
            if connection != "CONNECTED":
                await db.mt5_accounts.update_one({"id": account["id"]}, {"$set": base_updates})
                _last_sync[aid] = time.time()
                return {**account, **base_updates}

            resolved = await _resolve_symbol(account)
            quoted = quote(resolved, safe="")
            info, positions, tick, specification = await asyncio.gather(
                _client(account, "GET", f"/users/current/accounts/{aid}/account-information"),
                _client(account, "GET", f"/users/current/accounts/{aid}/positions"),
                _client(account, "GET", f"/users/current/accounts/{aid}/symbols/{quoted}/current-tick"),
                _client(account, "GET", f"/users/current/accounts/{aid}/symbols/{quoted}/specification"),
            )
            bid = float((tick or {}).get("bid") or 0.0)
            ask = float((tick or {}).get("ask") or 0.0)
            now = auth.now()
            updates = {
                **base_updates,
                "resolved_symbol": resolved,
                "balance": float((info or {}).get("balance") or 0.0),
                "equity": float((info or {}).get("equity") or 0.0),
                "margin": float((info or {}).get("margin") or 0.0),
                "free_margin": float((info or {}).get("freeMargin") or 0.0),
                "margin_level": float((info or {}).get("marginLevel") or 0.0),
                "account_currency": str((info or {}).get("currency") or ""),
                "trade_allowed": True,
                "algo_trading": True,
                "last_heartbeat_at": now,
                "last_seen_at": now,
                "broker_tick_at": now,
                "broker_bid": bid,
                "broker_ask": ask,
                "broker_spread_points": max(0.0, ask - bid),
                "broker_symbol": resolved,
                "broker_day": now.strftime("%Y.%m.%d"),
                "volume_min": float((specification or {}).get("minVolume") or 0.01),
                "volume_max": float((specification or {}).get("maxVolume") or 100.0),
                "volume_step": float((specification or {}).get("volumeStep") or 0.01),
            }
            needed = dict.fromkeys([primary_timeframe] + strategy.MTF_MAP.get(primary_timeframe, []))
            operations = []
            from pymongo import UpdateOne
            for timeframe in needed:
                candles = await _client(account, "GET", f"/users/current/accounts/{aid}/historical-market-data/symbols/{quoted}/timeframes/{timeframe}/candles?limit=300")
                for candle in candles if isinstance(candles, list) else []:
                    open_time = _as_epoch(candle.get("time"))
                    if not open_time:
                        continue
                    doc = {
                        "account_id": account["id"], "user_id": account["user_id"], "broker_server": "MetaApi",
                        "symbol": resolved, "app_symbol": account.get("symbol"), "timeframe": timeframe,
                        "open_time": open_time, "duration_seconds": TIMEFRAME_SECONDS.get(timeframe, 60),
                        "open": float(candle.get("open") or 0.0), "high": float(candle.get("high") or 0.0),
                        "low": float(candle.get("low") or 0.0), "close": float(candle.get("close") or 0.0),
                        "tick_volume": float(candle.get("tickVolume") or candle.get("volume") or 0.0),
                        "spread_points": 0, "received_at": now,
                    }
                    operations.append(UpdateOne({"account_id": account["id"], "timeframe": timeframe, "open_time": open_time}, {"$set": doc}, upsert=True))
            if operations:
                await db.broker_candles.bulk_write(operations, ordered=False)
            primary_count = await db.broker_candles.count_documents({"account_id": account["id"], "timeframe": primary_timeframe})
            updates.update({"broker_data_ready": primary_count >= 60, "broker_data_source": "broker" if primary_count >= 60 else "syncing"})
            await db.mt5_accounts.update_one({"id": account["id"]}, {"$set": updates})

            open_tickets = []
            for position in positions if isinstance(positions, list) else []:
                ticket = str(position.get("id") or position.get("positionId") or "")
                if not ticket:
                    continue
                open_tickets.append(ticket)
                direction = "BUY" if str(position.get("type") or "").upper().endswith("BUY") else "SELL"
                await db.mt5_positions.update_one(
                    {"account_id": account["id"], "ticket": ticket},
                    {"$set": {"account_id": account["id"], "user_id": account["user_id"], "ticket": ticket, "symbol": str(position.get("symbol") or resolved), "direction": direction, "volume": float(position.get("volume") or 0.0), "entry_price": float(position.get("openPrice") or 0.0), "current_price": float(position.get("currentPrice") or 0.0), "sl": float(position.get("stopLoss") or 0.0), "tp": float(position.get("takeProfit") or 0.0), "profit": float(position.get("profit") or 0.0), "opened_at": position.get("time"), "status": "OPEN", "updated_at": now}}, upsert=True,
                )
            close_query: Dict[str, Any] = {"account_id": account["id"], "status": "OPEN"}
            if open_tickets:
                close_query["ticket"] = {"$nin": open_tickets}
            await db.mt5_positions.update_many(close_query, {"$set": {"status": "CLOSED", "closed_at": now, "updated_at": now}})
            _last_sync[aid] = time.time()
            return await db.mt5_accounts.find_one({"id": account["id"]}) or {**account, **updates}
        except MetaApiError as exc:
            safe = str(exc)[:300]
            await db.mt5_accounts.update_one({"id": account["id"]}, {"$set": {"status": "error", "last_error": safe, "updated_at": auth.now()}})
            _last_sync[aid] = time.time()
            return await db.mt5_accounts.find_one({"id": account["id"]}) or account


async def execute_command(account: Dict[str, Any], command: Dict[str, Any]) -> Dict[str, Any]:
    aid = account["metaapi_account_id"]
    symbol = account.get("resolved_symbol") or await _resolve_symbol(account)
    payload = command.get("payload") or {}
    client_id = f"gt-{command['id'][:28]}"
    if command["action"] == "ENTRY":
        tick = await _client(account, "GET", f"/users/current/accounts/{aid}/symbols/{quote(symbol, safe='')}/current-tick")
        direction = command["direction"]
        price = float(tick.get("ask") if direction == "BUY" else tick.get("bid"))
        sl_distance = float(command.get("sl_dist") or payload.get("sl_dist") or 0.0)
        tp_distance = float(command.get("tp_dist") or payload.get("tp_dist") or 0.0)
        trade = {
            "actionType": f"ORDER_TYPE_{direction}", "symbol": symbol, "volume": float(command["lots"]),
            "stopLoss": price - sl_distance if direction == "BUY" else price + sl_distance,
            "takeProfit": price + tp_distance if direction == "BUY" else price - tp_distance,
            "clientId": client_id,
            "trailingStopLoss": {"distance": {"distance": float(payload.get("trail_distance") or sl_distance * 0.6), "units": "RELATIVE_PRICE"}},
        }
    else:
        trade = {"actionType": "POSITION_CLOSE_ID", "positionId": str(payload.get("ticket") or command.get("broker_ticket") or ""), "clientId": client_id}
    try:
        result = await _client(account, "POST", f"/users/current/accounts/{aid}/trade", payload=trade)
        code = int((result or {}).get("numericCode") or 0)
        success = code in (10008, 10009, 10010) or str((result or {}).get("stringCode") or "") in ("TRADE_RETCODE_PLACED", "TRADE_RETCODE_DONE", "TRADE_RETCODE_DONE_PARTIAL")
        status = "confirmed" if success else "rejected"
        updates = {"status": status, "execution_result": "executed" if success else "rejected", "broker_ticket": str((result or {}).get("positionId") or (result or {}).get("orderId") or ""), "broker_retcode": code or None, "broker_message": str((result or {}).get("message") or (result or {}).get("stringCode") or "")[:500], "completed_at": auth.now()}
    except MetaApiError as exc:
        updates = {"status": "rejected", "execution_result": "failed", "broker_message": str(exc)[:500], "completed_at": auth.now()}
    await db.mt5_commands.update_one({"id": command["id"]}, {"$set": updates})
    return {**command, **updates}