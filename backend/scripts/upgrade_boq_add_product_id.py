# backend/scripts/upgrade_boq_add_product_id.py
"""
scenario_boq_items tablosuna product_id kolonu ekler.
- Tablo yoksa TAM şemayla oluşturur (product_id dahil).
- Tablo varsa eksik sütunları ADD COLUMN ile ekler.
- Gerekli index'leri oluşturur.

SQLite (app.db) için tasarlanmıştır.

Çalıştırma:
    cd backend
    python scripts/upgrade_boq_add_product_id.py
"""
from pathlib import Path
import sqlite3

DB_PATH = Path(__file__).resolve().parents[1] / "app.db"

DDL_TABLE = """
CREATE TABLE IF NOT EXISTS scenario_boq_items (
    id INTEGER PRIMARY KEY,
    scenario_id INTEGER NOT NULL REFERENCES scenarios(id) ON DELETE CASCADE,

    section TEXT NULL,
    item_name TEXT NOT NULL,
    unit TEXT NOT NULL,

    quantity NUMERIC(18,4) NOT NULL DEFAULT 0,
    unit_price NUMERIC(18,4) NOT NULL DEFAULT 0,
    unit_cogs NUMERIC(18,4) NULL,

    frequency TEXT NOT NULL DEFAULT 'once',
    start_year INTEGER NULL,
    start_month INTEGER NULL,
    months INTEGER NULL,

    formulation_id INTEGER NULL REFERENCES product_formulations(id) ON DELETE SET NULL,
    price_escalation_policy_id INTEGER NULL REFERENCES escalation_policies(id) ON DELETE SET NULL,

    is_active INTEGER NOT NULL DEFAULT 1,
    notes TEXT NULL,

    category TEXT NULL,
    -- product link (yeni)
    product_id INTEGER NULL REFERENCES products(id) ON DELETE SET NULL,

    CONSTRAINT ck_boq_category CHECK (category IN ('bulk_with_freight','bulk_ex_freight','freight'))
);
"""

ADD_COLS_SQL = {
    # Sadece yeni eklememiz gereken alanı tanımlıyoruz.
    # SQLite'ta ALTER TABLE ... ADD COLUMN ifadesinde REFERENCES kullanılabilir.
    "product_id": "ALTER TABLE scenario_boq_items ADD COLUMN product_id INTEGER NULL REFERENCES products(id) ON DELETE SET NULL;",
}

CREATE_INDEXES = {
    "ix_boq_scenario": "CREATE INDEX IF NOT EXISTS ix_boq_scenario ON scenario_boq_items (scenario_id);",
    # İsteğe bağlı: product_id üstünden de arama yapılacaksa faydalı olur
    "ix_boq_product": "CREATE INDEX IF NOT EXISTS ix_boq_product ON scenario_boq_items (product_id);",
}

def table_exists(cx: sqlite3.Connection, name: str) -> bool:
    cur = cx.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name = ?;", (name,)
    )
    return cur.fetchone() is not None

def column_names(cx: sqlite3.Connection, table: str) -> set[str]:
    cols = set()
    for row in cx.execute(f"PRAGMA table_info({table});"):
        # row = (cid, name, type, notnull, dflt_value, pk)
        cols.add(row[1])
    return cols

def ensure_index(cx: sqlite3.Connection, name: str, sql: str) -> None:
    cur = cx.execute(
        "SELECT name FROM sqlite_master WHERE type='index' AND name = ?;", (name,)
    )
    if cur.fetchone() is None:
        cx.execute(sql)

def main() -> None:
    print(f"[i] Using DB = {DB_PATH}")
    cx = sqlite3.connect(str(DB_PATH))
    cx.execute("PRAGMA foreign_keys = ON;")

    if not table_exists(cx, "scenario_boq_items"):
        print("[+] Creating table scenario_boq_items (with product_id)…")
        cx.executescript(DDL_TABLE)
    else:
        print("[=] scenario_boq_items exists. Checking columns…")
        cols = column_names(cx, "scenario_boq_items")
        for col, add_sql in ADD_COLS_SQL.items():
            if col not in cols:
                print(f"[+] Adding column: {col}")
                cx.execute(add_sql)
            else:
                print(f"[=] Column already present: {col}")

    # indexes
    for ix_name, ix_sql in CREATE_INDEXES.items():
        ensure_index(cx, ix_name, ix_sql)

    cx.commit()

    # summary
    print("\n=== scenario_boq_items columns ===")
    for row in cx.execute("PRAGMA table_info(scenario_boq_items);"):
        print(f"- {row[1]:28} | {row[2]:15} | notnull={row[3]} | default={row[4]!r} | pk={row[5]}")

    count = cx.execute("SELECT COUNT(*) FROM scenario_boq_items;").fetchone()[0]
    print(f"\n[✓] scenario_boq_items ready. Row count: {count}")

    # hızlı kontrol: yabancı anahtar desteği açık mı?
    fk_on = cx.execute("PRAGMA foreign_keys;").fetchone()[0]
    print(f"[i] PRAGMA foreign_keys = {fk_on}")

    cx.close()

if __name__ == "__main__":
    main()
