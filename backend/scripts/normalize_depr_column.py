from sqlalchemy import create_engine, text
import os

url = os.environ.get("DATABASE_URL", "sqlite:///app.db")
engine = create_engine(url)

with engine.begin() as conn:
    conn.execute(text(
        "ALTER TABLE scenario_capex RENAME COLUMN depr_method TO depreciation_method"
    ))
    print("Renamed depr_method -> depreciation_method")
