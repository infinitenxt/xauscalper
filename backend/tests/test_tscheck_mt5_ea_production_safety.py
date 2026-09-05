"""Downloaded EA has production-safe local management.

Criterion: UniversalTerminalBridge.mq5 defaults BridgeUrl to the production
bridge, persists trailing/max-hold settings via GlobalVariables (so they
survive an EA/terminal restart), advances the stop only toward profit, and
hard-closes at max hold even after a restart. Verified statically -- no
Windows MT5 terminal is available in this environment (see spec deviations).
"""

import os

EA_PATH = os.path.join(
    os.path.dirname(__file__), "..", "..", "frontend", "public", "UniversalTerminalBridge.mq5"
)


def _source() -> str:
    assert os.path.isfile(EA_PATH), f"EA file not found at {EA_PATH}"
    with open(EA_PATH, encoding="utf-8") as f:
        return f.read()


def test_default_bridge_url_is_the_production_endpoint():
    src = _source()
    assert 'input string BridgeUrl = "https://trade.infinitenxt.com/api/mt5/bridge";' in src


def test_trailing_and_max_hold_settings_persist_via_global_variables():
    src = _source()
    # Written once on entry ...
    assert 'GlobalVariableSet(gv_prefix + "maxhold", JsonNumber(json, "max_hold_seconds", 1200.0));' in src
    assert 'GlobalVariableSet(gv_prefix + "trailenabled", JsonNumber(json, "trailing_enabled", 1.0));' in src
    assert 'GlobalVariableSet(gv_prefix + "trailstart", JsonNumber(json, "trail_start_r", 0.80));' in src
    assert 'GlobalVariableSet(gv_prefix + "traildistance", trail_distance);' in src
    # ... and reconstructed from the broker/global state (EnsureManagementState) if the
    # EA/terminal restarts and the in-memory globals are gone but GlobalVariables persist.
    assert "void EnsureManagementState(ulong ticket)" in src
    assert 'if(!GlobalVariableCheck(gv_prefix + "maxhold")) GlobalVariableSet(gv_prefix + "maxhold", 1200.0);' in src
    assert 'if(!GlobalVariableCheck(gv_prefix + "trailenabled")) GlobalVariableSet(gv_prefix + "trailenabled", 1.0);' in src


def test_trailing_stop_only_advances_toward_profit():
    src = _source()
    # `improves` gates PositionModify: for BUY the new SL must be strictly higher
    # than the current one; for SELL strictly lower (or no SL set yet) -- never
    # a step backwards toward the entry/loss side.
    assert (
        "bool improves = is_buy ? (next_sl > current_sl + point) : "
        "(current_sl <= 0.0 || next_sl < current_sl - point);"
    ) in src
    assert "if(!improves || next_sl <= 0.0)\n      return;" in src
    assert "trade.PositionModify(ticket, next_sl, tp)" in src


def test_hard_close_at_max_hold_survives_restart():
    src = _source()
    # ManageOpenPosition calls EnsureManagementState first, so "opened"/"maxhold"
    # are rebuilt from the broker position + persisted GlobalVariables even if the
    # EA/terminal was restarted, then the elapsed-time check fires unconditionally.
    assert "void ManageOpenPosition()" in src
    ea_body_start = src.index("void ManageOpenPosition()")
    ea_body = src[ea_body_start:ea_body_start + 1200]
    assert "EnsureManagementState(ticket);" in ea_body
    assert "(TimeCurrent() - opened) >= max_hold" in ea_body
    assert "trade.PositionClose(ticket)" in ea_body
