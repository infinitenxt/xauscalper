"""BTC market-session awareness.

BTC trades 24/7, including weekends.

London and New York overlap is treated as the highest-liquidity period,
while Asian and off-major-session periods are informational only.

Session filtering never blocks BTC trades because the BTC market remains
open around the clock.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Dict, List


# ---------------------------------------------------------------------------
# Major liquidity sessions (UTC)
# ---------------------------------------------------------------------------

SESSIONS: List[Dict[str, Any]] = [
    {
        "name": "Sydney",
        "start": 21,
        "end": 6,
        "weight": 1,
    },
    {
        "name": "Tokyo",
        "start": 0,
        "end": 9,
        "weight": 1,
    },
    {
        "name": "London",
        "start": 7,
        "end": 16,
        "weight": 3,
    },
    {
        "name": "New York",
        "start": 12,
        "end": 21,
        "weight": 3,
    },
]


LIQUIDITY_NOTES = {
    "PEAK": (
        "London and New York are both active — "
        "strong global participation and typically the deepest liquidity window."
    ),
    "HIGH": (
        "A major global session is active — "
        "market participation and liquidity are generally strong."
    ),
    "MEDIUM": (
        "Asian sessions are active — "
        "BTC remains fully tradeable, but liquidity can be lighter."
    ),
    "LOW": (
        "No major traditional session is active — "
        "BTC is still open and tradeable 24/7."
    ),
}


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _in_session(
    minute_of_day: int,
    start_h: int,
    end_h: int,
) -> bool:
    start = start_h * 60
    end = end_h * 60

    if start <= end:
        return start <= minute_of_day < end

    return (
        minute_of_day >= start
        or minute_of_day < end
    )


def _minutes_until(
    minute_of_day: int,
    target_h: int,
) -> int:
    target = target_h * 60
    delta = target - minute_of_day

    return delta if delta > 0 else delta + 1440


# ---------------------------------------------------------------------------
# Session classification
# ---------------------------------------------------------------------------

def classify(dt: datetime) -> str:
    """Return the dominant liquidity session for a timestamp."""

    minute_of_day = (
        dt.hour * 60
        + dt.minute
    )

    london = _in_session(
        minute_of_day,
        7,
        16,
    )

    new_york = _in_session(
        minute_of_day,
        12,
        21,
    )

    asian = (
        _in_session(
            minute_of_day,
            0,
            9,
        )
        or _in_session(
            minute_of_day,
            21,
            6,
        )
    )

    if london and new_york:
        return "London × New York"

    if london:
        return "London"

    if new_york:
        return "New York"

    if asian:
        return "Asian"

    return "Off-session"


BUCKETS = [
    "Asian",
    "London",
    "London × New York",
    "New York",
    "Off-session",
]


# ---------------------------------------------------------------------------
# Snapshot
# ---------------------------------------------------------------------------

def snapshot(
    at: datetime | None = None,
) -> Dict[str, Any]:
    """Return the current BTC liquidity/session snapshot."""

    now = at or datetime.now(timezone.utc)

    minute_of_day = (
        now.hour * 60
        + now.minute
    )

    rows: List[Dict[str, Any]] = []

    weight = 0
    active_names: List[str] = []

    for session in SESSIONS:
        active = _in_session(
            minute_of_day,
            int(session["start"]),
            int(session["end"]),
        )

        if active:
            weight += int(
                session["weight"]
            )

            active_names.append(
                str(session["name"])
            )

        rows.append(
            {
                "name": session["name"],
                "active": active,
                "open_utc": (
                    f"{int(session['start']):02d}:00"
                ),
                "close_utc": (
                    f"{int(session['end']):02d}:00"
                ),
                "minutes_to_open": (
                    0
                    if active
                    else _minutes_until(
                        minute_of_day,
                        int(session["start"]),
                    )
                ),
                "minutes_to_close": (
                    _minutes_until(
                        minute_of_day,
                        int(session["end"]),
                    )
                    if active
                    else 0
                ),
            }
        )

    london = any(
        row["name"] == "London"
        and row["active"]
        for row in rows
    )

    new_york = any(
        row["name"] == "New York"
        and row["active"]
        for row in rows
    )

    if london and new_york:
        liquidity = "PEAK"

    elif london or new_york:
        liquidity = "HIGH"

    elif weight > 0:
        liquidity = "MEDIUM"

    else:
        liquidity = "LOW"

    # BTC never closes.
    # Session liquidity is informational and must not block trading.
    tradeable = True

    # Calculate next London/New York overlap.
    overlap_active = (
        london
        and new_york
    )

    if overlap_active:
        minutes_to_overlap = 0
    else:
        overlap_minutes = 12 * 60

        current_minutes = minute_of_day

        if current_minutes < overlap_minutes:
            minutes_to_overlap = (
                overlap_minutes
                - current_minutes
            )
        else:
            minutes_to_overlap = (
                1440
                - current_minutes
                + overlap_minutes
            )

    return {
        "utc_time": now.strftime(
            "%H:%M"
        ),
        "sessions": rows,
        "active": active_names,
        "liquidity": liquidity,
        "tradeable": tradeable,
        "note": LIQUIDITY_NOTES[liquidity],
        "overlap_active": overlap_active,
        "minutes_to_overlap": int(
            minutes_to_overlap
        ),
    }