from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.auth import (
    current_user_any, hash_password, make_token, scope_label, verify_password,
)
from app.database import get_db
from app.models import User

router = APIRouter(prefix="/auth", tags=["auth"])

MIN_PASSWORD_LENGTH = 8


class LoginIn(BaseModel):
    username: str
    password: str


class ChangePasswordIn(BaseModel):
    current_password: str
    new_password: str = Field(min_length=MIN_PASSWORD_LENGTH, max_length=128)


def _profile(user: User) -> dict:
    return {"username": user.username, "role": user.role,
            "scope_value": user.scope_value, "scope_state": user.scope_state, "scope_label": scope_label(user),
            "must_change_password": bool(user.must_change_password)}


@router.post("/login")
def login(body: LoginIn, db: Session = Depends(get_db)):
    user = db.scalar(select(User).where(User.username == body.username))
    if not user or not verify_password(body.password, user.password_hash):
        raise HTTPException(401, "invalid username or password")
    # Only revealed after the password checks out, so this can't be used to probe for usernames.
    if not user.is_active:
        raise HTTPException(403, "this account has been deactivated; contact the Ministry administrator")
    return {"access_token": make_token(user), "token_type": "bearer", **_profile(user)}


@router.get("/me")
def me(user: User = Depends(current_user_any)):
    return _profile(user)


@router.post("/change-password")
def change_password(body: ChangePasswordIn, user: User = Depends(current_user_any),
                    db: Session = Depends(get_db)):
    """Self-service password change; also the way out of `must_change_password`."""
    if not verify_password(body.current_password, user.password_hash):
        raise HTTPException(400, "current password is incorrect")
    if body.new_password == body.current_password:
        raise HTTPException(400, "the new password must differ from the current one")
    user.password_hash = hash_password(body.new_password)
    user.must_change_password = False
    db.commit()
    return _profile(user)
