# backend/app/core/deps.py
from .config import SessionLocal  # ← DOĞRU: SessionLocal config'ten gelir

def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
