from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.auth import current_user, make_token, scope_label, verify_password
from app.database import get_db
from app.models import User

router = APIRouter(prefix="/auth", tags=["auth"])


class LoginIn(BaseModel):
    username: str
    password: str


def _profile(user: User) -> dict:
    return {"username": user.username, "role": user.role,
            "scope_value": user.scope_value, "scope_label": scope_label(user)}


@router.post("/login")
def login(body: LoginIn, db: Session = Depends(get_db)):
    user = db.scalar(select(User).where(User.username == body.username))
    if not user or not verify_password(body.password, user.password_hash):
        raise HTTPException(401, "invalid username or password")
    return {"access_token": make_token(user), "token_type": "bearer", **_profile(user)}


@router.get("/me")
def me(user: User = Depends(current_user)):
    return _profile(user)
