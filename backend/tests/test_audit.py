"""Tamper-evidence tests for the audit hash-chain.

The important one is `test_tampered_entry_is_detected`: it edits a stored entry
and confirms `verify_chain` pinpoints it. Proof the detection actually works --
not just that a clean chain returns valid: true.

Every test runs inside a transaction that is rolled back, so the real audit_log
is never modified.
"""

from datetime import datetime, timezone

import pytest
from sqlalchemy import delete, select, update

from app import audit
from app.database import engine
from app.models import AuditLog

_TS = datetime(2026, 9, 5, 12, 0, tzinfo=timezone.utc)


@pytest.fixture
def chain_conn():
    connection = engine.connect()
    trans = connection.begin()
    connection.execute(delete(AuditLog))  # scoped to this rolled-back tx only
    audit.append_entries(
        connection,
        [
            (1000 + i, 40.0 + i * 3, [{"source": "rule", "message": f"reason {i}"}], _TS)
            for i in range(6)
        ],
    )
    try:
        yield connection
    finally:
        trans.rollback()
        connection.close()


def test_clean_chain_verifies(chain_conn):
    r = audit.verify_chain(chain_conn, use_cache=False)
    assert r["valid"] is True
    assert r["entries_checked"] == 6
    assert r["broken_at"] is None


def test_cache_returns_same_verdict_and_is_marked(chain_conn):
    first = audit.verify_chain(chain_conn)
    assert first["cached"] is False
    second = audit.verify_chain(chain_conn)
    assert second["cached"] is True
    assert (second["valid"], second["broken_at"]) == (first["valid"], first["broken_at"])


def test_cache_invalidates_when_a_row_is_altered(chain_conn):
    audit.verify_chain(chain_conn)  # warm the cache -> valid
    ids = chain_conn.execute(select(AuditLog.id).order_by(AuditLog.id)).scalars().all()
    payload = chain_conn.execute(
        select(AuditLog.payload).where(AuditLog.id == ids[2])
    ).scalar_one()
    chain_conn.execute(
        update(AuditLog).where(AuditLog.id == ids[2])
        .values(payload={**payload, "combined_risk_score": "9.9999"})
    )
    # fingerprint changed -> cache must not mask the tamper
    r = audit.verify_chain(chain_conn)
    assert r["valid"] is False
    assert r["broken_at"] == ids[2]


def test_tampered_entry_is_detected(chain_conn):
    ids = chain_conn.execute(select(AuditLog.id).order_by(AuditLog.id)).scalars().all()
    target = ids[3]  # tamper the 4th entry

    # An attacker rewrites a stored score but cannot recompute every later hash.
    payload = chain_conn.execute(
        select(AuditLog.payload).where(AuditLog.id == target)
    ).scalar_one()
    chain_conn.execute(
        update(AuditLog)
        .where(AuditLog.id == target)
        .values(payload={**payload, "combined_risk_score": "0.0000"})
    )

    result = audit.verify_chain(chain_conn, use_cache=False)
    assert result["valid"] is False
    assert result["broken_at"] == target
    assert result["entries_checked"] == 3  # entries 1-3 still verify cleanly


def test_reordering_is_detected(chain_conn):
    ids = chain_conn.execute(select(AuditLog.id).order_by(AuditLog.id)).scalars().all()
    h2 = chain_conn.execute(
        select(AuditLog.payload_hash).where(AuditLog.id == ids[1])
    ).scalar_one()
    h3 = chain_conn.execute(
        select(AuditLog.payload_hash).where(AuditLog.id == ids[2])
    ).scalar_one()
    chain_conn.execute(update(AuditLog).where(AuditLog.id == ids[1]).values(payload_hash=h3))
    chain_conn.execute(update(AuditLog).where(AuditLog.id == ids[2]).values(payload_hash=h2))

    result = audit.verify_chain(chain_conn, use_cache=False)
    assert result["valid"] is False
    assert result["broken_at"] == ids[1]
