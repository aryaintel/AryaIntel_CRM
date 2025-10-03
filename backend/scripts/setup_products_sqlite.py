# backend/scripts/upgrade_products_schema.py
"""
Products şemasını oluşturur/günceller (SQLite/app.db).
- Tablo yoksa TAM şema ile oluşturur.
- Tablo varsa eksik sütunları ADD COLUMN ile ekler.
- FTS5 araması ve tetikleyiciler (products_fts) idempotent kurulur.
- Kategori/Etiket M:N, Media, Price Book & Entries, Audit tabloları oluşturulur.
- --seed ile örnek veri basılır.

Çalıştırma:
    cd backend
    python scripts/upgrade_products_schema.py --seed
    python scripts/upgrade_products_schema.py --drop   # yalnız products şemasını temizler
"""
from __future__ import annotations
from pathlib import Path
import sqlite3
import argparse
import sys
from typing import Iterable

DB_PATH = Path(__file__).resolve().parents[1] / "app.db"

# ---- yardımcılar ------------------------------------------------------------

def table_exists(cx: sqlite3.Connection, name: str) -> bool:
    return cx.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?;", (name,)
    ).fetchone() is not None

def index_exists(cx: sqlite3.Connection, name: str) -> bool:
    return cx.execute(
        "SELECT 1 FROM sqlite_master WHERE type='index' AND name=?;", (name,)
    ).fetchone() is not None

def trigger_exists(cx: sqlite3.Connection, name: str) -> bool:
    return cx.execute(
        "SELECT 1 FROM sqlite_master WHERE type='trigger' AND name=?;", (name,)
    ).fetchone() is not None

def column_names(cx: sqlite3.Connection, table: str) -> set[str]:
    return {row[1] for row in cx.execute(f"PRAGMA table_info({table});").fetchall()}

def ensure_index(cx: sqlite3.Connection, name: str, sql: str) -> None:
    if not index_exists(cx, name):
        cx.execute(sql)

def ensure_trigger(cx: sqlite3.Connection, name: str, sql: str) -> None:
    if not trigger_exists(cx, name):
        cx.executescript(sql)

# ---- ana tablolar -----------------------------------------------------------

PRODUCTS_CREATE = """
CREATE TABLE IF NOT EXISTS products (
  id             INTEGER PRIMARY KEY AUTOINCREMENT,
  code           TEXT    NOT NULL UNIQUE,
  name           TEXT    NOT NULL,
  description    TEXT,
  uom            TEXT,
  currency       TEXT    DEFAULT 'USD',
  base_price     NUMERIC DEFAULT 0,
  tax_rate_pct   NUMERIC,
  barcode_gtin   TEXT,
  is_active      INTEGER NOT NULL DEFAULT 1,  -- 1:true, 0:false
  metadata       TEXT,
  created_at     TEXT NOT NULL DEFAULT (datetime('now')),
  updated_at     TEXT NOT NULL DEFAULT (datetime('now')),
  deleted_at     TEXT
);
"""

PRODUCTS_ADD_COL = {
    "code":         "ALTER TABLE products ADD COLUMN code TEXT;",
    "name":         "ALTER TABLE products ADD COLUMN name TEXT;",
    "description":  "ALTER TABLE products ADD COLUMN description TEXT;",
    "uom":          "ALTER TABLE products ADD COLUMN uom TEXT;",
    "currency":     "ALTER TABLE products ADD COLUMN currency TEXT DEFAULT 'USD';",
    "base_price":   "ALTER TABLE products ADD COLUMN base_price NUMERIC DEFAULT 0;",
    "tax_rate_pct": "ALTER TABLE products ADD COLUMN tax_rate_pct NUMERIC;",
    "barcode_gtin": "ALTER TABLE products ADD COLUMN barcode_gtin TEXT;",
    "is_active":    "ALTER TABLE products ADD COLUMN is_active INTEGER NOT NULL DEFAULT 1;",
    "metadata":     "ALTER TABLE products ADD COLUMN metadata TEXT;",
    "created_at":   "ALTER TABLE products ADD COLUMN created_at TEXT NOT NULL DEFAULT (datetime('now'));",
    "updated_at":   "ALTER TABLE products ADD COLUMN updated_at TEXT NOT NULL DEFAULT (datetime('now'));",
    "deleted_at":   "ALTER TABLE products ADD COLUMN deleted_at TEXT;",
}

