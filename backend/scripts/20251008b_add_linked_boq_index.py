# backend/scripts/migrations/20251008b_add_linked_boq_index.py
import argparse
from sqlalchemy import create_engine, text

SQL_STMTS = [
    # SQLite: create index if not exists (supported)
    "CREATE INDEX IF NOT EXISTS idx_scenario_capex_linked_boq ON scenario_capex(linked_boq_item_id);",
]

def run(db_url: str):
    engine = create_engine(db_url)
    with engine.begin() as conn:
        for stmt in SQL_STMTS:
            conn.execute(text(stmt))
    print("[done] idx_scenario_capex_linked_boq ensured.")

if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("--db", required=True, help="SQLAlchemy DB URL, e.g. sqlite:///C:/Dev/AryaIntel_CRM/app.db")
    args = p.parse_args()
    run(args.db)
