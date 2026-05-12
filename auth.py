import os
import re
import secrets
from typing import Optional, Tuple
import bcrypt as _bcrypt
from itsdangerous import URLSafeTimedSerializer, BadSignature, SignatureExpired
from fastapi import Request, HTTPException
from sqlalchemy.orm import Session
from database import UserProcess

ENVIRONMENT = os.getenv("ENVIRONMENT", "dev").lower()
IS_PRODUCTION = ENVIRONMENT in ("prod", "production")

SECRET_KEY = os.getenv("SECRET_KEY", "").strip()
if not SECRET_KEY:
    if IS_PRODUCTION:
        raise RuntimeError(
            "SECRET_KEY ist nicht gesetzt. In Produktion ist das Pflicht – "
            "bitte einen langen zufälligen Wert in die Umgebungsvariablen eintragen."
        )
    SECRET_KEY = "dev-secret-only-for-local-development"

HASHED_PASSWORD = os.getenv("HASHED_PASSWORD", "").strip()
if not HASHED_PASSWORD:
    if IS_PRODUCTION:
        raise RuntimeError(
            "HASHED_PASSWORD ist nicht gesetzt. In Produktion bitte zwingend "
            "einen bcrypt-Hash hinterlegen (z.B. via `htpasswd -bnBC 12 '' DEINPASSWORT`)."
        )
    # Default-Hash entspricht dem Passwort "0000" – nur für lokale Entwicklung
    HASHED_PASSWORD = "$2b$12$jzFxIK3.YqMKsKHpiPV0POH7OUK9jduaO1cYUWzknaMDiXBUwJJNO"

SESSION_COOKIE = "mt_session"
SESSION_MAX_AGE = 60 * 60 * 24 * 30  # 30 Tage

serializer = URLSafeTimedSerializer(SECRET_KEY)


def cookie_kwargs() -> dict:
    """Zentrale, sichere Cookie-Konfiguration."""
    return {
        "max_age": SESSION_MAX_AGE,
        "httponly": True,
        "samesite": "lax",
        "secure": IS_PRODUCTION,  # in Produktion nur über HTTPS
    }


def verify_password(plain: str) -> bool:
    if not plain:
        return False
    try:
        return _bcrypt.checkpw(plain.encode(), HASHED_PASSWORD.encode())
    except Exception:
        return False


def create_signed_token(process_id: str) -> str:
    return serializer.dumps(process_id)


def decode_signed_token(token: str) -> Optional[str]:
    try:
        return serializer.loads(token, max_age=SESSION_MAX_AGE)
    except (BadSignature, SignatureExpired):
        return None


def get_current_process(request: Request, db: Session) -> Optional[UserProcess]:
    token = request.cookies.get(SESSION_COOKIE)
    if not token:
        return None
    process_id = decode_signed_token(token)
    if not process_id:
        return None
    return db.query(UserProcess).filter(UserProcess.id == process_id).first()


def require_process(request: Request, db: Session) -> UserProcess:
    process = get_current_process(request, db)
    if not process:
        raise HTTPException(status_code=303, headers={"Location": "/login"})
    return process


def create_new_process(db: Session) -> Tuple[UserProcess, str]:
    # Zufällige, unvorhersagbare ID (256 Bit Entropie)
    process_id = secrets.token_urlsafe(32)
    signed = create_signed_token(process_id)
    process = UserProcess(id=process_id, session_token=process_id)
    db.add(process)
    db.commit()
    db.refresh(process)
    return process, signed


_BLOCKED_PATTERN = re.compile(
    r"\b(scheiß\w*|fick\w*|arsch\w*|wichser|hurensohn|idiot|blödmann|hure|nutte|piss\w*)\b",
    re.IGNORECASE,
)


def contains_blocked_content(text: str) -> bool:
    if not text:
        return False
    return bool(_BLOCKED_PATTERN.search(text))