PRODUCTS_UPDATED_TRG = """
CREATE TRIGGER IF NOT EXISTS trg_products_updated
AFTER UPDATE ON products
BEGIN
  UPDATE products SET updated_at = datetime('now') WHERE id = OLD.id;
END;
"""

# ---- FTS5 -------------------------------------------------------------------

FTS_CREATE = """
CREATE VIRTUAL TABLE IF NOT EXISTS products_fts
USING fts5(code, name, description, content='products', content_rowid='id');
"""

FTS_TRIGGERS = """
CREATE TRIGGER IF NOT EXISTS trg_products_ai
AFTER INSERT ON products BEGIN
  INSERT INTO products_fts(rowid, code, name, description)
  VALUES (new.id, new.code, new.name, COALESCE(new.description,''));
END;

CREATE TRIGGER IF NOT EXISTS trg_products_ad
AFTER DELETE ON products BEGIN
  INSERT INTO products_fts(products_fts, rowid, code, name, description)
  VALUES ('delete', old.id, old.code, old.name, COALESCE(old.description,''));
END;

CREATE TRIGGER IF NOT EXISTS trg_products_au
AFTER UPDATE ON products BEGIN
  INSERT INTO products_fts(products_fts, rowid, code, name, description)
  VALUES ('delete', old.id, old.code, old.name, COALESCE(old.description,''));
  INSERT INTO products_fts(rowid, code, name, description)
  VALUES (new.id, new.code, new.name, COALESCE(new.description,''));
END;
"""

# ---- Category, Tag M:N ------------------------------------------------------

CATEGORIES_CREATE = """
CREATE TABLE IF NOT EXISTS product_categories (
  id         INTEGER PRIMARY KEY AUTOINCREMENT,
  code       TEXT NOT NULL UNIQUE,
  name       TEXT NOT NULL,
  parent_id  INTEGER REFERENCES product_categories(id) ON DELETE SET NULL,
  created_at TEXT NOT NULL DEFAULT (datetime('now')),
  updated_at TEXT NOT NULL DEFAULT (datetime('now'))
);
"""

CATEGORIES_TRG = """
CREATE TRIGGER IF NOT EXISTS trg_prodcat_updated
AFTER UPDATE ON product_categories
BEGIN
  UPDATE product_categories SET updated_at = datetime('now') WHERE id = OLD.id;
END;
"""

CAT_LINKS_CREATE = """
CREATE TABLE IF NOT EXISTS product_category_links (
  product_id  INTEGER NOT NULL REFERENCES products(id) ON DELETE CASCADE,
  category_id INTEGER NOT NULL REFERENCES product_categories(id) ON DELETE CASCADE,
  PRIMARY KEY (product_id, category_id)
);
"""

TAGS_CREATE = """
CREATE TABLE IF NOT EXISTS product_tags (
  id   INTEGER PRIMARY KEY AUTOINCREMENT,
  tag  TEXT NOT NULL UNIQUE
);
"""

TAG_LINKS_CREATE = """
CREATE TABLE IF NOT EXISTS product_tag_links (
  product_id INTEGER NOT NULL REFERENCES products(id) ON DELETE CASCADE,
  tag_id     INTEGER NOT NULL REFERENCES product_tags(id) ON DELETE CASCADE,
  PRIMARY KEY (product_id, tag_id)
);
"""

# ---- Attributes -------------------------------------------------------------

