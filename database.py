import os
import json
import base64
import hashlib
from datetime import datetime
from sqlalchemy import create_engine, Column, String, DateTime, Text
from sqlalchemy.orm import DeclarativeBase, sessionmaker
from cryptography.fernet import Fernet, InvalidToken
from dotenv import load_dotenv

load_dotenv()

DATABASE_URL = os.getenv("DATABASE_URL", "sqlite:///./traumjob.db")

engine = create_engine(DATABASE_URL, connect_args={"check_same_thread": False})
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


# ---------------------------------------------------------------------------
# Verschlüsselung sensibler Felder
# ---------------------------------------------------------------------------

def _build_fernet() -> Fernet:
    """Holt den Fernet-Schlüssel aus ENCRYPTION_KEY oder leitet ihn aus SECRET_KEY ab.

    Toleriert übliche Copy-Paste-Probleme: Whitespace, fehlende Padding-Zeichen,
    umgebende Anführungszeichen.
    """
    key = os.getenv("ENCRYPTION_KEY", "").strip().strip('"').strip("'")
    if key:
        # Padding wieder ergänzen falls "=" beim Kopieren verlorenging
        missing_pad = (-len(key)) % 4
        if missing_pad:
            key = key + ("=" * missing_pad)
        try:
            return Fernet(key.encode())
        except Exception:
            # Falls trotzdem ungültig: deterministisch ableiten – Daten bleiben lesbar
            pass
    secret = os.getenv("SECRET_KEY", "dev-secret").encode()
    derived = base64.urlsafe_b64encode(hashlib.sha256(secret).digest())
    return Fernet(derived)


_fernet = _build_fernet()


def _encrypt(plain: str) -> str:
    return _fernet.encrypt(plain.encode("utf-8")).decode("ascii")


def _decrypt(token: str) -> str:
    """Entschlüsselt – fällt bei Legacy-Klartext auf den Originalwert zurück."""
    try:
        return _fernet.decrypt(token.encode("ascii")).decode("utf-8")
    except (InvalidToken, ValueError, UnicodeDecodeError):
        return token


class Base(DeclarativeBase):
    pass


class UserProcess(Base):
    __tablename__ = "processes"

    id = Column(String, primary_key=True)
    session_token = Column(String, unique=True, index=True, nullable=False)
    current_step = Column(String, default="start")

    # Jeder Schritt als JSON-Text gespeichert (sensible Felder verschlüsselt)
    fakten = Column(Text, nullable=True)
    video_confirmed = Column(String, nullable=True)
    reflexion = Column(Text, nullable=True)
    charakter = Column(Text, nullable=True)
    werte = Column(Text, nullable=True)
    energie = Column(Text, nullable=True)
    berufsfelder = Column(Text, nullable=True)
    vergleich = Column(Text, nullable=True)
    ergebnis = Column(Text, nullable=True)
    favoriten = Column(Text, nullable=True)
    links_data = Column(Text, nullable=True)

    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    # Diese Felder werden verschlüsselt im Klartext-Spaltentext (Fernet base64)
    SENSITIVE_FIELDS = {
        "fakten", "reflexion", "charakter", "werte", "energie", "berufsfelder",
        "vergleich", "ergebnis", "favoriten", "links_data",
    }

    def get_json(self, field: str):
        val = getattr(self, field)
        if val is None:
            return None
        if field in self.SENSITIVE_FIELDS:
            val = _decrypt(val)
        try:
            return json.loads(val)
        except (json.JSONDecodeError, TypeError):
            return None

    def set_json(self, field: str, data) -> None:
        raw = json.dumps(data, ensure_ascii=False)
        if field in self.SENSITIVE_FIELDS:
            raw = _encrypt(raw)
        setattr(self, field, raw)


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def init_db():
    Base.metadata.create_all(bind=engine)
    # Migration: neue Spalten nachträglich anlegen falls DB schon existiert
    with engine.connect() as conn:
        try:
            cols = {row[1] for row in conn.exec_driver_sql("PRAGMA table_info(processes)").fetchall()}
            for new_col in ("werte", "energie"):
                if new_col not in cols:
                    conn.exec_driver_sql(f"ALTER TABLE processes ADD COLUMN {new_col} TEXT")
            conn.commit()
        except Exception:
            pass
