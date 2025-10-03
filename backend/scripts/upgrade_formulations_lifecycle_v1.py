# -*- coding: utf-8 -*-
"""
product_formulations tablosuna arşiv alanları ekler.
- is_archived (INT, default 0)
- archived_at (TEXT)
- parent_formulation_id (INT, self-FK)
Çalıştırma:
    cd backend
    python scripts/upgrade_formulations_lifecycle_v1.py
"""
from pathlib import Path
import sqlite3

DB_PATH = Path(__file__).resolve().parents[1] / "app.db"

def column_names(cx, table):
    return {row[1] for row in cx.execute(f"PRAGMA table_info({table});")}

def main():
    print(f"[i] Using DB = {DB_PATH}")
    cx = sqlite3.connect(str(DB_PATH))
    cx.execute("PRAGMA foreign_keys=ON;")

    cols = column_names(cx, "product_formulations")

    if "is_archived" not in cols:
        print("[+] add column is_archived")
        cx.execute("ALTER TABLE product_formulations "
                   "ADD COLUMN is_archived INTEGER NOT NULL DEFAULT 0;")

    if "archived_at" not in cols:
        print("[+] add column archived_at")
        cx.execute("ALTER TABLE product_formulations "
                   "ADD COLUMN archived_at TEXT NULL;")

    if "parent_formulation_id" not in cols:
        print("[+] add column parent_formulation_id")
        cx.execute("ALTER TABLE product_formulations "
                   "ADD COLUMN parent_formulation_id INTEGER NULL "
                   "REFERENCES product_formulations(id) ON DELETE SET NULL;")

    # index’ler
    cx.execute("""CREATE INDEX IF NOT EXISTS ix_form_is_archived
                  ON product_formulations (is_archived);""")
    cx.execute("""CREATE INDEX IF NOT EXISTS ix_form_parent
                  ON product_formulations (parent_formulation_id);""")

    # backfill (eski kayıtlarda NULL varsa)
    cx.execute("UPDATE product_formulations "
               "SET is_archived = COALESCE(is_archived, 0);")

    cx.commit()
    # özet
    for r in cx.execute("PRAGMA table_info(product_formulations);"):
        print(f"- {r[1]:22} {r[2]}")
    cx.close()
    print("[✓] upgrade_formulations_lifecycle_v1 done.")

if __name__ == "__main__":
    main()
