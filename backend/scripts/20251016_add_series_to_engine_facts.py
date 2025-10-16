# Path: backend/scripts/20251016_add_series_to_engine_facts_v2.py
"""
Migration: add `series` column + indexes to engine_facts_monthly (idempotent)
- Robust Windows/SQLite URL handling
- Helpful diagnostics when SQLite can't open the file

Usage (Windows PowerShell):
  python backend\scripts\20251016_add_series_to_engine_facts_v2.py --db "sqlite:///C:/Dev/AryaIntel_CRM/backend/app.db"
  # or if your DB is at repo root (legacy):
  python backend\scripts\20251016_add_series_to_engine_facts_v2.py --db "sqlite:///C:/Dev/AryaIntel_CRM/app.db"

If you pass a plain file path ending with .db, the script will convert it to a valid sqlite URL for you.
"""

from __future__ import annotations
import argparse
import os
import re
import sys
from pathlib import Path
from typing import Optional, Tuple, List

from sqlalchemy import create_engine, text
from sqlalchemy.engine import Engine
from sqlalchemy.exc import OperationalError

# ------------------------
# URL normalization helpers
# ------------------------

def is_windows() -> bool:
    return os.name == "nt"

def to_sqlite_url(db: str) -> str:
    """
    Accepts forms like:
      - sqlite:///C:/path/file.db
      - sqlite:////C:/path/file.db
      - C:\\path\\file.db
      - C:/path/file.db
    Returns a normalized SQLAlchemy sqlite URL.
    """
    if db.lower().startswith("sqlite:"):
        # Already a URL
        if is_windows():
            # We'll try both 3-slash and 4-slash variants later if needed.
            return db
        else:
            return db

    # Plain file path -> build sqlite URL
    p = Path(db)
    # Expand environment variables and user home (just in case)
    db_path = Path(os.path.expandvars(os.path.expanduser(str(p)))).resolve()
    if is_windows():
        # Windows: prefer sqlite:///C:/... (three slashes)
        url = f"sqlite:///{db_path.as_posix()}"
    else:
        # POSIX absolute
        url = f"sqlite:////{db_path.as_posix()}"
    return url

def try_connect(url: str) -> Tuple[Optional[Engine], Optional[str]]:
    """
    Try connecting, return (engine, error_message).
    If fails, return (None, error).
    """
    try:
        eng = create_engine(url, future=True)
        with eng.connect() as conn:
            conn.execute(text("SELECT 1"))
        return eng, None
    except OperationalError as e:
        return None, f"{e.__class__.__name__}: {e}"
    except Exception as e:
        return None, f"{e.__class__.__name__}: {e}"

def resolve_engine(db_arg: Optional[str]) -> Engine:
    """
    Pick a URL based on (1) --db, (2) DATABASE_URL env, (3) common defaults.
    Try a few safe variants on Windows (3-slash vs 4-slash).
    """
    candidates: List[str] = []
    if db_arg:
        candidates.append(to_sqlite_url(db_arg))

    env = os.getenv("DATABASE_URL")
    if env:
        candidates.append(to_sqlite_url(env))

    # Common repo defaults
    defaults = [
        # backend/app.db (current manifest)
        Path("backend/app.db"),
        # repo root app.db (legacy)
        Path("app.db"),
    ]
    for d in defaults:
        if d.exists():
            candidates.append(to_sqlite_url(str(d.resolve())))
        else:
            candidates.append(to_sqlite_url(str(d)))

    # On Windows, if a candidate is sqlite:////C:/..., also try sqlite:///C:/...
    expanded: List[str] = []
    for c in candidates:
        expanded.append(c)
        if is_windows() and c.lower().startswith("sqlite:////") and re.search(r":/", c):
            expanded.append("sqlite:///" + c[len("sqlite:////"):])
        if is_windows() and c.lower().startswith("sqlite:///") and re.search(r":/", c):
            expanded.append("sqlite:////" + c[len("sqlite:///"):])

    # Deduplicate preserving order
    seen = set()
    final_candidates = []
    for c in expanded:
        if c not in seen:
            seen.add(c)
            final_candidates.append(c)

    print("[info] DB candidates (in order):")
    for c in final_candidates:
        print("   ", c)

    last_err = None
    for url in final_candidates:
        print(f"[info] trying: {url}")
        eng, err = try_connect(url)
        if eng:
            print(f"[ok] connected: {url}")
            return eng
        else:
            print(f"[warn] failed: {err}")
            last_err = err

    raise SystemExit(f"[fatal] could not connect to any candidate. Last error: {last_err}")

