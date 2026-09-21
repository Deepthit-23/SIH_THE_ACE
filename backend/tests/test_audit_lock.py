"""Concurrent audit appends must not fork the hash-chain: appends are serialised by an advisory lock.

These tests write NOTHING (every transaction is rolled back), so they are safe against the live chain.
"""

from datetime import datetime, timezone

from sqlalchemy import text

from app import audit
from app.database import engine


def _try_lock(other_conn) -> bool:
    return bool(other_conn.execute(text("SELECT pg_try_advisory_xact_lock(:k)"), {"k": audit.CHAIN_LOCK_KEY}).scalar())


def test_every_appender_takes_the_chain_lock_and_holds_it_until_the_transaction_ends():
    now = datetime.now(timezone.utc)
    appenders = {
        "admin": lambda c: audit.append_admin_event(c, "user_created", "test:actor", "lock_probe", "state_nodal", None, now),
        "case": lambda c: audit.append_case_event(c, 1, "under_review", None, "test:actor", now),
        "score": lambda c: audit.append_entries(c, [(1, 10.0, [], now)]),
    }
    for name, append in appenders.items():
        with engine.connect() as writer, engine.connect() as other:
            tx = writer.begin()
            append(writer)                                                    # not committed
            probe = other.begin()
            assert _try_lock(other) is False, f"{name}: a second writer could enter while the first was mid-append"
            probe.rollback()
            tx.rollback()                                                     # released with the transaction
            probe = other.begin()
            assert _try_lock(other) is True, f"{name}: lock not released at rollback"
            probe.rollback()
