# Pathway: C:/Dev/AryaIntel_CRM/backend/migrations/20251011_add_service_catalog.py
"""Idempotent migration: Add Service Catalog (families & services) for Products-like Services page.

- Creates:
    * service_families (id, code, name, is_active, sort_order, created_at, updated_at)
    * services_catalog (id, family_id, code, name, uom, default_currency, is_active, description, created_at, updated_at)
- Adds helpful indexes and constraints.
- Seeds a minimal default set of families (Labor, Equipment, Freight) if none exist (optional bootstrap).

Conventions:
* Uses APP_DB_PATH env var if present; falls back to 'C:/Dev/AryaIntel_CRM/app.db' (Windows dev default).
* Idempotent: safe to run multiple times.
* No destructive changes.

Run:
    python backend/migrations/20251011_add_service_catalog.py
"""

import os
import sqlite3
from datetime import datetime

DEFAULT_DB = r"C:/Dev/AryaIntel_CRM/app.db"
DB_PATH = os.environ.get("APP_DB_PATH", DEFAULT_DB)

def _exec(cur, sql, params=None):
    cur.execute(sql, params or ())

def _table_exists(cur, name: str) -> bool:
    _exec(cur, "SELECT name FROM sqlite_master WHERE type='table' AND name=?", (name,))
    return cur.fetchone() is not None

def _col_names(cur, table: str):
    _exec(cur, f"PRAGMA table_info({table})")
    return [row[1] for row in cur.fetchall()]

def ensure_service_families(cur):
    if not _table_exists(cur, "service_families"):
        _exec(cur, """                CREATE TABLE service_families (
                id INTEGER PRIMARY KEY,
                code TEXT UNIQUE NOT NULL,
                name TEXT NOT NULL,
                is_active INTEGER NOT NULL DEFAULT 1,
                sort_order INTEGER NOT NULL DEFAULT 0,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            );
        """)
        _exec(cur, "CREATE UNIQUE INDEX IF NOT EXISTS ux_service_families_code ON service_families(code);")
        _exec(cur, "CREATE INDEX IF NOT EXISTS ix_service_families_active ON service_families(is_active);")

def ensure_services_catalog(cur):
    if not _table_exists(cur, "services_catalog"):
        _exec(cur, """                CREATE TABLE services_catalog (
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
        """ )
        _exec(cur, "CREATE UNIQUE INDEX IF NOT EXISTS ux_services_catalog_code ON services_catalog(code);")
        _exec(cur, "CREATE INDEX IF NOT EXISTS ix_services_catalog_family ON services_catalog(family_id);")
        _exec(cur, "CREATE INDEX IF NOT EXISTS ix_services_catalog_active ON services_catalog(is_active);")

def seed_defaults(cur):
    now = datetime.utcnow().isoformat(timespec='seconds') + 'Z'
    # Seed minimal families if table empty
    _exec(cur, "SELECT COUNT(1) FROM service_families")
    count = cur.fetchone()[0]
    if count == 0:
        families = [
            ("LABOR", "Labor", 1, 0, now, now),
            ("EQUIP", "Equipment", 1, 1, now, now),
            ("FREIGHT", "Freight", 1, 2, now, now),
        ]
        for code, name, active, sort_order, ca, ua in families:
            _exec(cur, """                    INSERT OR IGNORE INTO service_families(code, name, is_active, sort_order, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?);
            """, (code, name, active, sort_order, ca, ua))

    # No default seed for services_catalog (depends on Excel mapping); keep empty scaffold.

def migrate():
    os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
    con = sqlite3.connect(DB_PATH)
    try:
        cur = con.cursor()
        ensure_service_families(cur)
        ensure_services_catalog(cur)
        seed_defaults(cur)
        con.commit()
        print(f"[OK] Service Catalog migration complete on {DB_PATH}")
    finally:
        con.close()

if __name__ == "__main__":
    migrate()
