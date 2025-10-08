#!/usr/bin/env python3
"""
Widen scenario_boq_items.category CHECK to include 'capex_return'.

Idempotent:
- If 'capex_return' already allowed, prints [skip] and exits 0.
- Otherwise, on SQLite: recreates table from sqlite_master SQL with adjusted CHECK,
  copies data, restores indexes & triggers.
- On PostgreSQL/MySQL: attempts DROP/ADD the named CHECK if present; otherwise no-op.

Usage:
  python backend/scripts/20251009_add_boq_category_capex_return.py --db sqlite:///C:/Dev/AryaIntel_CRM/app.db
"""

import argparse
import re
import sys
from contextlib import contextmanager

from sqlalchemy import create_engine, text
from sqlalchemy.engine import Engine


TARGET_TABLE = "scenario_boq_items"
CHECK_NAME = "ck_boq_category"
TARGET_VALUE = "capex_return"


def _log(msg: str) -> None:
    print(msg, flush=True)


@contextmanager
def _begin(engine: Engine):
    with engine.connect() as conn:
        trans = conn.begin()
        try:
            yield conn
            trans.commit()
        except:  # noqa
            trans.rollback()
            raise


def _already_allows(sql: str) -> bool:
    """Return True if CREATE TABLE SQL already contains capex_return in the category CHECK."""
    m = re.search(r"CHECK\s*\(\s*category\s+IN\s*\(([^)]*)\)\s*\)", sql, flags=re.IGNORECASE)
    if not m:
        return False
        # (No explicit CHECK found; treat as not-allowed so we can add it if we’re rebuilding.)
    inner = m.group(1)
    # Extract tokens like 'bulk_with_freight'
    vals = [v.strip().strip("'\"") for v in inner.split(",")]
    return TARGET_VALUE in vals


def _inject_capex_return(sql: str) -> str:
    """
    Modify the CREATE TABLE SQL to include 'capex_return' in the category CHECK.
    """
    def _repl(match: re.Match) -> str:
        inner = match.group(1)
        vals = [v.strip() for v in inner.split(",") if v.strip()]
        # Normalize and ensure quoted single tokens
        parsed = []
        for v in vals:
            v = v.strip()
            v = v.strip("'").strip('"')
            parsed.append(v)
        if TARGET_VALUE not in parsed:
            parsed.append(TARGET_VALUE)
        rebuilt = ", ".join(f"'{v}'" for v in parsed)
        return f"CHECK(category IN ({rebuilt}))"

    # Replace the first matching category IN (...) CHECK
    new_sql, n = re.subn(
        r"CHECK\s*\(\s*category\s+IN\s*\(([^)]*)\)\s*\)",
        _repl,
        sql,
        count=1,
        flags=re.IGNORECASE,
    )
    if n == 0:
        # No CHECK found — create one by appending a CHECK near the end, before closing paren
        # Find last closing ) of column list
        close_idx = new_sql.rfind(")")
        if close_idx == -1:
            raise RuntimeError("Could not locate column list to append CHECK().")
        # Append with preceding comma
        injected = ", CHECK(category IN ('bulk_with_freight','bulk_ex_freight','freight','capex_return'))"
        new_sql = new_sql[:close_idx] + injected + new_sql[close_idx:]
    return new_sql