ATTR_CREATE = """
CREATE TABLE IF NOT EXISTS product_attributes (
  id            INTEGER PRIMARY KEY AUTOINCREMENT,
  product_id    INTEGER NOT NULL REFERENCES products(id) ON DELETE CASCADE,
  key           TEXT NOT NULL,
  value_raw     TEXT,
  type          TEXT NOT NULL DEFAULT 'string' CHECK (type IN ('string','number','boolean','json')),
  lang          TEXT,
  country       TEXT,
  channel       TEXT,
  customer_seg  TEXT,
  valid_from    TEXT,
  valid_to      TEXT,
  created_at    TEXT NOT NULL DEFAULT (datetime('now')),
  updated_at    TEXT NOT NULL DEFAULT (datetime('now')),
  -- UNIQUE: ifade kullanmadan düz kombinasyon
  UNIQUE (product_id, key, lang, country, channel, customer_seg, valid_from, valid_to)
);
"""

ATTR_TRG = """
CREATE TRIGGER IF NOT EXISTS trg_prodattributes_updated
AFTER UPDATE ON product_attributes
BEGIN
  UPDATE product_attributes SET updated_at = datetime('now') WHERE id = OLD.id;
END;
"""

# ---- Media ------------------------------------------------------------------

MEDIA_CREATE = """
CREATE TABLE IF NOT EXISTS product_media (
  id          INTEGER PRIMARY KEY AUTOINCREMENT,
  product_id  INTEGER NOT NULL REFERENCES products(id) ON DELETE CASCADE,
  kind        TEXT NOT NULL,
  url         TEXT NOT NULL,
  title       TEXT,
  sort_order  INTEGER DEFAULT 0,
  created_at  TEXT NOT NULL DEFAULT (datetime('now'))
);
"""

# ---- Price Books ------------------------------------------------------------

PRICE_BOOKS_CREATE = """
CREATE TABLE IF NOT EXISTS price_books (
  id          INTEGER PRIMARY KEY AUTOINCREMENT,
  code        TEXT NOT NULL UNIQUE,
  name        TEXT NOT NULL,
  currency    TEXT NOT NULL DEFAULT 'USD',
  is_default  INTEGER NOT NULL DEFAULT 0,
  is_active   INTEGER NOT NULL DEFAULT 1,
  created_at  TEXT NOT NULL DEFAULT (datetime('now')),
  updated_at  TEXT NOT NULL DEFAULT (datetime('now'))
);
"""

PRICE_BOOKS_TRG = """
CREATE TRIGGER IF NOT EXISTS trg_price_books_updated
AFTER UPDATE ON price_books
BEGIN
  UPDATE price_books SET updated_at = datetime('now') WHERE id = OLD.id;
END;
"""

PBE_CREATE = """
CREATE TABLE IF NOT EXISTS price_book_entries (
  id             INTEGER PRIMARY KEY AUTOINCREMENT,
  price_book_id  INTEGER NOT NULL REFERENCES price_books(id) ON DELETE CASCADE,
  product_id     INTEGER NOT NULL REFERENCES products(id) ON DELETE CASCADE,
  currency       TEXT NOT NULL,
  list_price     NUMERIC NOT NULL,
  discount_type  TEXT,
  discount_value NUMERIC,
  min_qty        NUMERIC,
  max_qty        NUMERIC,
  valid_from     TEXT,
  valid_to       TEXT,
  is_active      INTEGER NOT NULL DEFAULT 1,
  metadata       TEXT,
  created_at     TEXT NOT NULL DEFAULT (datetime('now')),
  updated_at     TEXT NOT NULL DEFAULT (datetime('now')),
  -- UNIQUE: ifadeler olmadan sade bir kombinasyon
  UNIQUE (price_book_id, product_id, currency, valid_from, valid_to, min_qty, max_qty)
);
"""

PBE_TRG = """
CREATE TRIGGER IF NOT EXISTS trg_pbe_updated
AFTER UPDATE ON price_book_entries
BEGIN
  UPDATE price_book_entries SET updated_at = datetime('now') WHERE id = OLD.id;
END;
"""

# ---- Audit ------------------------------------------------------------------

