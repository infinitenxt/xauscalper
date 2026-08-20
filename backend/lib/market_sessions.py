"""Forex/gold trading-session awareness (all times UTC).

Gold moves on London and New York liquidity. The overlap (12:00–16:00 UTC) is the
highest-quality window for scalping; the Asia-only and post-New-York hours are
where spreads widen and scalps get chopped up. The engine can refuse to trade in
LOW-liquidity hours (settings key ``session_filter_enabled``).
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List

# name, open hour UTC, close hour UTC (wraps past midnight when start > end)
SESSIONS: List[Dict[str, Any]] = [
    {"name": "Sydney", "start": 21, "end": 6, "weight": 1},
    {"name": "Tokyo", "start": 0, "end": 9, "weight": 1},
    {"name": "London", "start": 7, "end": 16, "weight": 3},
    {"name": "New York", "start": 12, "end": 21, "weight": 3},
]

LIQUIDITY_NOTES = {
    "PEAK": "London and New York are both open — deepest liquidity of the day and the best window for gold scalps.",
    "HIGH": "A major session is open, so gold has real participation and moves are more likely to follow through.",
    "MEDIUM": "Only Asian sessions are open. Gold tends to range here, and breakouts often fail.",
    "LOW": "No major session is open. Spreads widen and moves are thin — the worst time to scalp gold.",
}


def _in_session(minute_of_day: int, start_h: int, end_h: int) -> bool:
    start, end = start_h * 60, end_h * 60
    if start <= end:
        return start <= minute_of_day < end
    return minute_of_day >= start or minute_of_day < end


def _minutes_until(minute_of_day: int, target_h: int) -> int:
    target = target_h * 60
    delta = target - minute_of_day
    return delta if delta > 0 else delta + 1440


def snapshot(at: datetime | None = None) -> Dict[str, Any]:
    now = at or datetime.now(timezone.utc)
    mod = now.hour * 60 + now.minute
    rows: List[Dict[str, Any]] = []
    weight = 0
    active_names: List[str] = []
    for s in SESSIONS:
        active = _in_session(mod, int(s["start"]), int(s["end"]))
        if active:
            weight += int(s["weight"])
            active_names.append(str(s["name"]))
        rows.append(
            {
                "name": s["name"],
                "active": active,
                "open_utc": f"{int(s['start']):02d}:00",
                "close_utc": f"{int(s['end']):02d}:00",
                "minutes_to_open": 0 if active else _minutes_until(mod, int(s["start"])),
                "minutes_to_close": _minutes_until(mod, int(s["end"])) if active else 0,
            }
        )

    london = any(r["name"] == "London" and r["active"] for r in rows)
    ny = any(r["name"] == "New York" and r["active"] for r in rows)
    if london and ny:
        liquidity = "PEAK"
    elif london or ny:
        liquidity = "HIGH"
    elif weight > 0:
        liquidity = "MEDIUM"
    else:
        liquidity = "LOW"

    overlap_start = datetime(now.year, now.month, now.day, 12, tzinfo=timezone.utc)
    if now >= overlap_start:
        overlap_start += timedelta(days=1)
    return {
        "utc_time": now.strftime("%H:%M"),
        "sessions": rows,
        "active": active_names,
        "liquidity": liquidity,
        "tradeable": liquidity != "LOW",
        "note": LIQUIDITY_NOTES[liquidity],
        "overlap_active": london and ny,
        "minutes_to_overlap": 0 if (london and ny) else int((overlap_start - now).total_seconds() // 60),
    }
