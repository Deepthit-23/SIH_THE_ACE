"""Simplified tamper-evident audit chain.

This is a DEMONSTRATION of hash-chaining -- NOT a real distributed ledger or
blockchain (no consensus, no replication, single writer). Each entry's hash
binds its payload to the previous entry's hash:

    this_hash = sha256(canonical_json(payload) + previous_hash)

so altering any past entry -- or reordering them -- breaks every hash after it,
which `verify_chain` detects.

All payload values are ints or strings (no floats) so the JSONB round-trip is
byte-stable and the recomputed hash matches exactly.
"""

from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone

from sqlalchemy import insert, select

from app.models import AuditLog

GENESIS_HASH = "0" * 64
EVENT_RISK_SCORE = "risk_score"


def _sha256(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def explanation_digest(explanation) -> str:
    """Stable hash of the explanation list -- bound into the payload."""
    return _sha256(
        json.dumps(explanation or [], sort_keys=True, separators=(",", ":"), default=str)
    )


def build_payload(project_id: int, combined_risk_score: float, explanation, ts: datetime) -> dict:
    return {
        "project_id": int(project_id),
        "combined_risk_score": f"{float(combined_risk_score):.4f}",
        "explanation_sha256": explanation_digest(explanation),
        "timestamp": ts.astimezone(timezone.utc).isoformat(),
    }


def _payload_json(payload: dict) -> str:
    return json.dumps(payload, sort_keys=True, separators=(",", ":"))


def chain_hash(payload: dict, previous_hash: str) -> str:
    return _sha256(_payload_json(payload) + previous_hash)


def last_hash(conn) -> str:
    row = conn.execute(
        select(AuditLog.payload_hash).order_by(AuditLog.id.desc()).limit(1)
    ).first()
    return row[0] if row else GENESIS_HASH


def append_entries(conn, records: list[tuple], event_type: str = EVENT_RISK_SCORE) -> int:
    """Append one chained entry per record, continuing from the current tail.

    `records`: iterable of (project_id, combined_risk_score, explanation, timestamp).
    Must be called inside the same transaction as the risk_flags write.
    """
    prev = last_hash(conn)
    rows: list[dict] = []
    for project_id, score, explanation, ts in records:
        payload = build_payload(project_id, score, explanation, ts)
        h = chain_hash(payload, prev)
        rows.append({
            "event_type": event_type,
            "project_id": int(project_id),
            "payload": payload,
            "payload_hash": h,
            "previous_hash": prev,
            "timestamp": ts,
        })
        prev = h
    for i in range(0, len(rows), 5000):
        conn.execute(insert(AuditLog), rows[i : i + 5000])
    return len(rows)


def verify_chain(conn) -> dict:
    """Walk the full chain, recompute every hash, confirm nothing was altered.

    Returns {"valid": bool, "entries_checked": int, "broken_at": id | None}.
    `broken_at` is the id of the first entry whose stored hash or back-link does
    not match the recomputation.
    """
    rows = conn.execute(
        select(
            AuditLog.id, AuditLog.payload, AuditLog.payload_hash, AuditLog.previous_hash
        ).order_by(AuditLog.id)
    ).all()

    prev = GENESIS_HASH
    checked = 0
    for r in rows:
        if r.previous_hash != prev or chain_hash(r.payload, prev) != r.payload_hash:
            return {"valid": False, "entries_checked": checked, "broken_at": r.id}
        prev = r.payload_hash
        checked += 1
    return {"valid": True, "entries_checked": checked, "broken_at": None}
