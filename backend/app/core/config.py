# app/core/config.py
from pydantic_settings import BaseSettings
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, Session
import secrets
from typing import List


class Settings(BaseSettings):
    # --- Security / JWT ---
    SECRET_KEY: str = secrets.token_urlsafe(32)  # prod'da ENV ile ver
    ALGORITHM: str = "HS256"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 60 * 24  # 24 saat

    # --- Database ---
    DATABASE_URL: str = "sqlite:///./app.db"

    # --- CORS ---
    CORS_ALLOW_ORIGINS: List[str] = ["*"]

    class Config:
        env_file = ".env"
        case_sensitive = True


settings = Settings()

# SQLite için özel connect args
connect_args = {"check_same_thread": False} if settings.DATABASE_URL.startswith("sqlite") else {}

# SQLAlchemy Engine & Session
engine = create_engine(settings.DATABASE_URL, connect_args=connect_args, future=True)
SessionLocal = sessionmaker(bind=engine, autocommit=False, autoflush=False, future=True)


def get_db() -> Session:
    """FastAPI dependency — request boyunca DB session sağlar."""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
