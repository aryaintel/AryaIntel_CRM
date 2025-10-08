# PATH: backend/scripts/migrations/2025_10_08_add_cost_books_and_entries.py
"""
AryaIntel CRM — DB migration
Adds Cost Books (cost_books) and Cost Book Entries (cost_book_entries) to centralize unit costs
(similar to Price Books), following Salesforce CPQ-style separation of price vs cost.

- Idempotent: safe to run multiple times.
- SQLite-friendly DDL (exec_driver_sql-equivalent via sqlite3).
- Seeds a single default active Cost Book using the default Price Book currency if available.
- Enforces “exactly one default active cost book”.

Default DB path (override with --db): C:/Dev/AryaIntel_CRM/app.db
"""

import argparse
import sqlite3
from datetime import datetime

DEFAULT_DB_PATH = r"C:/Dev/AryaIntel_CRM/app.db"

DDL_COST_BOOKS = """
CREATE TABLE IF NOT EXISTS cost_books (
  id          INTEGER PRIMARY KEY,
  code        VARCHAR NOT NULL UNIQUE,
  name        VARCHAR NOT NULL,
  currency    VARCHAR(3) NOT NULL,               -- mirror price_books
  is_active   BOOLEAN NOT NULL DEFAULT 1,
  is_default  BOOLEAN NOT NULL DEFAULT 0,
  created_at  DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
  updated_at  DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP
);
"""

DDL_IDX_COST_BOOKS = [
    ("ix_cost_books_active",  "CREATE INDEX IF NOT EXISTS ix_cost_books_active  ON cost_books(is_active)"),
    ("ix_cost_books_default", "CREATE INDEX IF NOT EXISTS ix_cost_books_default ON cost_books(is_default)"),
    ("ix_cost_books_id",      "CREATE INDEX IF NOT EXISTS ix_cost_books_id      ON cost_books(id)"),
]

DDL_COST_BOOK_ENTRIES = """
CREATE TABLE IF NOT EXISTS cost_book_entries (
  id             INTEGER PRIMARY KEY,
  cost_book_id   INTEGER NOT NULL REFERENCES cost_books(id) ON DELETE CASCADE,
  product_id     INTEGER NOT NULL REFERENCES products(id),
  valid_from     DATE,                                   -- inclusive
  valid_to       DATE,                                   -- inclusive; NULL=open-ended
  unit_cost      NUMERIC(18, 4) NOT NULL,               -- normalized to book currency
  cost_term      TEXT,                                   -- snapshot (e.g., EXW)
  cost_term_id   INTEGER REFERENCES price_terms(id),     -- normalized FK (if available)
  notes          TEXT
);
"""

DDL_IDX_COST_BOOK_ENTRIES = [
    ("ix_cbe_book",     "CREATE INDEX IF NOT EXISTS ix_cbe_book    ON cost_book_entries(cost_book_id)"),
    ("ix_cbe_product",  "CREATE INDEX IF NOT EXISTS ix_cbe_product ON cost_book_entries(product_id)"),
    # Helpful composite for best-cost lookups by window/term:
    ("ix_cbe_lookup",   "CREATE INDEX IF NOT EXISTS ix_cbe_lookup  ON cost_book_entries(product_id, cost_term_id, valid_from, valid_to)"),
]

DDL_MIGRATIONS = """
CREATE TABLE IF NOT EXISTS arya_migrations (
  name       TEXT PRIMARY KEY,
  applied_at DATETIME NOT NULL
);
"""

MIGRATION_NAME = "2025_10_08_add_cost_books_and_entries"


def exec_many(cur, stmts):
    for _, sql in stmts:
        cur.execute(sql)


def get_default_price_book_currency(cur) -> str | None:
    """
    Try to reuse the default Price Book currency to keep system consistent.
    Falls back to 'USD' if not available.
    """
    try:
        cur.execute("""
            SELECT currency
            FROM price_books
            WHERE is_active=1 AND is_default=1
            ORDER BY id DESC
            LIMIT 1
        """)
        row = cur.fetchone()
        if row and row[0]:
            return row[0]
    except sqlite3.Error:
        pass
    return None