def _sqlite_migrate(engine: Engine) -> None:
    with engine.connect() as conn:
        row = conn.execute(
            text("SELECT sql FROM sqlite_master WHERE type='table' AND name=:t"),
            {"t": TARGET_TABLE},
        ).fetchone()
        if not row or not row[0]:
            _log(f"[error] Table {TARGET_TABLE} not found.")
            sys.exit(1)
        create_sql = row[0]

        if _already_allows(create_sql):
            _log("[skip] 'capex_return' already allowed in CHECK.")
            return

        _log("[info] Rebuilding table to widen CHECK (SQLite).")

        # Build new CREATE TABLE with widened CHECK
        widened_sql = _inject_capex_return(create_sql)

        # Build a temporary CREATE TABLE by renaming the table identifier inside the SQL
        tmp_table = f"{TARGET_TABLE}__tmp"
        widened_sql_tmp = re.sub(
            r"(?i)^(CREATE\s+TABLE\s+)(\"?%s\"?)" % re.escape(TARGET_TABLE),
            r"\1%s" % tmp_table,
            widened_sql,
            count=1,
        )

        # Capture column list from current table for INSERT copy
        cols = [
            r[1]
            for r in conn.execute(text(f"PRAGMA table_info('{TARGET_TABLE}')")).fetchall()
        ]
        if not cols:
            _log(f"[error] Could not read PRAGMA table_info('{TARGET_TABLE}').")
            sys.exit(1)
        col_list = ", ".join(f'"{c}"' for c in cols)

        # Save index & trigger SQL to recreate later
        idx_rows = conn.execute(
            text("SELECT name, sql FROM sqlite_master WHERE type='index' AND tbl_name=:t AND sql IS NOT NULL"),
            {"t": TARGET_TABLE},
        ).fetchall()
        trg_rows = conn.execute(
            text("SELECT name, sql FROM sqlite_master WHERE type='trigger' AND tbl_name=:t"),
            {"t": TARGET_TABLE},
        ).fetchall()

    # Perform rebuild inside a transaction with foreign_keys OFF
    with engine.connect() as conn, conn.begin():
        conn.execute(text("PRAGMA foreign_keys=OFF"))

        # Safety: drop temp if exists (idempotency on previous partial runs)
        conn.execute(text(f"DROP TABLE IF EXISTS {tmp_table}"))

        # Create temp widened table
        conn.execute(text(widened_sql_tmp))

        # Copy data
        conn.execute(
            text(f'INSERT INTO {tmp_table} ({col_list}) SELECT {col_list} FROM {TARGET_TABLE}')
        )

        # Drop old table & rename back
        conn.execute(text(f"DROP TABLE {TARGET_TABLE}"))
        conn.execute(text(f"ALTER TABLE {tmp_table} RENAME TO {TARGET_TABLE}"))

        # Recreate indexes
        for name, idx_sql in idx_rows:
            if not idx_sql:
                continue
            conn.execute(text(idx_sql))

        # Recreate triggers
        for name, trg_sql in trg_rows:
            if not trg_sql:
                continue
            conn.execute(text(trg_sql))

        conn.execute(text("PRAGMA foreign_keys=ON"))

    _log("[done] CHECK widened to include 'capex_return' (SQLite).")


def _pg_or_mysql_migrate(engine: Engine) -> None:
    # Best-effort: drop & add named check constraint if present
    dialect = engine.dialect.name
    _log(f"[info] {dialect}: attempting to update named CHECK '{CHECK_NAME}'.")

    with _begin(engine) as conn:
        # Inspect if already allowed (via INFORMATION_SCHEMA or by trial insert into temp table).
        # Simpler: try to add a compatible CHECK; if it already allows, we'll detect and skip.
        try:
            # try drop existing named check (if exists)
            conn.execute(text(f'ALTER TABLE {TARGET_TABLE} DROP CONSTRAINT IF EXISTS {CHECK_NAME}'))
        except Exception:
            pass

        # Recreate CHECK with widened set
        try:
            conn.execute(text(
                f"ALTER TABLE {TARGET_TABLE} "
                f"ADD CONSTRAINT {CHECK_NAME} "
                f"CHECK (category IN ('bulk_with_freight','bulk_ex_freight','freight','capex_return'))"
            ))
            _log("[done] CHECK widened (server-side RDBMS).")
        except Exception as e:
            _log(f"[warn] Could not alter CHECK (possibly already widened or unnamed): {e}")
            _log("[skip] Leaving table unchanged.")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--db", required=True, help="SQLAlchemy DB URL, e.g. sqlite:///C:/Dev/AryaIntel_CRM/app.db")
    args = ap.parse_args()

    engine = create_engine(args.db)
    dialect = engine.dialect.name

    _log(f"[info] Target table: {TARGET_TABLE}")
    _log(f"[info] DB dialect: {dialect}")

    if dialect == "sqlite":
        _sqlite_migrate(engine)
    elif dialect in ("postgresql", "mysql", "mariadb"):
        _pg_or_mysql_migrate(engine)
    else:
        _log(f"[warn] Unsupported dialect '{dialect}'. No changes applied.")
        sys.exit(0)


if __name__ == "__main__":
    main()
