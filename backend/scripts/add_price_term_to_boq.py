# tools/migrations/add_price_term_to_boq.py
import sqlite3, os, sys
DB = os.getenv("APP_DB_PATH", os.path.join(os.path.dirname(__file__), "..", "..", "app.db"))
cx = sqlite3.connect(DB)
cx.execute("PRAGMA foreign_keys=OFF;")
cols = [r[1] for r in cx.execute("PRAGMA table_info(scenario_boq_items)")]
if "price_term" not in cols:
    cx.execute("ALTER TABLE scenario_boq_items ADD COLUMN price_term TEXT NULL;")
cx.commit()
print("OK: price_term column present.")
