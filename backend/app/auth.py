"""Server-enforced JWT/RBAC layer.

Every scoped query goes through ONE mechanism so scoping can't be forgotten:
  - ORM queries  -> `project_scope_filter(user)` / `scope_project_query(stmt, user)`
  - raw SQL      -> `scope_sql(user, alias)` returns (" AND ...", params)
  - single rows  -> `assert_project_scope(project, user)` (403 outside scope)

Scope matching is exact, case-insensitive equality (never ILIKE: a `%`/`_` in a
scope value must not behave as a wildcard).

Roles (spec name -> stored value): ministry, state -> state_nodal,
district -> district_authority, mp -> mp_self.
"""

from datetime import datetime, timedelta, timezone

import bcrypt
import jwt
from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy import and_, false, func, select, text
from sqlalchemy.orm import Session

from app.config import settings
from app.database import engine, get_db
from app.models import Project, User

ROLES = {"ministry", "state_nodal", "district_authority", "mp_self"}
# role -> the projects / vendor_transactions column its scope_value is matched on. State and district are
# LOCATION scopes (work_state), so the hierarchy nests: Ministry > State (work_state) > District
# (work_state + district) > MP (mp_name, unchanged). A NULL work_state (unresolved location) matches nothing.
SCOPE_COLUMN = {"state_nodal": "work_state", "district_authority": "district", "mp_self": "mp_name"}

# Demo accounts (documented in the README). The MP scope is the exact `mp_name`
# string as it appears in the data, including honorific and term suffix.
DEMO_USERS = [
    ("ministry_demo", "DemoMinistry!2026", "ministry", None),
    ("state_demo", "DemoState!2026", "state_nodal", "Telangana"),
    ("district_demo", "DemoDistrict!2026", "district_authority", "HYDERABAD"),
    ("mp_demo", "DemoMP!2026", "mp_self", "Dr. Abhishek Manu Singhvi (2026-32)"),
]

# A District Authority is scoped by the (state, district) PAIR -- district names repeat across states
# (Bilaspur HP/CG, Hamirpur HP/UP ...). The state of a demo district account:
DEMO_SCOPE_STATE = {"district_demo": "Telangana"}

bearer = HTTPBearer(auto_error=False)


def hash_password(password: str) -> str:
    return bcrypt.hashpw(password.encode(), bcrypt.gensalt()).decode()


def verify_password(password: str, encoded: str) -> bool:
    return bcrypt.checkpw(password.encode(), encoded.encode())


def make_token(user: User) -> str:
    now = datetime.now(timezone.utc)
    return jwt.encode(
        {"sub": user.username, "role": user.role, "scope": user.scope_value, "scope_state": user.scope_state,
         "iat": now, "exp": now + timedelta(minutes=settings.jwt_expire_minutes)},
        settings.jwt_secret, algorithm=settings.jwt_algorithm,
    )


def ensure_user_columns() -> None:
    """Additive, idempotent upgrade of an existing `users` table (no Alembic in this project):
    databases created before user management get the new columns with safe defaults."""
    ddl = {
        "is_active": "boolean NOT NULL DEFAULT true",
        "must_change_password": "boolean NOT NULL DEFAULT false",
        "created_at": "timestamptz DEFAULT now()",
        "scope_state": "varchar(255)",
    }
    # catalog check first: ADD COLUMN IF NOT EXISTS still takes an exclusive table lock when nothing changes
    with engine.connect() as c:
        have = {r[0] for r in c.execute(text(
            "SELECT column_name FROM information_schema.columns WHERE table_name = 'users'"))}
    missing = {col: typ for col, typ in ddl.items() if col not in have}
    if missing:
        with engine.begin() as c:
            for col, typ in missing.items():
                c.execute(text(f"ALTER TABLE users ADD COLUMN IF NOT EXISTS {col} {typ}"))


def seed_demo_users(db: Session) -> None:
    """Idempotent: create missing demo users, and re-sync role/scope of existing ones.

    Deliberately leaves is_active / password / must_change_password of existing accounts alone,
    so a Ministry decision (deactivation, changed password) is not silently undone at restart.
    """
    db.rollback()  # end any open transaction before the DDL below
    ensure_user_columns()
    from app.pipeline.location import ensure_derived   # work_state on projects / vendor_transactions
    ensure_derived(engine)
    for username, password, role, scope in DEMO_USERS:
        scope_state = DEMO_SCOPE_STATE.get(username)
        user = db.scalar(select(User).where(User.username == username))
        if user is None:
            db.add(User(username=username, password_hash=hash_password(password),
                        role=role, scope_value=scope, scope_state=scope_state))
        else:
            user.role, user.scope_value, user.scope_state = role, scope, scope_state
    db.commit()


