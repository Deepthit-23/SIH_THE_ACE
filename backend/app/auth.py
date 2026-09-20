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
from sqlalchemy import func, select, text
from sqlalchemy.orm import Session

from app.config import settings
from app.database import engine, get_db
from app.models import Project, User

ROLES = {"ministry", "state_nodal", "district_authority", "mp_self"}
# role -> the projects / vendor_transactions column its scope_value is matched on
SCOPE_COLUMN = {"state_nodal": "state", "district_authority": "district", "mp_self": "mp_name"}

# Demo accounts (documented in the README). The MP scope is the exact `mp_name`
# string as it appears in the data, including honorific and term suffix.
DEMO_USERS = [
    ("ministry_demo", "DemoMinistry!2026", "ministry", None),
    ("state_demo", "DemoState!2026", "state_nodal", "Telangana"),
    ("district_demo", "DemoDistrict!2026", "district_authority", "HYDERABAD"),
    ("mp_demo", "DemoMP!2026", "mp_self", "Dr. Abhishek Manu Singhvi (2026-32)"),
]

bearer = HTTPBearer(auto_error=False)


def hash_password(password: str) -> str:
    return bcrypt.hashpw(password.encode(), bcrypt.gensalt()).decode()


def verify_password(password: str, encoded: str) -> bool:
    return bcrypt.checkpw(password.encode(), encoded.encode())


def make_token(user: User) -> str:
    now = datetime.now(timezone.utc)
    return jwt.encode(
        {"sub": user.username, "role": user.role, "scope": user.scope_value,
         "iat": now, "exp": now + timedelta(minutes=settings.jwt_expire_minutes)},
        settings.jwt_secret, algorithm=settings.jwt_algorithm,
    )


def ensure_user_columns() -> None:
    """Additive, idempotent upgrade of an existing `users` table (no Alembic in this project):
    databases created before user management get the new columns with safe defaults."""
    with engine.begin() as c:
        c.execute(text("ALTER TABLE users ADD COLUMN IF NOT EXISTS is_active boolean NOT NULL DEFAULT true"))
        c.execute(text("ALTER TABLE users ADD COLUMN IF NOT EXISTS must_change_password boolean NOT NULL DEFAULT false"))
        c.execute(text("ALTER TABLE users ADD COLUMN IF NOT EXISTS created_at timestamptz DEFAULT now()"))


def seed_demo_users(db: Session) -> None:
    """Idempotent: create missing demo users, and re-sync role/scope of existing ones.

    Deliberately leaves is_active / password / must_change_password of existing accounts alone,
    so a Ministry decision (deactivation, changed password) is not silently undone at restart.
    """
    db.rollback()  # end any open transaction before the DDL below
    ensure_user_columns()
    for username, password, role, scope in DEMO_USERS:
        user = db.scalar(select(User).where(User.username == username))
        if user is None:
            db.add(User(username=username, password_hash=hash_password(password),
                        role=role, scope_value=scope))
        else:
            user.role, user.scope_value = role, scope
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
    return "National" if user.role == "ministry" else (user.scope_value or "—")


def project_scope_filter(user: User):
    """SQLAlchemy criterion restricting `Project` rows to the user's scope (None = all)."""
    if user.role == "ministry":
        return None
    col = getattr(Project, SCOPE_COLUMN[user.role])
    return func.lower(col) == (user.scope_value or "").lower()


def scope_project_query(stmt, user: User):
    """Apply mandatory row scope to a statement that selects from Project."""
    crit = project_scope_filter(user)
    return stmt if crit is None else stmt.where(crit)


def scope_sql(user: User, alias: str, param: str = "_scope") -> tuple[str, dict]:
    """Raw-SQL twin of `project_scope_filter`. Returns (" AND <cond>" | "", params).

    `alias` must expose the state / district / mp_name columns (projects and
    vendor_transactions both do).
    """
    if user.role == "ministry":
        return "", {}
    col = SCOPE_COLUMN[user.role]
    return f" AND lower({alias}.{col}) = lower(:{param})", {param: user.scope_value or ""}


def assert_project_scope(project: Project | None, user: User) -> Project:
    if project is None:
        raise HTTPException(404, "Project not found")
    if user.role != "ministry":
        value = getattr(project, SCOPE_COLUMN[user.role])
        if (value or "").casefold() != (user.scope_value or "").casefold():
            raise HTTPException(status.HTTP_403_FORBIDDEN, "outside your authorised scope")
    return project


def require_ministry(user: User = Depends(current_user)) -> User:
    if user.role != "ministry":
        raise HTTPException(status.HTTP_403_FORBIDDEN, "ministry access required")
    return user