def ensure_one_default_active_cost_book(cur):
    """
    Make sure there is exactly one default active cost book.
    If none: pick the latest active one.
    If many: keep the most recent, clear others.
    """
    cur.execute("SELECT id FROM cost_books WHERE is_active=1 AND is_default=1 ORDER BY id DESC")
    ids = [r[0] for r in cur.fetchall()]

    if len(ids) == 0:
        # No default: choose the latest active or make the only one default if single exists
        cur.execute("SELECT id FROM cost_books WHERE is_active=1 ORDER BY id DESC LIMIT 1")
        r = cur.fetchone()
        if r:
            cur.execute("UPDATE cost_books SET is_default=1 WHERE id=?", (r[0],))
    elif len(ids) > 1:
        # More than one default: keep the most recent as default, clear others
        keep = ids[0]
        cur.execute("UPDATE cost_books SET is_default=0 WHERE is_default=1")
        cur.execute("UPDATE cost_books SET is_default=1 WHERE id=?", (keep,))


def seed_default_cost_book_if_needed(cur):
    """
    Seed one sensible default book if table is empty.
    """
    cur.execute("SELECT COUNT(1) FROM cost_books")
    (count,) = cur.fetchone()
    if count and count > 0:
        return  # already seeded

    currency = get_default_price_book_currency(cur) or "USD"

    # Try stable deterministic code/name
    code = "COST-DEFAULT"
    name = "Default Cost Book"

    # Upsert-like insert (idempotent)
    cur.execute("""
        INSERT OR IGNORE INTO cost_books (code, name, currency, is_active, is_default)
        VALUES (?, ?, ?, 1, 1)
    """, (code, name, currency))

    # If the INSERT OR IGNORE hit a conflict, ensure we still have one default
    ensure_one_default_active_cost_book(cur)


def mark_migration_applied(cur):
    cur.execute("INSERT OR IGNORE INTO arya_migrations (name, applied_at) VALUES (?, ?)",
                (MIGRATION_NAME, datetime.utcnow().isoformat(" ")))


def main():
    ap = argparse.ArgumentParser(description="AryaIntel CRM DB migration: add cost books & entries")
    ap.add_argument("--db", default=DEFAULT_DB_PATH, help="Path to app.db (default: %(default)s)")
    args = ap.parse_args()

    conn = sqlite3.connect(args.db)
    conn.execute("PRAGMA foreign_keys=ON;")
    conn.execute("PRAGMA journal_mode=WAL;")
    conn.execute("PRAGMA synchronous=NORMAL;")
    cur = conn.cursor()

    try:
        cur.execute("BEGIN;")

        # Migration bookkeeping
        cur.execute(DDL_MIGRATIONS)

        # Core DDL
        cur.execute(DDL_COST_BOOKS)
        exec_many(cur, DDL_IDX_COST_BOOKS)

        cur.execute(DDL_COST_BOOK_ENTRIES)
        exec_many(cur, DDL_IDX_COST_BOOK_ENTRIES)

        # Seed default cost book (if table empty)
        seed_default_cost_book_if_needed(cur)

        # Enforce exactly one default active cost book
        ensure_one_default_active_cost_book(cur)

        # Record migration applied
        mark_migration_applied(cur)

        conn.commit()
        print(f"[OK] Migration '{MIGRATION_NAME}' applied successfully to {args.db}")

        # Hints for next steps (non-invasive; no data writes)
        cur.execute("SELECT code, name, currency, is_default FROM cost_books ORDER BY id DESC LIMIT 1")
        row = cur.fetchone()
        if row:
            print(f"     Default cost book → code={row[0]}, name={row[1]}, currency={row[2]}, is_default={row[3]}")

    except Exception as e:
        conn.rollback()
        print(f"[ERROR] Migration failed: {e}")
        raise
    finally:
        cur.close()
        conn.close()


if __name__ == "__main__":
    main()
