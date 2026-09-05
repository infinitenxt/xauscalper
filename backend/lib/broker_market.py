"""Broker-matched MT5 ticks and closed-candle storage/read path."""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Dict, List

from pymongo import UpdateOne

from lib import auth, strategy
from lib.db import db


BROKER_TICK_STALE_SECONDS = 10


def family(symbol: str) -> str:
    value = symbol.upper().replace("/", "")
    if "XAU" in value or "GOLD" in value:
        return "XAU"
    if "BTC" in value or "XBT" in value or "BITCOIN" in value:
        return "BTC"
    return ""


def app_family(symbol: str) -> str:
    return "XAU" if symbol.upper() == "XAUUSD" else "BTC"


async def ingest(account: Dict[str, Any], body: Any) -> Dict[str, Any]:
    if family(body.symbol) != app_family(str(account.get("symbol") or "BTCUSDT")):
        raise ValueError("broker symbol does not match the connected asset")
    if body.ask < body.bid:
        raise ValueError("broker ASK cannot be below BID")

    now = auth.now()
    operations: List[UpdateOne] = []
    for bar in body.bars:
        doc = {
            "account_id": account["id"],
            "user_id": account["user_id"],
            "broker_server": account["broker_server"],
            "symbol": body.symbol,
            "app_symbol": account.get("symbol") or "BTCUSDT",
            **bar.model_dump(),
            "received_at": now,
        }
        operations.append(
            UpdateOne(
                {
                    "account_id": account["id"],
                    "timeframe": bar.timeframe,
                    "open_time": bar.open_time,
                },
                {"$set": doc},
                upsert=True,
            )
        )
    if operations:
        await db.broker_candles.bulk_write(operations, ordered=False)

    await db.broker_ticks.insert_one(
        {
            "account_id": account["id"],
            "user_id": account["user_id"],
            "symbol": body.symbol,
            "bid": body.bid,
            "ask": body.ask,
            "spread_points": body.spread_points,
            "tick_time": datetime.fromtimestamp(body.tick_time, tz=timezone.utc),
            "captured_at": now,
        }
    )
    primary = str((await db.settings.find_one({"user_id": account["user_id"]}) or {}).get("primary_timeframe") or "5m")
    primary_count = await db.broker_candles.count_documents(
        {"account_id": account["id"], "timeframe": primary}
    )
    ready = primary_count >= 60
    await db.mt5_accounts.update_one(
        {"id": account["id"]},
        {
            "$set": {
                "broker_data_ready": ready,
                "broker_data_source": "broker" if ready else "syncing",
                "broker_tick_at": now,
                "broker_bid": body.bid,
                "broker_ask": body.ask,
                "broker_spread_points": body.spread_points,
                "broker_point": body.point,
                "broker_digits": body.digits,
                "broker_trade_stops_level": body.trade_stops_level,
                "broker_contract_size": body.contract_size,
                "broker_symbol": body.symbol,
                "broker_day": body.broker_day or now.strftime("%Y.%m.%d"),
            }
        },
    )
    if ready:
        pending = await db.mt5_survival.find_one({"account_id": account["id"], "activation_requested": True})
        if pending:
            from lib import survival
            fresh_account = await db.mt5_accounts.find_one({"id": account["id"]}) or account
            await survival.activate_pending(fresh_account)
    return {"accepted_bars": len(body.bars), "broker_data_ready": ready, "source": "broker" if ready else "syncing"}


async def bundle(account: Dict[str, Any], timeframe: str) -> Dict[str, Any]:
    fresh_account = await db.mt5_accounts.find_one({"id": account["id"]}) or account
    seen = auth.aware(fresh_account.get("broker_tick_at"))
    fresh = bool(seen and (auth.now() - seen).total_seconds() <= BROKER_TICK_STALE_SECONDS)
    if not fresh or not fresh_account.get("broker_data_ready"):
        if fresh_account.get("broker_data_source") not in ("syncing", "stale"):
            await db.mt5_accounts.update_one(
                {"id": account["id"]},
                {"$set": {"broker_data_source": "stale" if fresh_account.get("broker_data_ready") else "syncing"}},
            )
        return {"ready": False, "fresh": fresh, "candles_by_tf": {}, "price": 0.0}

    candles_by_tf: Dict[str, List[Dict[str, float]]] = {}
    needed = dict.fromkeys([timeframe] + strategy.MTF_MAP.get(timeframe, []))
    for tf in needed:
        rows = await db.broker_candles.find(
            {"account_id": account["id"], "timeframe": tf}, {"_id": 0}
        ).sort("open_time", -1).limit(300).to_list(300)
        rows.reverse()
        if rows:
            candles_by_tf[tf] = [
                {
                    "time": int(row["open_time"]),
                    "open": float(row["open"]),
                    "high": float(row["high"]),
                    "low": float(row["low"]),
                    "close": float(row["close"]),
                    "volume": float(row.get("tick_volume") or 0.0),
                    "close_time": int(row["open_time"]) + int(row.get("duration_seconds") or 60),
                }
                for row in rows
            ]
    ready = len(candles_by_tf.get(timeframe, [])) >= 60
    bid = float(fresh_account.get("broker_bid") or 0.0)
    ask = float(fresh_account.get("broker_ask") or 0.0)
    return {
        "ready": ready,
        "fresh": fresh,
        "candles_by_tf": candles_by_tf,
        "price": (bid + ask) / 2 if bid and ask else bid or ask,
        "broker_symbol": fresh_account.get("broker_symbol") or fresh_account.get("resolved_symbol") or "",
        "tick_at": seen,
    }


async def account_for_user(user_id: str, app_symbol: str) -> Dict[str, Any] | None:
    return await db.mt5_accounts.find_one(
        {"user_id": user_id, "symbol": app_symbol, "revoked": {"$ne": True}}
    )