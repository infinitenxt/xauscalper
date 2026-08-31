"""AI trade narrator.

The ONLY place an LLM is used: turning the engine's structured entry facts into a
short, human explanation of why the trade was taken. Everything else in the app
(signals, sizing, exits) stays fully deterministic.

Design notes:
- Non-blocking: the engine opens the trade first and fires this off as a task,
  then patches the trade document when the text arrives. Entry latency is zero.
- Always degrades: if the key is missing, the call errors, or it times out, the
  deterministic reason list is used instead and ``ai_status`` says so.
"""
from __future__ import annotations

import asyncio
import logging
import os
from typing import Any, Dict, List, Tuple

logger = logging.getLogger("narrator")

MODEL_PROVIDER = "openai"
MODEL_NAME = "gpt-5.4"
TIMEOUT_SECONDS = 25.0

SYSTEM_MESSAGE = (
    "You are the desk analyst for an educational bitcoin (BTCUSDT) scalping bot. "
    "You are handed the exact technical facts behind a paper trade that was just opened. "
    "Write a tight explanation of why this trade was taken, in 3 to 4 sentences, "
    "in plain confident trading-desk English.\n\n"
    "Rules:\n"
    "- Open by naming the setup itself. Never begin with 'This trade was taken because', "
    "'This long was taken', 'This position' or any similar filler.\n"
    "- Lead with the core reason the setup was taken, then the confirmations that mattered most.\n"
    "- Explain in one sentence why the stop and target sit where they do.\n"
    "- Never promise or predict a result. No 'will', no 'guaranteed'. Frame it as a probability-weighted setup.\n"
    "- Never invent numbers or indicators that are not in the facts.\n"
    "- No markdown, no bullet points, no headings, no emoji. Plain prose only.\n"
    "- Do not mention that you are an AI or that you were given facts."
)


def _fallback(facts: Dict[str, Any]) -> str:
    reasons: List[str] = list(facts.get("entry_reasons") or [])
    risk: List[str] = list(facts.get("risk_reasons") or [])
    parts = reasons[:4] + risk[:2]
    return " ".join(p.rstrip(".") + "." for p in parts if p)


def _prompt(facts: Dict[str, Any]) -> str:
    aligned = facts.get("aligned_confirmations") or []
    lines = [
        f"Direction: {facts.get('direction')}",
        f"Symbol: {facts.get('symbol')} on the {facts.get('timeframe')} timeframe (scalp)",
        f"Entry: {facts.get('entry')}",
        f"Stop loss: {facts.get('sl')}",
        f"Take profit: {facts.get('tp')}",
        f"Planned reward:risk: {facts.get('rr')}",
        f"Confluence confidence: {facts.get('confidence')}% "
        f"(bull {facts.get('bull_score')} vs bear {facts.get('bear_score')})",
        f"ATR: {facts.get('atr')}",
        f"Position: {facts.get('qty')} oz, risking {facts.get('risk_amount')} USDT",
        "",
        "Confirmations that agreed with the direction:",
    ]
    for c in aligned:
        lines.append(f"- {c.get('name')} ({c.get('direction')}, weight {c.get('weight')}): {c.get('detail')}")
    struct = facts.get("structure") or {}
    pattern = facts.get("pattern") or {}
    lines += [
        "",
        f"Market structure: {struct.get('label')} — {struct.get('detail')}",
        f"Last candle price action: {pattern.get('label')} — {pattern.get('detail')}",
        "",
        "Stop and target rationale from the risk engine:",
    ]
    for r in facts.get("level_reasons") or []:
        lines.append(f"- {r}")
    return "\n".join(lines)


async def explain_trade(facts: Dict[str, Any]) -> Tuple[str, str]:
    """Return (explanation, status) where status is 'ai' or 'unavailable'."""
    key = os.environ.get("EMERGENT_LLM_KEY")
    if not key:
        logger.warning("EMERGENT_LLM_KEY missing — using deterministic explanation")
        return _fallback(facts), "unavailable"
    try:
        from emergentintegrations.llm.chat import LlmChat, UserMessage

        chat = LlmChat(
            api_key=key,
            session_id=f"trade-{facts.get('trade_id')}",
            system_message=SYSTEM_MESSAGE,
        ).with_model(MODEL_PROVIDER, MODEL_NAME)
        reply = await asyncio.wait_for(
            chat.send_message(UserMessage(text=_prompt(facts))), timeout=TIMEOUT_SECONDS
        )
        text = (reply if isinstance(reply, str) else str(reply)).strip()
        if not text:
            return _fallback(facts), "unavailable"
        return text, "ai"
    except asyncio.TimeoutError:
        logger.warning("narrator timed out after %ss", TIMEOUT_SECONDS)
        return _fallback(facts), "unavailable"
    except Exception as exc:  # noqa: BLE001
        logger.warning("narrator failed: %s", exc)
        return _fallback(facts), "unavailable"