AUDIT_CREATE = """
CREATE TABLE IF NOT EXISTS product_audit (
  id           INTEGER PRIMARY KEY AUTOINCREMENT,
  product_id   INTEGER NOT NULL REFERENCES products(id) ON DELETE CASCADE,
  action       TEXT NOT NULL,           -- insert|update|delete|restore
  actor        TEXT,
  changes      TEXT NOT NULL,
  created_at   TEXT NOT NULL DEFAULT (datetime('now'))
);
"""

# ---- Drop (yalnız products şeması) -----------------------------------------

DROP_SQL = """
PRAGMA foreign_keys = OFF;

DROP TRIGGER IF EXISTS trg_pbe_updated;
DROP TABLE   IF EXISTS price_book_entries;
DROP TRIGGER IF EXISTS trg_price_books_updated;
DROP TABLE   IF EXISTS price_books;

DROP TABLE   IF EXISTS product_media;

DROP TRIGGER IF EXISTS trg_prodattributes_updated;
DROP TABLE   IF EXISTS product_attributes;

DROP TABLE   IF EXISTS product_tag_links;
DROP TABLE   IF EXISTS product_tags;

DROP TABLE   IF EXISTS product_category_links;
DROP TRIGGER IF EXISTS trg_prodcat_updated;
DROP TABLE   IF EXISTS product_categories;

DROP TABLE   IF EXISTS product_audit;

DROP TRIGGER IF EXISTS trg_products_au;
DROP TRIGGER IF EXISTS trg_products_ad;
DROP TRIGGER IF EXISTS trg_products_ai;
DROP TABLE   IF EXISTS products_fts;

DROP TRIGGER IF EXISTS trg_products_updated;
DROP TABLE   IF EXISTS products;

PRAGMA foreign_keys = ON;
"""

# ---- Seed -------------------------------------------------------------------

SEED_SQL = """
INSERT OR IGNORE INTO price_books(code, name, currency, is_default, is_active)
VALUES ('STANDARD', 'Standard Price Book', 'USD', 1, 1);

INSERT OR IGNORE INTO products(code, name, description, uom, currency, base_price, tax_rate_pct, is_active)
VALUES
  ('P-100', 'Generic Service A', 'Base service', 'EA', 'USD', 100.00, 18.0, 1),
  ('P-200', 'Material X',       'Raw material X', 'KG', 'USD',  12.50, 18.0, 1),
  ('P-300', 'Material Y',       'Raw material Y', 'KG', 'EUR',  14.75, 18.0, 1);

INSERT OR IGNORE INTO price_book_entries(price_book_id, product_id, currency, list_price)
SELECT pb.id, p.id, p.currency, p.base_price
FROM price_books pb
JOIN products p
WHERE pb.code='STANDARD';
"""

# ---- Kurulum/güncelleme adımları -------------------------------------------

def ensure_products(cx: sqlite3.Connection) -> None:
    if not table_exists(cx, "products"):
        print("[+] Creating products…")
        cx.executescript(PRODUCTS_CREATE)
    else:
        print("[=] products exists. Checking columns…")
        cols = column_names(cx, "products")
        for col, sql in PRODUCTS_ADD_COL.items():
            if col not in cols:
                print(f"[+] Adding products.{col}")
                cx.execute(sql)
    ensure_index(cx, "idx_products_active",  "CREATE INDEX idx_products_active ON products(is_active);")
    ensure_index(cx, "idx_products_deleted", "CREATE INDEX idx_products_deleted ON products(deleted_at);")
    ensure_index(cx, "idx_products_currency","CREATE INDEX idx_products_currency ON products(currency);")
    ensure_trigger(cx, "trg_products_updated", PRODUCTS_UPDATED_TRG)

def ensure_fts(cx: sqlite3.Connection) -> None:
    print("[=] Ensuring FTS5…")
    cx.executescript(FTS_CREATE)
    cx.executescript(FTS_TRIGGERS)

