from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.audit import verify_chain
from app.auth import current_user
from app.database import get_db
from app.models import User
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
