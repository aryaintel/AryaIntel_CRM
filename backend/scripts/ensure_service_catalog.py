
# Pathway: C:/Dev/AryaIntel_CRM/backend/scripts/ensure_service_catalog.py

"""
Purpose:
- Diagnose DB path mismatch (classic cause of "no such table: service_families").
- Ensure Service Catalog tables exist in the DB your API uses (DATABASE_URL).
- Safe & idempotent: only CREATE TABLE IF NOT EXISTS and helpful indexes.
Usage:
  set DATABASE_URL to your API database (Windows example):
    set DATABASE_URL=sqlite:////C:/Dev/AryaIntel_CRM/app.db
  then run:
    python backend/scripts/ensure_service_catalog.py
"""

import os
import re
import sqlite3
from urllib.parse import urlparse, unquote
from datetime import datetime, timezone

DEFAULT_APP_DB = r"C:/Dev/AryaIntel_CRM/app.db"

def parse_sqlite_path(database_url: str) -> str:
    """
    Accepts forms like:
      sqlite:///C:/Dev/AryaIntel_CRM/app.db
      sqlite:////C:/Dev/AryaIntel_CRM/app.db
      sqlite:///./app.db
      sqlite:///app.db
    Returns absolute Windows path string.
    """
    if not database_url or not database_url.startswith("sqlite"):
        return DEFAULT_APP_DB

    # strip "sqlite://"
    rest = database_url[len("sqlite:"):]
    # normalize slashes
    rest = rest.lstrip("/")

    # If starts with drive letter like C:/..., keep as-is
    if re.match(r"^[A-Za-z]:/", rest):
        return unquote(rest)

    # If it's relative like "./app.db" or "app.db"
    if rest.startswith("./") or not (":" in rest[:3] or rest.startswith("/")):
        # resolve relative to current working directory
        return os.path.abspath(unquote(rest))

    # Fallback
    return unquote(rest)

def ensure_tables(db_path: str):
    os.makedirs(os.path.dirname(db_path), exist_ok=True)
    con = sqlite3.connect(db_path)
    try:
        cur = con.cursor()
        # service_families
        cur.execute("""
            CREATE TABLE IF NOT EXISTS service_families (
                id INTEGER PRIMARY KEY,
                code TEXT UNIQUE NOT NULL,
                name TEXT NOT NULL,
                is_active INTEGER NOT NULL DEFAULT 1,
                sort_order INTEGER NOT NULL DEFAULT 0,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            );
        """)
        cur.execute("CREATE UNIQUE INDEX IF NOT EXISTS ux_service_families_code ON service_families(code);")
        cur.execute("CREATE INDEX IF NOT EXISTS ix_service_families_active ON service_families(is_active);")

        # services_catalog
        cur.execute("""
            CREATE TABLE IF NOT EXISTS services_catalog (
                id INTEGER PRIMARY KEY,
                family_id INTEGER NOT NULL,
                code TEXT UNIQUE NOT NULL,
                name TEXT NOT NULL,
                uom TEXT,
                default_currency TEXT,
                is_active INTEGER NOT NULL DEFAULT 1,
                description TEXT,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                FOREIGN KEY (family_id) REFERENCES service_families(id) ON DELETE RESTRICT
            );
        """)
        cur.execute("CREATE UNIQUE INDEX IF NOT EXISTS ux_services_catalog_code ON services_catalog(code);")
        cur.execute("CREATE INDEX IF NOT EXISTS ix_services_catalog_family ON services_catalog(family_id);")
        cur.execute("CREATE INDEX IF NOT EXISTS ix_services_catalog_active ON services_catalog(is_active);")

        con.commit()
    finally:
        con.close()

def main():
    db_url = os.environ.get("DATABASE_URL", "")
    app_db_env = os.environ.get("APP_DB_PATH", DEFAULT_APP_DB)
    api_db_path = parse_sqlite_path(db_url) if db_url else DEFAULT_APP_DB

    print("[INFO] DATABASE_URL        :", db_url or "(not set)")
    print("[INFO] Parsed API DB Path  :", api_db_path)
    print("[INFO] APP_DB_PATH (mig)   :", app_db_env)

    # Ensure tables in API DB
    ensure_tables(api_db_path)
    print("[OK] Ensured Service Catalog tables in:", api_db_path)

    # Optional: show quick presence check
    con = sqlite3.connect(api_db_path)
    try:
        cur = con.cursor()
        cur.execute("SELECT name FROM sqlite_master WHERE type='table' AND name in ('service_families','services_catalog') ORDER BY name;")
        print("[INFO] Tables present     :", [r[0] for r in cur.fetchall()])
    finally:
        con.close()

if __name__ == "__main__":
    main()
