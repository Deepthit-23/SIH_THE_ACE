"""Ministry-only user management.

Every endpoint depends on `require_ministry` (server-side role check -> 403 for every other role,
401 with no/invalid token); the frontend hiding the nav item is only a convenience.

Every provisioning change is appended to the SAME audit hash-chain as scores and case reviews
(event_type='admin_action') in the same transaction as the change itself, so a user cannot be
created / deactivated / reactivated / reset without leaving a tamper-evident record. Passwords and
hashes are never written to the chain.
"""

from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy import func, select, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app import audit
from app.auth import ROLES, SCOPE_COLUMN, hash_password, require_ministry, scope_label
from app.database import get_db
from app.models import Project, User

router = APIRouter(prefix="/admin", tags=["admin"])

MIN_PASSWORD_LENGTH = 8
USERNAME_PATTERN = r"^[A-Za-z0-9][A-Za-z0-9._@-]{2,63}$"

SCOPE_LABEL = {"state_nodal": "state", "district_authority": "district", "mp_self": "MP"}


class UserOut(BaseModel):
    id: int
    username: str
    role: str
    scope_value: str | None
    scope_label: str
    is_active: bool
    must_change_password: bool
    created_at: datetime | None


class UserCreate(BaseModel):
    username: str = Field(pattern=USERNAME_PATTERN)
    role: str
    scope_value: str | None = None
    temp_password: str = Field(min_length=MIN_PASSWORD_LENGTH, max_length=128)


class UserPatch(BaseModel):
    is_active: bool | None = None
    reset_password: str | None = Field(default=None, min_length=MIN_PASSWORD_LENGTH, max_length=128)


def _out(u: User) -> UserOut:
    return UserOut(
        id=u.id, username=u.username, role=u.role, scope_value=u.scope_value,
        scope_label=scope_label(u), is_active=bool(u.is_active),
        must_change_password=bool(u.must_change_password), created_at=u.created_at,
    )


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _actor(admin: User) -> str:
    return f"{admin.role}:{admin.username}"


def _canonical_scope(db: Session, role: str, scope_value: str | None) -> str | None:
    """Validate a scope against the real data and return it in its stored casing.

    A scope that matches nothing would create an account that silently sees an empty dashboard,
    so it is rejected instead of accepted.
    """
    value = (scope_value or "").strip()
    if role == "ministry":
        if value:
            raise HTTPException(422, "the ministry role is national and takes no scope")
        return None
    if not value:
        raise HTTPException(422, f"a {SCOPE_LABEL[role]} scope is required for this role")
    col = getattr(Project, SCOPE_COLUMN[role])
    found = db.scalar(select(col).where(func.lower(col) == value.lower()).limit(1))
    if found is None:
        raise HTTPException(422, f"no {SCOPE_LABEL[role]} named '{value}' exists in the data")
    return found


@router.get("/users", response_model=list[UserOut])
def list_users(db: Session = Depends(get_db), admin: User = Depends(require_ministry)):
    return [_out(u) for u in db.scalars(select(User).order_by(User.id)).all()]


@router.post("/users", response_model=UserOut, status_code=201)
def create_user(body: UserCreate, db: Session = Depends(get_db), admin: User = Depends(require_ministry)):
    if body.role not in ROLES:
        raise HTTPException(422, f"role must be one of {sorted(ROLES)}")
    if db.scalar(select(User.id).where(func.lower(User.username) == body.username.lower())):
        raise HTTPException(409, "that username is already taken")
    scope = _canonical_scope(db, body.role, body.scope_value)
    user = User(
        username=body.username, role=body.role, scope_value=scope,
        password_hash=hash_password(body.temp_password),   # bcrypt; plaintext is never stored
        is_active=True, must_change_password=True,
    )
    db.add(user)
    try:
        db.flush()
        audit.append_admin_event(
            db, "user_created", _actor(admin), user.username, user.role, user.scope_value, _now(),
            detail="must change password at first login",
        )
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(409, "that username is already taken")
    db.refresh(user)
    return _out(user)


@router.patch("/users/{user_id}", response_model=UserOut)
def patch_user(user_id: int, body: UserPatch, db: Session = Depends(get_db),
               admin: User = Depends(require_ministry)):
    if body.is_active is None and body.reset_password is None:
        raise HTTPException(422, "send is_active and/or reset_password")
    user = db.get(User, user_id)
    if user is None:
        raise HTTPException(404, "user not found")

    now, actor = _now(), _actor(admin)
    if body.is_active is not None and body.is_active != user.is_active:
        if not body.is_active:
            if user.id == admin.id:
                raise HTTPException(400, "you cannot deactivate your own account")
            if user.role == "ministry":
                others = db.scalar(
                    select(func.count()).select_from(User)
                    .where(User.role == "ministry", User.is_active.is_(True), User.id != user.id)
                )
                if not others:
                    raise HTTPException(400, "cannot deactivate the last active ministry account")
        user.is_active = body.is_active
        audit.append_admin_event(
            db, "user_reactivated" if body.is_active else "user_deactivated", actor,
            user.username, user.role, user.scope_value, now,
        )
    if body.reset_password is not None:
        user.password_hash = hash_password(body.reset_password)
        user.must_change_password = True
        audit.append_admin_event(
            db, "password_reset", actor, user.username, user.role, user.scope_value, now,
            detail="must change password at next login",
        )
    db.commit()
    db.refresh(user)
    return _out(user)


@router.get("/scope-options")
def scope_options(
    kind: str = Query(pattern="^(state|district|mp)$"),
    q: str | None = Query(None, max_length=100),
    db: Session = Depends(get_db),
    admin: User = Depends(require_ministry),
) -> list[dict]:
    """Values a new user's scope can take, straight from the data: [{value, label}].
    `mp` is a search (q, min 2 chars); state / district return the full list."""
    if kind == "state":
        rows = db.execute(text("SELECT DISTINCT state FROM projects WHERE state IS NOT NULL ORDER BY 1")).scalars()
        return [{"value": s, "label": s} for s in rows]
    if kind == "district":
        rows = db.execute(text(
            "SELECT district, string_agg(DISTINCT state, ', ' ORDER BY state) FROM projects "
            "WHERE district IS NOT NULL GROUP BY district ORDER BY district"
        )).all()
        return [{"value": d, "label": f"{d} ({s})" if s else d} for d, s in rows]
    term = (q or "").strip()
    if len(term) < 2:
        return []
    like = "%" + term.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_") + "%"
    rows = db.execute(
        text("SELECT mp_name, max(state) FROM projects WHERE mp_name ILIKE :p ESCAPE '\\' "
             "GROUP BY mp_name ORDER BY mp_name LIMIT 25"),
        {"p": like},
    ).all()
    return [{"value": n, "label": f"{n} — {s}" if s else n} for n, s in rows]
