# backend/scripts/show_capex_schema.py
"""
CAPEX tablosunun (scenario_capex) varlığını ve şemasını gösterir,
örnek satırları listeler.

Çalıştırma:
    cd backend
    python scripts/show_capex_schema.py
İsteğe bağlı:
    DATABASE_URL env değişkeni ayarlanmışsa onu kullanır.
"""
import os
from sqlalchemy import create_engine, text
from sqlalchemy.engine import Engine
from sqlalchemy import inspect

DB_URL = os.environ.get("DATABASE_URL", "sqlite:///app.db")


def connect() -> Engine:
    print(f"[i] Using DB_URL = {DB_URL}")
    return create_engine(DB_URL, future=True)


def main() -> None:
    eng = connect()
    insp = inspect(eng)

    print("\n=== TABLES ===")
    try:
        tables = insp.get_table_names()
        print(", ".join(tables) or "(no tables)")
    except Exception as e:
        print(f"!! tablolar okunamadı: {e}")
        return

    if "scenario_capex" not in insp.get_table_names():
        print("\n[!] 'scenario_capex' tablosu bulunamadı.")
        return

    print("\n=== scenario_capex COLUMNS ===")
    for col in insp.get_columns("scenario_capex"):
        name = col.get("name")
        t = col.get("type")
        nullable = col.get("nullable")
        default = col.get("default")
        print(f"- {name:12} | {t!s:18} | nullable={nullable} | default={default}")

    print("\n=== INDEXES ===")
    for idx in insp.get_indexes("scenario_capex"):
        print(f"- {idx.get('name')} -> columns={idx.get('column_names')} unique={idx.get('unique')}")

    print("\n=== FOREIGN KEYS ===")
    for fk in insp.get_foreign_keys("scenario_capex"):
        print(f"- {fk.get('name')} -> {fk.get('constrained_columns')} -> {fk.get('referred_table')}({fk.get('referred_columns')})")

    with eng.connect() as cx:
        print("\n=== ROW COUNT ===")
        count = cx.execute(text("SELECT COUNT(*) FROM scenario_capex")).scalar_one()
        print(count)

        print("\n=== SAMPLE ROWS (up to 10) ===")
        rows = cx.execute(
            text(
                "SELECT id, scenario_id, year, month, amount, COALESCE(notes,'') AS notes "
                "FROM scenario_capex ORDER BY year, month, id LIMIT 10"
            )
        ).mappings().all()
        if not rows:
            print("(no rows)")
        else:
            for r in rows:
                print(dict(r))


if __name__ == "__main__":
    main()
