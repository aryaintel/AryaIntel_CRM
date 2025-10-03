# backend/scripts/add_index_point.py
from pathlib import Path
import sqlite3

DB = Path(__file__).resolve().parents[1] / "app.db"
rows = [
    # (series_id, year, month, value)
    (1, 2024, 12, 101.23),
    (2, 2024, 12, 103.75),
]
cx = sqlite3.connect(DB)
cx.execute("PRAGMA foreign_keys=ON;")
for sid, y, m, val in rows:
    cx.execute("""
        INSERT OR REPLACE INTO index_points(series_id, year, month, value, source_ref)
        VALUES (?, ?, ?, ?, 'seed')
    """, (sid, y, m, val))
cx.commit()
cx.close()
print("Inserted index points:", rows)
