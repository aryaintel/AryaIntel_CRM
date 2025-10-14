# Idempotent schema helper for engine category mapping.
# Exposes ensure_schema(engine) so the API can import and call it during startup.
# Path: backend/scripts/20251015_add_engine_category_map.py

from __future__ import annotations

import argparse
import os
from pathlib import Path
from sqlalchemy import text, create_engine
from sqlalchemy.engine import Engine

ENGINE_CATEGORIES = [
    ("AN", "Ammonium Nitrate", 10),
    ("EM", "Emulsion", 20),
    ("IE", "Initiating Explosives", 30),
    ("Services", "Services", 40),
]

def ensure_schema(engine: Engine) -> None:
    with engine.begin() as conn:
        # engine_categories
        conn.execute(text("""
            CREATE TABLE IF NOT EXISTS engine_categories (
                code TEXT PRIMARY KEY,
                name TEXT,
                sort_order INTEGER
            )
        """))

        # seed codes (upsert for SQLite)
        for code, name, sort_order in ENGINE_CATEGORIES:
            conn.execute(text("""
                INSERT INTO engine_categories (code, name, sort_order)
                VALUES (:code, :name, :order)
                ON CONFLICT(code) DO UPDATE SET
                    name=excluded.name,
                    sort_order=excluded.sort_order
            """), {"code": code, "name": name, "order": sort_order})

        # engine_category_map
        conn.execute(text("""
            CREATE TABLE IF NOT EXISTS engine_category_map (
                id INTEGER PRIMARY KEY,
                scope TEXT NOT NULL,          -- 'product_family' | 'product'
                ref_id INTEGER NOT NULL,      -- family.id or product.id
                category_code TEXT NOT NULL,  -- FK to engine_categories.code
                is_active INTEGER NOT NULL DEFAULT 1,
                note TEXT,
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
            )
        """))

        # unique composite index so scope+ref is a single active row
        conn.execute(text("""
            CREATE UNIQUE INDEX IF NOT EXISTS ux_ecm_scope_ref
            ON engine_category_map(scope, ref_id)
        """))

def _sqlite_url_from_path(db_path: Path) -> str:
    # SQLAlchemy on Windows expects sqlite:///C:/... for absolute paths
    return "sqlite:///" + db_path.as_posix()

def _resolve_db_url(cli_db: str | None) -> str:
    # Priority 1: CLI --db
    if cli_db:
        return cli_db
    # Priority 2: env var
    env = os.environ.get("DATABASE_URL")
    if env:
        return env

    # Priority 3: project manifest default (Windows dev path)
    # Manifest says DB is at AryaIntel_CRM\backend\app.db
    # Try to infer the absolute path based on this script's location.
    script_dir = Path(__file__).resolve().parent  # .../backend/scripts
    backend_dir = script_dir.parent               # .../backend
    db_file = backend_dir / "app.db"
    return _sqlite_url_from_path(db_file)

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Ensure engine category schema.")
    parser.add_argument("--db", help="Database URL (e.g., sqlite:///C:/Dev/AryaIntel_CRM/backend/app.db)")
    args = parser.parse_args()

    db_url = _resolve_db_url(args.db)
    # Make sure parent dir exists for SQLite file URLs
    if db_url.startswith("sqlite:///"):
        # Extract path portion after sqlite:///
        raw = db_url[len("sqlite:///"):]
        # Convert to Path; handle URL-style forward slashes on Windows
        db_path = Path(raw)
        db_parent = db_path.parent
        if not db_parent.exists():
            raise SystemExit(f"[ERROR] Database directory does not exist: {db_parent}")
    engine = create_engine(db_url, future=True)
    ensure_schema(engine)
    print(f"[OK] engine_category_map schema ensured at: {db_url}")
