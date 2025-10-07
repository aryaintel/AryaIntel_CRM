"""
price_terms referans tablosunu OLUSTURUR, seed eder.
price_book_entries.price_term_id kolonu ekler ve eski TEXT price_term'den map'leyip doldurur.
SQLite icin.

Calistirma:
    cd backend
    python scripts/ensure_price_terms_ref.py
"""
from pathlib import Path
import sqlite3

DB_PATH = Path(__file__).resolve().parents[1] / "app.db"

SEED = [
    ("bulk_with_freight", "Bulk with Freight", "Bulk price incl. freight"),
    ("bulk_ex_freight",  "Bulk ex Freight",    "Bulk price excluding freight"),
    ("freight",          "Freight",            "Freight only"),
]

def table_exists(cx, name):
    return cx.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?;", (name,)
    ).fetchone() is not None

def column_exists(cx, table, col):
    return any(r["name"] == col for r in cx.execute(f"PRAGMA table_info({table})"))

def get_term_id_by_code(cx, code):
    r = cx.execute("SELECT id FROM price_terms WHERE code = ?;", (code,)).fetchone()
    return r["id"] if r else None

def ensure_terms(cx: sqlite3.Connection):
    if not table_exists(cx, "price_terms"):
        cx.execute("""
            CREATE TABLE price_terms (
                id INTEGER PRIMARY KEY,
                code TEXT NOT NULL UNIQUE,
                name TEXT NOT NULL,
                description TEXT NULL,
                is_active INTEGER NOT NULL DEFAULT 1,
                sort_order INTEGER NOT NULL DEFAULT 0
            );
        """)
        print("[+] created table price_terms")

    # seed (idempotent)
    for i, (code, name, desc) in enumerate(SEED):
        cx.execute("""
            INSERT INTO price_terms(code, name, description, sort_order)
            SELECT ?, ?, ?, ?
            WHERE NOT EXISTS (SELECT 1 FROM price_terms WHERE code = ?);
        """, (code, name, desc, i, code))
    print("[=] seeded price_terms")

def ensure_fk_on_entries(cx: sqlite3.Connection):
    if not column_exists(cx, "price_book_entries", "price_term_id"):
        cx.execute("ALTER TABLE price_book_entries ADD COLUMN price_term_id INTEGER NULL;")
        print("[+] added price_term_id to price_book_entries")

    # map legacy TEXT column -> FK
    # 1) normalize bilinen stringler
    cx.execute("""
        UPDATE price_book_entries
           SET price_term = LOWER(price_term)
         WHERE price_term IS NOT NULL;
    """)

    # 2) map code -> id
    for code, *_ in SEED:
        term_id = get_term_id_by_code(cx, code)
        cx.execute("""
            UPDATE price_book_entries
               SET price_term_id = ?
             WHERE (price_term = ?)
                OR (price_term_id IS NULL AND price_term IS NULL AND ? = 'bulk_with_freight');
        """, (term_id, code, code))

    # 3) fallback: NULL kalanları default koda çek
    default_id = get_term_id_by_code(cx, "bulk_with_freight")
    cx.execute("""
        UPDATE price_book_entries
           SET price_term_id = ?
         WHERE price_term_id IS NULL;
    """, (default_id,))

    # 4) FK güvenliği (SQLite'ta ALTER TABLE limited; check olarak bırakıyoruz)
    cx.execute("PRAGMA foreign_keys = ON;")
    print("[=] backfilled price_book_entries.price_term_id")

def main():
    print(f"[i] DB: {DB_PATH}")
    cx = sqlite3.connect(str(DB_PATH))
    cx.row_factory = sqlite3.Row
    cx.execute("PRAGMA foreign_keys = ON;")

    ensure_terms(cx)
    ensure_fk_on_entries(cx)
    cx.commit()

    # Özet
    rows = cx.execute("""
        SELECT pt.code, COUNT(*) AS cnt
          FROM price_book_entries e
          LEFT JOIN price_terms pt ON pt.id = e.price_term_id
      GROUP BY pt.code
      ORDER BY cnt DESC;
    """).fetchall()
    print("[✓] distribution:")
    for r in rows:
        print(f"    {r['code']}: {r['cnt']}")

    cx.close()

if __name__ == "__main__":
    main()
