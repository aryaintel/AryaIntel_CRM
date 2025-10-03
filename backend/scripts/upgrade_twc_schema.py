# backend/scripts/upgrade_twc_schema.py
"""
scenario_twc tablosunu i.WC (TWC) ihtiyaçlarına göre oluşturur/günceller.
- Tablo yoksa TAM şema ile oluşturur.
- Tablo varsa eksik sütunları ADD COLUMN ile ekler.
- Mevcut tüm scenarios için (yoksa) varsayılan TWC kayıtlarını seed eder.
SQLite (app.db) için tasarlanmıştır.

Çalıştırma:
    cd backend
    python scripts/upgrade_twc_schema.py
"""
from pathlib import Path
import sqlite3
import sys

DB_PATH = Path(__file__).resolve().parents[1] / "app.db"

DDL_TABLE = """
CREATE TABLE IF NOT EXISTS scenario_twc (
    id INTEGER PRIMARY KEY,
    scenario_id INTEGER NOT NULL REFERENCES scenarios(id) ON DELETE CASCADE,
    dso_days INTEGER NOT NULL DEFAULT 45,
    dpo_days INTEGER NOT NULL DEFAULT 30,
    inventory_days INTEGER NULL,
    notes TEXT NULL,

    CONSTRAINT uq_twc_scenario UNIQUE (scenario_id),
    CONSTRAINT ck_twc_dso CHECK (dso_days >= 0 AND dso_days <= 365),
    CONSTRAINT ck_twc_dpo CHECK (dpo_days >= 0 AND dpo_days <= 365),
    CONSTRAINT ck_twc_inv CHECK (inventory_days IS NULL OR (inventory_days >= 0 AND inventory_days <= 365))
);
"""

ADD_COLS_SQL = {
    "dso_days": "ALTER TABLE scenario_twc ADD COLUMN dso_days INTEGER NOT NULL DEFAULT 45;",
    "dpo_days": "ALTER TABLE scenario_twc ADD COLUMN dpo_days INTEGER NOT NULL DEFAULT 30;",
    "inventory_days": "ALTER TABLE scenario_twc ADD COLUMN inventory_days INTEGER NULL;",
    "notes": "ALTER TABLE scenario_twc ADD COLUMN notes TEXT NULL;",
}

BACKFILL_SQL = [
    "UPDATE scenario_twc SET dso_days = COALESCE(dso_days, 45);",
    "UPDATE scenario_twc SET dpo_days = COALESCE(dpo_days, 30);",
]

def table_exists(cx: sqlite3.Connection, name: str) -> bool:
    cur = cx.execute("SELECT name FROM sqlite_master WHERE type='table' AND name = ?;", (name,))
    return cur.fetchone() is not None

def column_names(cx: sqlite3.Connection, table: str) -> set[str]:
    return {row[1] for row in cx.execute(f"PRAGMA table_info({table});")}

def ensure_index(cx: sqlite3.Connection, name: str, sql: str) -> None:
    cur = cx.execute("SELECT name FROM sqlite_master WHERE type='index' AND name = ?;", (name,))
    if cur.fetchone() is None:
        cx.execute(sql)

def ensure_unique_per_scenario(cx: sqlite3.Connection) -> None:
    # UNIQUE constraint zaten var; ayrıca unique index ile destekleyelim (idempotent).
    ensure_index(
        cx,
        "uqx_twc_scenario",
        "CREATE UNIQUE INDEX IF NOT EXISTS uqx_twc_scenario ON scenario_twc (scenario_id);",
    )

def seed_defaults(cx: sqlite3.Connection) -> int:
    created = 0
    scenario_ids = [row[0] for row in cx.execute("SELECT id FROM scenarios;").fetchall()]
    for sid in scenario_ids:
        exists = cx.execute("SELECT 1 FROM scenario_twc WHERE scenario_id = ?;", (sid,)).fetchone()
        if exists:
            continue
        cx.execute(
            """
            INSERT INTO scenario_twc (scenario_id, dso_days, dpo_days, inventory_days, notes)
            VALUES (?, 45, 30, NULL, 'Seeded by upgrade_twc_schema.py');
            """,
            (sid,),
        )
        created += 1
    return created

def main() -> None:
    print(f"[i] Using DB = {DB_PATH}")
    cx = sqlite3.connect(str(DB_PATH))
    cx.execute("PRAGMA foreign_keys = ON;")

    # Önkoşul: scenarios tablosu var mı?
    if not table_exists(cx, "scenarios"):
        print("[!] 'scenarios' tablosu bulunamadı. Önce ana şemayı/migrasyonları çalıştırın.")
        cx.close()
        sys.exit(1)

    if not table_exists(cx, "scenario_twc"):
        print("[+] Creating table scenario_twc (TWC schema)…")
        cx.executescript(DDL_TABLE)
    else:
        print("[=] scenario_twc exists. Checking columns…")
        cols = column_names(cx, "scenario_twc")
        for col, add_sql in ADD_COLS_SQL.items():
            if col not in cols:
                print(f"[+] Adding column: {col}")
                cx.execute(add_sql)
            else:
                print(f"[=] Column already present: {col}")

    ensure_unique_per_scenario(cx)

    for sql in BACKFILL_SQL:
        cx.execute(sql)

    created = seed_defaults(cx)
    cx.commit()

    print("\n=== scenario_twc columns ===")
    for row in cx.execute("PRAGMA table_info(scenario_twc);"):
        print(f"- {row[1]:15} | {row[2]:10} | notnull={row[3]} | default={row[4]!r} | pk={row[5]}")

    count = cx.execute("SELECT COUNT(*) FROM scenario_twc;").fetchone()[0]
    print(f"\n[✓] scenario_twc ready. Row count: {count} (seeded: {created})")
    cx.close()

if __name__ == "__main__":
    main()
