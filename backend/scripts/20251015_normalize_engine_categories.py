
# Normalize legacy engine category codes: SERV -> Services
# Safe, idempotent cleanup for existing databases.
# Path: backend/scripts/20251015_normalize_engine_categories.py

from __future__ import annotations

import argparse
import os
from pathlib import Path
from sqlalchemy import text, create_engine

TARGET_FROM = "SERV"
TARGET_TO = "Services"

def _sqlite_url_from_path(db_path: Path) -> str:
    return "sqlite:///" + db_path.as_posix()

def _resolve_db_url(cli_db: str | None) -> str:
    if cli_db:
        return cli_db
    env = os.environ.get("DATABASE_URL")
    if env:
        return env
    # Default per project manifest: backend/app.db next to this script's parent
    script_dir = Path(__file__).resolve().parent      # .../backend/scripts
    backend_dir = script_dir.parent                   # .../backend
    db_file = backend_dir / "app.db"
    return _sqlite_url_from_path(db_file)

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Normalize legacy engine category codes (SERV -> Services).")
    parser.add_argument("--db", help="Database URL, e.g. sqlite:///C:/Dev/AryaIntel_CRM/backend/app.db")
    args = parser.parse_args()

    db_url = _resolve_db_url(args.db)
    engine = create_engine(db_url, future=True)

    with engine.begin() as conn:
        # 1) Ensure the canonical 'Services' code exists (seed if missing)
        conn.execute(text("""
            INSERT INTO engine_categories (code, name, sort_order)
            VALUES (:code, :name, :order)
            ON CONFLICT(code) DO UPDATE SET
                name=excluded.name,
                sort_order=excluded.sort_order
        """), {"code": TARGET_TO, "name": "Services", "order": 40})

        # 2) Update references in engine_category_map
        res1 = conn.execute(text("""
            UPDATE engine_category_map
            SET category_code = :to, updated_at = CURRENT_TIMESTAMP
            WHERE category_code = :frm
        """), {"to": TARGET_TO, "frm": TARGET_FROM})
        updated_map = res1.rowcount

        # 3) Optional: update product_attributes if present (do nothing if table absent)
        has_pa = conn.execute(text("SELECT name FROM sqlite_master WHERE type='table' AND name='product_attributes'")).fetchone()
        updated_pa = 0
        if has_pa:
            res2 = conn.execute(text("""
                UPDATE product_attributes
                SET value = :to
                WHERE name = 'engine_category' AND value = :frm
            """), {"to": TARGET_TO, "frm": TARGET_FROM})
            updated_pa = res2.rowcount or 0

        # 4) Remove legacy code row
        res3 = conn.execute(text("""
            DELETE FROM engine_categories WHERE code = :frm
        """), {"frm": TARGET_FROM})
        deleted_legacy = res3.rowcount

    print(f"[OK] Normalization complete @ {db_url}")
    print(f" - engine_category_map updated: {updated_map}")
    print(f" - product_attributes updated: {updated_pa}")
    print(f" - engine_categories deleted legacy rows: {deleted_legacy}")
