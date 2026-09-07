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
import threading
import time
from datetime import datetime, timezone

from sqlalchemy import func, insert, select, text

from app.models import AuditLog

GENESIS_HASH = "0" * 64
EVENT_RISK_SCORE = "risk_score"
EVENT_CASE_REVIEW = "case_review"

# verify_chain re-hashes every row, so cache the verdict. The cache key is a
# cheap in-DB fingerprint of the whole table (count + max id + md5 of every
# hash/link/payload) -- it changes the instant ANY row is altered, so the cache
# can never mask tampering. TTL is just a periodic re-check backstop.
_VERIFY_TTL_SECONDS = 300
_verify_cache: dict = {"fingerprint": None, "result": None, "at": 0.0}
_verify_lock = threading.Lock()


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


def _table_fingerprint(conn) -> str:
    """One cheap query that changes if any audit_log row is added or altered."""
    return conn.execute(
        text(
            "SELECT count(*)::text || ':' || COALESCE(max(id), 0)::text || ':' || "
            "COALESCE(md5(string_agg("
            "  payload_hash || previous_hash || COALESCE(payload::text, ''), '|' ORDER BY id"
            ")), 'empty') FROM audit_log"
        )
    ).scalar()


def _walk_chain(conn) -> dict:
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


def append_case_event(
    conn, project_id: int, status: str, note: str | None, reviewer: str | None, ts: datetime
) -> str:
    """Append one chained `case_review` entry. Same chain as scoring events."""
    prev = last_hash(conn)
    payload = {
        "event": EVENT_CASE_REVIEW,
        "project_id": int(project_id),
        "status": status,
        "note_sha256": _sha256(note or ""),
        "reviewer": (reviewer or "").strip(),
        "timestamp": ts.astimezone(timezone.utc).isoformat(),
    }
    h = chain_hash(payload, prev)
    conn.execute(
        insert(AuditLog),
        [{
            "event_type": EVENT_CASE_REVIEW,
            "project_id": int(project_id),
            "payload": payload,
            "payload_hash": h,
            "previous_hash": prev,
            "timestamp": ts,
        }],
    )
    return h


def verify_chain(conn, use_cache: bool = True) -> dict:
    """Walk the full chain, recompute every hash, confirm nothing was altered.

    Returns {"valid", "entries_checked", "broken_at", "cached", "checked_at"}.
    Cached on a table fingerprint (+ TTL); pass use_cache=False to force a walk.
    """
    if not use_cache:
        result = _walk_chain(conn)
        return {**result, "cached": False, "checked_at": _now_iso()}

    fp = _table_fingerprint(conn)
    now = time.time()
    with _verify_lock:
        c = _verify_cache
        if c["fingerprint"] == fp and (now - c["at"]) < _VERIFY_TTL_SECONDS:
            return {**c["result"], "cached": True, "checked_at": c["checked_at"]}

    result = _walk_chain(conn)
    checked_at = _now_iso()
    with _verify_lock:
        _verify_cache.update(fingerprint=fp, result=result, at=now, checked_at=checked_at)
    return {**result, "cached": False, "checked_at": checked_at}


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")
