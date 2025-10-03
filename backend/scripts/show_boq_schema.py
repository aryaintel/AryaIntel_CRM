# backend/scripts/show_boq_schema.py
import os
from sqlalchemy import create_engine, inspect, text

# Projede varsayılan olarak SQLite kullanılıyor (backend klasöründe app.db var)
DATABASE_URL = os.getenv("DATABASE_URL", "sqlite:///app.db")

engine = create_engine(DATABASE_URL, future=True)
insp = inspect(engine)

TABLE = "scenario_boq_items"

print(f"DB URL: {DATABASE_URL}")
print(f"\n== Columns for '{TABLE}' ==\n")

if TABLE not in insp.get_table_names():
    raise SystemExit(f"Table '{TABLE}' not found. Available: {insp.get_table_names()}")

cols = insp.get_columns(TABLE)
pks = set(insp.get_pk_constraint(TABLE).get("constrained_columns") or [])

for c in cols:
    name = c["name"]
    typ  = str(c["type"])
    nullable = c.get("nullable", True)
    default = c.get("default")
    is_pk = "PK" if name in pks else ""
    print(f"- {name:20} {typ:20} null={nullable!s:5} default={default} {is_pk}")

# (opsiyonel) enum tipini Postgres'te bilgi şemasından da okuyalım
with engine.connect() as conn:
    try:
        res = conn.execute(text("""
            SELECT t.typname AS enum_name, e.enumlabel AS enum_value
            FROM pg_type t
            JOIN pg_enum e ON t.oid = e.enumtypid
            JOIN pg_catalog.pg_namespace n ON n.oid = t.typnamespace
            WHERE t.typname = 'boq_category'
            ORDER BY e.enumsortorder;
        """))
        rows = res.fetchall()
        if rows:
            print("\n== PostgreSQL ENUM 'boq_category' values ==")
            for r in rows:
                print(f"- {r.enum_value}")
    except Exception:
        # SQLite kullanıyorsak burası doğal olarak çalışmayacak, sorun değil.
        pass

print("\n== First 5 rows ==\n")
with engine.begin() as conn:
    res = conn.execute(text(f"SELECT * FROM {TABLE} LIMIT 5"))
    rows = res.mappings().all()
    if not rows:
        print("(no rows)")
    else:
        for i, r in enumerate(rows, 1):
            print(f"#{i}: {dict(r)}")
