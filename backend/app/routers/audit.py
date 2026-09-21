from fastapi import APIRouter, Depends, Query
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.audit import verify_chain
from app.auth import current_user
from app.database import get_db
from app.models import AuditLog, User
from app.schemas import AuditVerifyOut

router = APIRouter(prefix="/audit", tags=["audit"])


@router.get("/verify", response_model=AuditVerifyOut)
def verify(db: Session = Depends(get_db), user: User = Depends(current_user)) -> AuditVerifyOut:
    """Walk the full audit hash-chain and confirm no entry was altered.

    Any authenticated role may verify: the response carries only a verdict and a
    count (no project data), and integrity of the trail matters to every role.
    Simplified tamper-evidence demo -- not a real distributed ledger.
    """
    return AuditVerifyOut(**verify_chain(db))


@router.get("/recent")
def recent(limit: int = Query(6, ge=1, le=20), db: Session = Depends(get_db),
           user: User = Depends(current_user)) -> dict:
    """The newest audit-chain entries, for the header widget that draws the chain.

    Returns ONLY chain metadata (id, event type, this hash, the previous entry's hash, timestamp):
    never the payload or a project id, so no role can learn anything outside its scope from it.
    Newest first; entry[i].previous_hash == entry[i+1].hash is the link the widget draws.
    """
    rows = db.execute(
        select(AuditLog.id, AuditLog.event_type, AuditLog.payload_hash, AuditLog.previous_hash,
               AuditLog.timestamp).order_by(AuditLog.id.desc()).limit(limit)
    ).all()
    return {
        "height": rows[0].id if rows else 0,      # id of the newest entry (ids are sequential)
        "entries": [
            {"id": r.id, "event_type": r.event_type, "hash": r.payload_hash,
             "previous_hash": r.previous_hash, "timestamp": r.timestamp}
            for r in rows
        ],
    }
