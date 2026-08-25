"""Atlas-safe startup seeding.

Inspects backend/seed.py source for destructive bulk operations, then runs
the idempotent seed() against the live local Mongo instance to confirm
pre-existing legacy trade/wallet/session rows survive and only missing
defaults/indexes get created.
"""

import asyncio
import os
import uuid

import pytest

SEED_PATH = os.path.join(os.path.dirname(__file__), "..", "seed.py")


def test_seed_source_has_no_bulk_delete_or_drop():
    with open(SEED_PATH) as f:
        source = f.read()
    assert "delete_many" not in source, "seed.py must not bulk-delete on startup"
    assert "drop_collection" not in source and ".drop(" not in source, (
        "seed.py must not drop collections on startup"
    )


def test_seed_run_preserves_legacy_trade_wallet_session_records():
    import sys

    backend_dir = os.path.join(os.path.dirname(__file__), "..")
    sys.path.insert(0, backend_dir)
    from lib.db import db  # noqa: E402
    import seed  # noqa: E402

    async def _run():
        suffix = uuid.uuid4().hex[:8]
        user_id = f"tscheck-seed-user-{suffix}"
        trade_id = f"tscheck-seed-trade-{suffix}"
        session_token = f"tscheck-seed-session-{suffix}"

        await db.trades.insert_one({"id": trade_id, "user_id": user_id, "status": "open"})
        await db.wallets.insert_one({"user_id": user_id, "balance": 12345.0})
        await db.sessions.insert_one({"token": session_token, "user_id": user_id})

        try:
            await seed.run()

            trade = await db.trades.find_one({"id": trade_id})
            wallet = await db.wallets.find_one({"user_id": user_id})
            session = await db.sessions.find_one({"token": session_token})

            assert trade is not None, "legacy trade record was deleted by seed"
            assert wallet is not None, "legacy wallet record was deleted by seed"
            assert session is not None, "legacy session record was deleted by seed"

            admin = await db.users.find_one({"email": seed.ADMIN_EMAIL})
            assert admin is not None and admin.get("role") == "admin"
        finally:
            await db.trades.delete_one({"id": trade_id})
            await db.wallets.delete_one({"user_id": user_id})
            await db.sessions.delete_one({"token": session_token})

    asyncio.run(_run())
