from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.audit import verify_chain
from app.database import get_db
from app.schemas import AuditVerifyOut

router = APIRouter(prefix="/audit", tags=["audit"])


@router.get("/verify", response_model=AuditVerifyOut)
def verify(db: Session = Depends(get_db)) -> AuditVerifyOut:
    """Walk the full audit hash-chain and confirm no entry was altered.

    Simplified tamper-evidence demo -- not a real distributed ledger.
    """
    return AuditVerifyOut(**verify_chain(db))
