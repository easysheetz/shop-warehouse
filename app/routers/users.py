"""Logowanie i konta pracowników."""
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from ..auth import admin_user, current_user, hash_pin, make_token, verify_pin
from ..db import get_db
from ..models import User

router = APIRouter(prefix="/api", tags=["użytkownicy"])

PIN = Field(min_length=4, max_length=12, pattern=r"^\d+$")


class LoginIn(BaseModel):
    name: str = Field(max_length=80)
    pin: str = Field(max_length=12)


class UserIn(BaseModel):
    name: str = Field(min_length=1, max_length=80)
    pin: str = PIN
    is_admin: bool = False


class UserPatch(BaseModel):
    pin: str | None = Field(default=None, min_length=4, max_length=12, pattern=r"^\d+$")
    is_admin: bool | None = None
    active: bool | None = None


@router.post("/login")
def login(body: LoginIn, db: Session = Depends(get_db)):
    user = db.scalar(select(User).where(func.lower(User.name) == body.name.strip().lower()))
    if not user or not user.active or not verify_pin(body.pin, user.pin_hash):
        raise HTTPException(401, "Zły login lub PIN")
    return {"token": make_token(user), "user": {"id": user.id, "name": user.name, "is_admin": user.is_admin}}


@router.get("/me")
def me(user: User = Depends(current_user)):
    return {"id": user.id, "name": user.name, "is_admin": user.is_admin}


@router.get("/users/names")
def user_names(db: Session = Depends(get_db)):
    """Imiona na ekranie logowania."""
    return [u.name for u in db.scalars(select(User).where(User.active).order_by(User.name))]


@router.get("/users")
def list_users(_: User = Depends(admin_user), db: Session = Depends(get_db)):
    return [{"id": u.id, "name": u.name, "is_admin": u.is_admin, "active": u.active}
            for u in db.scalars(select(User).order_by(User.name))]


@router.post("/users")
def create_user(body: UserIn, _: User = Depends(admin_user), db: Session = Depends(get_db)):
    db.add(User(name=body.name.strip(), pin_hash=hash_pin(body.pin), is_admin=body.is_admin))
    try:
        db.commit()
    except IntegrityError:
        raise HTTPException(400, "Taki użytkownik już istnieje") from None
    return {"ok": True}


@router.patch("/users/{uid}")
def patch_user(uid: int, body: UserPatch, admin: User = Depends(admin_user), db: Session = Depends(get_db)):
    u = db.get(User, uid)
    if not u:
        raise HTTPException(404, "Brak użytkownika")
    if body.pin is not None:
        u.pin_hash = hash_pin(body.pin)
    if u.id != admin.id:  # administrator nie odbierze uprawnień sam sobie
        if body.is_admin is not None:
            u.is_admin = body.is_admin
        if body.active is not None:
            u.active = body.active
    db.commit()
    return {"ok": True}
