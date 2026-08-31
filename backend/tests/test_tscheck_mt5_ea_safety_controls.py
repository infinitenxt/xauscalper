"""EA file contains restart-safe and duplicate-safe controls.

A real Windows MT5 terminal / MetaEditor compiler is unavailable in this
Linux environment, so bitcoinTerminalBridge.mq5 is verified statically for the
required safeguards: command expiry checks, a persistent account-scoped
command journal, broker retcode validation, opened_at reporting, and
management-state reconstruction from the broker's own position time.
"""

import os

EA_PATH = os.path.join(
    os.path.dirname(__file__), "..", "..", "frontend", "public", "bitcoinTerminalBridge.mq5"
)


def _source() -> str:
    assert os.path.isfile(EA_PATH), f"EA file not found at {EA_PATH}"
    with open(EA_PATH, "r", encoding="utf-8") as f:
        return f.read()


def test_ea_has_command_expiry_check():
    src = _source()
    assert "expires_epoch" in src
    assert "TimeGMT() >= (datetime)expires_epoch" in src, "poll loop must reject a command once its expires_epoch has passed"


def test_ea_has_persistent_account_scoped_journal():
    src = _source()
    assert "journal_file" in src
    # journal filename is scoped by account login + magic number, not global/shared
    assert 'journal_file = "GPT_MT5_" + (string)AccountInfoInteger(ACCOUNT_LOGIN)' in src
    assert "CommandWasExecuted" in src and "RememberExecutedCommand" in src
    assert "FileOpen(journal_file" in src, "journal must be a real persisted file, surviving EA/terminal restarts"


def test_ea_validates_broker_retcode():
    src = _source()
    assert "ResultRetcode()" in src
    assert "TRADE_RETCODE_DONE" in src and "TRADE_RETCODE_PLACED" in src
    assert "TradeRequestAccepted" in src, "executed/accepted outcomes must be gated on the broker's own retcode"


def test_ea_reports_opened_at_from_broker_position():
    src = _source()
    assert "POSITION_TIME" in src
    assert '"opened_at\\":\\"" ' not in src  # sanity: not a hardcoded/faked field
    assert '"opened_at\\":"' in src.replace(" ", "") or "opened_at" in src
    assert 'PositionGetInteger(POSITION_TIME)' in src, "opened_at must come from the broker's POSITION_TIME, not a local clock"


def test_ea_reconstructs_management_state_from_broker_position_time():
    src = _source()
    assert "EnsureManagementState" in src
    assert "PositionGetInteger(POSITION_TIME)" in src
    # EnsureManagementState seeds the "opened" global var from POSITION_TIME when missing,
    # so a restarted/attached EA can rebuild its break-even/trailing state from the broker.
    assert 'GlobalVariableSet(gv_prefix + "opened", (double)PositionGetInteger(POSITION_TIME))' in src
