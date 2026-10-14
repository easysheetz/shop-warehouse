"""Logowanie pracowników kodem PIN + token sesji podpisany kluczem SECRET_KEY."""
import hashlib
import hmac
import secrets

from fastapi import Depends, Header, HTTPException
from itsdangerous import BadSignature, SignatureExpired, URLSafeTimedSerializer
from sqlalchemy.orm import Session

from .config import settings
from .db import get_db
from .models import User

_serializer = URLSafeTimedSerializer(settings.SECRET_KEY, salt="skaner-session")


def hash_pin(pin: str) -> str:
    salt = secrets.token_hex(8)
    digest = hashlib.pbkdf2_hmac("sha256", pin.encode(), salt.encode(), 200_000).hex()
    return f"{salt}${digest}"


def verify_pin(pin: str, stored: str) -> bool:
    try:
        salt, digest = stored.split("$", 1)
    except ValueError:
        return False
    check = hashlib.pbkdf2_hmac("sha256", pin.encode(), salt.encode(), 200_000).hex()
    return hmac.compare_digest(check, digest)


def make_token(user: User) -> str:
    return _serializer.dumps({"uid": user.id})


def current_user(authorization: str = Header(default=""), db: Session = Depends(get_db)) -> User:
    token = authorization.removeprefix("Bearer ").strip()
    if not token:
        raise HTTPException(401, "Zaloguj się")
    try:
        data = _serializer.loads(token, max_age=settings.SESSION_HOURS * 3600)
    except SignatureExpired:
        raise HTTPException(401, "Sesja wygasła – zaloguj się ponownie") from None
    except BadSignature:
        raise HTTPException(401, "Nieprawidłowa sesja") from None
    user = db.get(User, data.get("uid"))
    if not user or not user.active:
        raise HTTPException(401, "Konto nieaktywne")
    return user


def admin_user(user: User = Depends(current_user)) -> User:
    if not user.is_admin:
        raise HTTPException(403, "Tylko administrator")
    return user