def ensure_categories_tags(cx: sqlite3.Connection) -> None:
    if not table_exists(cx, "product_categories"):
        print("[+] Creating product_categories…")
        cx.executescript(CATEGORIES_CREATE)
    ensure_trigger(cx, "trg_prodcat_updated", CATEGORIES_TRG)

    if not table_exists(cx, "product_category_links"):
        print("[+] Creating product_category_links…")
        cx.executescript(CAT_LINKS_CREATE)

    if not table_exists(cx, "product_tags"):
        print("[+] Creating product_tags…")
        cx.executescript(TAGS_CREATE)

    if not table_exists(cx, "product_tag_links"):
        print("[+] Creating product_tag_links…")
        cx.executescript(TAG_LINKS_CREATE)

def ensure_attributes_media(cx: sqlite3.Connection) -> None:
    if not table_exists(cx, "product_attributes"):
        print("[+] Creating product_attributes…")
        cx.executescript(ATTR_CREATE)
    ensure_trigger(cx, "trg_prodattributes_updated", ATTR_TRG)

    if not table_exists(cx, "product_media"):
        print("[+] Creating product_media…")
        cx.executescript(MEDIA_CREATE)
    ensure_index(cx, "idx_prod_media_product", "CREATE INDEX idx_prod_media_product ON product_media(product_id);")

def ensure_price_books(cx: sqlite3.Connection) -> None:
    if not table_exists(cx, "price_books"):
        print("[+] Creating price_books…")
        cx.executescript(PRICE_BOOKS_CREATE)
    ensure_trigger(cx, "trg_price_books_updated", PRICE_BOOKS_TRG)

    if not table_exists(cx, "price_book_entries"):
        print("[+] Creating price_book_entries…")
        cx.executescript(PBE_CREATE)
    ensure_trigger(cx, "trg_pbe_updated", PBE_TRG)
    ensure_index(cx, "idx_pbe_book_prod", "CREATE INDEX idx_pbe_book_prod ON price_book_entries(price_book_id, product_id);")
    ensure_index(cx, "idx_pbe_validity",  "CREATE INDEX idx_pbe_validity  ON price_book_entries(valid_from, valid_to);")

def ensure_audit(cx: sqlite3.Connection) -> None:
    if not table_exists(cx, "product_audit"):
        print("[+] Creating product_audit…")
        cx.executescript(AUDIT_CREATE)
    ensure_index(cx, "idx_prod_audit_product", "CREATE INDEX idx_prod_audit_product ON product_audit(product_id);")

# ---- main -------------------------------------------------------------------

def drop_products_schema(cx: sqlite3.Connection) -> None:
    print("[!] Dropping products schema…")
    cx.executescript(DROP_SQL)

def print_summary(cx: sqlite3.Connection) -> None:
    print("\n=== products columns ===")
    for row in cx.execute("PRAGMA table_info(products);"):
        print(f"- {row[1]:12} | {row[2]:10} | notnull={row[3]} | default={row[4]!r} | pk={row[5]}")
    cnt = cx.execute("SELECT COUNT(*) FROM products;").fetchone()[0]
    print(f"[✓] products ready. Row count: {cnt}")

def main():
    ap = argparse.ArgumentParser(description="Upgrade Products schema (SQLite)")
    ap.add_argument("--db", type=Path, default=DB_PATH, help=f"DB path (default: {DB_PATH})")
    ap.add_argument("--seed", action="store_true", help="Örnek veri yükle")
    ap.add_argument("--drop", action="store_true", help="Sadece products şemasını temizle")
    args = ap.parse_args()

    print(f"[i] Using DB = {args.db}")
    cx = sqlite3.connect(str(args.db))
    cx.execute("PRAGMA foreign_keys = ON;")

    try:
        if args.drop:
            drop_products_schema(cx)
            cx.commit()
            print("[✓] Dropped.")
            return

        ensure_products(cx)
        ensure_fts(cx)
        ensure_categories_tags(cx)
        ensure_attributes_media(cx)
        ensure_price_books(cx)
        ensure_audit(cx)

        if args.seed:
            print("[+] Seeding sample data…")
            cx.executescript(SEED_SQL)

        cx.commit()
        print_summary(cx)
    except Exception as e:
        cx.rollback()
        print(f"[ERROR] {e}", file=sys.stderr)
        raise
    finally:
        cx.close()

if __name__ == "__main__":
    main()