def _load_user(credentials: HTTPAuthorizationCredentials | None, db: Session) -> User:
    """Authenticate the bearer token and return an ACTIVE account (re-read from the DB on every
    request, so deactivating a user kills their existing tokens immediately)."""
    if not credentials:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "authentication required")
    try:
        payload = jwt.decode(credentials.credentials, settings.jwt_secret,
                             algorithms=[settings.jwt_algorithm])
        username = payload.get("sub")
    except jwt.PyJWTError:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "invalid or expired token")
    user = db.scalar(select(User).where(User.username == username))
    if not user or user.role not in ROLES:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "invalid account")
    if not user.is_active:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "account deactivated")
    return user


def current_user_any(credentials: HTTPAuthorizationCredentials | None = Depends(bearer),
                     db: Session = Depends(get_db)) -> User:
    """Authenticated + active, INCLUDING accounts that still owe a password change. Only
    /auth/me and /auth/change-password use this; everything else uses `current_user`."""
    return _load_user(credentials, db)


def current_user(user: User = Depends(current_user_any)) -> User:
    """Authenticated + active + has completed the forced first-login password change."""
    if user.must_change_password:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "password_change_required")
    return user


# --------------------------------------------------------------------------- #
# scoping
# --------------------------------------------------------------------------- #
def scope_label(user: User) -> str:
    if user.role == "ministry":
        return "National"
    if user.role == "district_authority":
        return f"{user.scope_value}, {user.scope_state}" if user.scope_value and user.scope_state else (user.scope_value or "—")
    return user.scope_value or "—"


def project_scope_filter(user: User):
    """SQLAlchemy criterion restricting `Project` rows to the user's scope (None = all).

    District Authority: BOTH district and the state the work is located in must match (the pair);
    an account with no scope_state matches nothing rather than silently widening to every state.
    """
    if user.role == "ministry":
        return None
    if user.role == "district_authority":
        if not user.scope_state:
            return false()
        return and_(
            func.lower(Project.district) == (user.scope_value or "").lower(),
            func.lower(Project.work_state) == user.scope_state.lower(),
        )
    col = getattr(Project, SCOPE_COLUMN[user.role])
    return func.lower(col) == (user.scope_value or "").lower()


def scope_project_query(stmt, user: User):
    """Apply mandatory row scope to a statement that selects from Project."""
    crit = project_scope_filter(user)
    return stmt if crit is None else stmt.where(crit)


def scope_sql(user: User, alias: str, param: str = "_scope") -> tuple[str, dict]:
    """Raw-SQL twin of `project_scope_filter`. Returns (" AND <cond>" | "", params).

    `alias` must expose the work_state / district / mp_name columns (projects and
    vendor_transactions both do).
    """
    if user.role == "ministry":
        return "", {}
    if user.role == "district_authority":
        if not user.scope_state:
            return " AND FALSE", {}
        return (
            f" AND lower({alias}.district) = lower(:{param})"
            f" AND lower({alias}.work_state) = lower(:{param}_state)",
            {param: user.scope_value or "", f"{param}_state": user.scope_state},
        )
    col = SCOPE_COLUMN[user.role]
    return f" AND lower({alias}.{col}) = lower(:{param})", {param: user.scope_value or ""}


def assert_project_scope(project: Project | None, user: User) -> Project:
    if project is None:
        raise HTTPException(404, "Project not found")
    if user.role == "ministry":
        return project
    if user.role == "district_authority":
        ok = (
            bool(user.scope_state)
            and (project.district or "").casefold() == (user.scope_value or "").casefold()
            and (project.work_state or "").casefold() == user.scope_state.casefold()
        )
    else:
        value = getattr(project, SCOPE_COLUMN[user.role])
        ok = (value or "").casefold() == (user.scope_value or "").casefold()
    if not ok:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "outside your authorised scope")
    return project


def require_ministry(user: User = Depends(current_user)) -> User:
    if user.role != "ministry":
        raise HTTPException(status.HTTP_403_FORBIDDEN, "ministry access required")
    return user