# ------------------------
# Schema helpers
# ------------------------

def table_exists(db: Engine, name: str) -> bool:
    with db.begin() as cx:
        res = cx.execute(text(
            "SELECT name FROM sqlite_master WHERE type='table' AND name=:n"
        ), {"n": name}).fetchone()
        return bool(res)

def column_exists(db: Engine, table: str, column: str) -> bool:
    with db.begin() as cx:
        res = cx.execute(text(f"PRAGMA table_info('{table}')")).fetchall()
        return any(r[1] == column for r in res)  # r[1]=name

def index_exists(db: Engine, name: str) -> bool:
    with db.begin() as cx:
        res = cx.execute(text(
            "SELECT name FROM sqlite_master WHERE type='index' AND name=:n"
        ), {"n": name}).fetchone()
        return bool(res)

def create_index(db: Engine, sql: str, name: str):
    if index_exists(db, name):
        print(f"[skip] index exists: {name}")
        return
    with db.begin() as cx:
        cx.execute(text(sql))
    print(f"[ok] index created: {name}")

def ensure_migrations_table(db: Engine):
    with db.begin() as cx:
        cx.execute(text("""
        CREATE TABLE IF NOT EXISTS arya_migrations (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            code TEXT UNIQUE NOT NULL,
            applied_at TEXT DEFAULT (datetime('now'))
        )
        """))
    print("[ok] ensured arya_migrations table")

def record_migration(db: Engine, code: str):
    with db.begin() as cx:
        cx.execute(text("""
            INSERT INTO arya_migrations(code, applied_at)
            VALUES (:c, datetime('now'))
            ON CONFLICT(code) DO UPDATE SET applied_at = excluded.applied_at
        """), {"c": code})
    print(f"[ok] recorded migration: {code}")

# ------------------------
# Migration logic
# ------------------------

MIGRATION_CODE = "20251016_add_series_to_engine_facts"

def migrate(db: Engine):
    if not table_exists(db, "engine_facts_monthly"):
        raise SystemExit("[fatal] table engine_facts_monthly not found. Abort.")

    # 1) Add column `series` if missing
    if not column_exists(db, "engine_facts_monthly", "series"):
        with db.begin() as cx:
            cx.execute(text("ALTER TABLE engine_facts_monthly ADD COLUMN series TEXT"))
        print("[ok] column added: engine_facts_monthly.series")
    else:
        print("[skip] column exists: engine_facts_monthly.series")

    # 2) Partial unique indexes for legacy/new rows
    #    Note: partial indexes require SQLite 3.8.0+
    create_index(
        db,
        """
        CREATE UNIQUE INDEX ux_efm_run_sheet_cat_yyyymm_legacy
        ON engine_facts_monthly (run_id, sheet_code, category_code, yyyymm)
        WHERE series IS NULL
        """,
        "ux_efm_run_sheet_cat_yyyymm_legacy"
    )

    create_index(
        db,
        """
        CREATE UNIQUE INDEX ux_efm_run_sheet_cat_yyyymm_series
        ON engine_facts_monthly (run_id, sheet_code, category_code, yyyymm, series)
        WHERE series IS NOT NULL
        """,
        "ux_efm_run_sheet_cat_yyyymm_series"
    )

    # 3) Composite lookup index (create only if these columns exist)
    needed = ["scenario_id", "run_id", "sheet_code", "category_code", "yyyymm", "series"]
    if all(column_exists(db, "engine_facts_monthly", c) for c in needed):
        create_index(
            db,
            """
            CREATE INDEX ix_efm_scenario_run_sheet_cat_yyyymm_series
            ON engine_facts_monthly (scenario_id, run_id, sheet_code, category_code, yyyymm, series)
            """,
            "ix_efm_scenario_run_sheet_cat_yyyymm_series"
        )
    else:
        print("[warn] skipped composite lookup index; some columns missing")

    ensure_migrations_table(db)
    record_migration(db, MIGRATION_CODE)

# ------------------------
# CLI
# ------------------------

def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--db", help="Database URL or .db file path (sqlite). "
                                 "Examples: sqlite:///C:/Dev/AryaIntel_CRM/backend/app.db  |  C:\\Dev\\AryaIntel_CRM\\backend\\app.db")
    args = ap.parse_args(argv)

    eng = resolve_engine(args.db)
    migrate(eng)
    print("[done] migration completed successfully.")
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
