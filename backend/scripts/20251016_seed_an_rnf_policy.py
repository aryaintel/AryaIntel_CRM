# backend/scripts/20251016_seed_an_rnf_policy.py
"""
Seed script: AN Rise & Fall basket (Ammonia 45% + CPI Perth 55%)

Resilient to compounding CHECK variants:
- Reads table DDL and extracts allowed literals for `compounding` via a broad regex.
- If DDL parse fails, it brute-force validates candidates using SAVEPOINTs
  so the DB state is not mutated during probing.

Run:
  cd backend
  python scripts/20251016_seed_an_rnf_policy.py --scenario 1
  # optional:
  #   --db "sqlite:///C:/Dev/AryaIntel_CRM/backend/app.db"
  #   --start-year 2023 --end-year 2027 --month 1
"""

from __future__ import annotations
import argparse
import re
from pathlib import Path
from typing import Optional, Sequence

from sqlalchemy import create_engine, text
from sqlalchemy.exc import IntegrityError

# ---- Excel parity constants (AN) ----
AMMONIA_CODE = "AMMONIA_SPOT_USD"
AMMONIA_NAME = "Ammonia Spot (USD/t)"
CPI_CODE = "CPI_PERTH"
CPI_NAME = "CPI Perth (Index)"

POLICY_NAME = "AN Rise & Fall (Ammonia 45% + CPI Perth 55%)"
POLICY_SCOPE = "basket"          # 'rate'|'index'|'basket'
POLICY_FREQ = "annual"           # 'monthly'|'quarterly'|'annual'
# compounding value will be detected

DEFAULT_START_YEAR = 2023
DEFAULT_END_YEAR = 2027
DEFAULT_MONTH = 1


def default_db_url() -> str:
    backend_dir = Path(__file__).resolve().parents[1]
    db_path = (backend_dir / "app.db").as_posix()
    return f"sqlite:///{db_path}"


# ---------- DDL helpers ----------
def _fetch_table_sql(conn, table: str) -> str | None:
    row = conn.execute(
        text("SELECT sql FROM sqlite_master WHERE type='table' AND name = :t"),
        {"t": table},
    ).fetchone()
    return None if not row else row[0]


def _parse_compounding_in_list(ddl: str) -> Sequence[str]:
    """
    Extract allowed literals for `compounding` from DDL regardless of constraint name.
    Looks for "... compounding ... IN ('a','b','c') ..."
    """
    if not ddl:
        return []
    pat = re.compile(
        r"compounding\s*(?:\w+|\([^)]*\))?\s*IN\s*\((?P<inside>[^)]*)\)",
        re.IGNORECASE | re.DOTALL,
    )
    m = pat.search(ddl)
    if not m:
        return []
    inside = m.group("inside")
    vals = []
    for part in inside.split(","):
        s = part.strip().strip("'").strip('"').strip()
        if s:
            vals.append(s)
    return vals


def _probe_compounding_literal(conn, policy_id: int, candidates: Sequence[str]) -> str:
    """
    Safely try candidates via SAVEPOINT + UPDATE to see which one passes CHECK.
    DB state is rolled back after each attempt; returns first passing candidate.
    """
    for c in candidates:
        try:
            conn.exec_driver_sql("SAVEPOINT sp_comp")
            conn.execute(
                text("""
                    UPDATE escalation_policies
                       SET compounding = :c
                     WHERE id = :pid
                """),
                {"c": c, "pid": policy_id},
            )
            # If no IntegrityError, candidate is valid.
            conn.exec_driver_sql("ROLLBACK TO sp_comp")
            conn.exec_driver_sql("RELEASE sp_comp")
            return c
        except IntegrityError:
            conn.exec_driver_sql("ROLLBACK TO sp_comp")
            conn.exec_driver_sql("RELEASE sp_comp")
            continue
    # If none passed, fall back to 'none' (will still fail, but explicit)
    return "none"


# ---------- CRUD helpers ----------
def get_or_create_index_series(conn, code: str, name: str) -> int:
    row = conn.execute(text("SELECT id FROM index_series WHERE code=:c"), {"c": code}).fetchone()
    if row:
        return int(row[0])
    conn.execute(text("INSERT INTO index_series (code, name) VALUES (:c,:n)"), {"c": code, "n": name})
    row = conn.execute(text("SELECT id FROM index_series WHERE code=:c"), {"c": code}).fetchone()
    return int(row[0])


def upsert_index_point(conn, series_id: int, year: int, month: int, value: float) -> None:
    conn.execute(
        text("""
            INSERT INTO index_points (series_id, year, month, value)
            VALUES (:sid,:y,:m,:v)
            ON CONFLICT(series_id,year,month)
            DO UPDATE SET value=excluded.value
        """),
        {"sid": series_id, "y": year, "m": month, "v": value},
    )


def _existing_policy_id(conn, name: str) -> int | None:
    row = conn.execute(
        text("SELECT id FROM escalation_policies WHERE name=:n AND scope=:s"),
        {"n": name, "s": POLICY_SCOPE},
    ).fetchone()
    return None if not row else int(row[0])


def insert_policy_stub(conn, name: str, start_year: int, start_month: int, frequency: str, compounding: str) -> int:
    conn.execute(
        text("""
            INSERT INTO escalation_policies
                (name, scope, rate_pct, index_series_id, start_year, start_month,
                 cap_pct, floor_pct, frequency, compounding)
            VALUES (:n, :s, NULL, NULL, :y, :m, NULL, NULL, :f, :c)
        """),
        {"n": name, "s": POLICY_SCOPE, "y": start_year, "m": start_month, "f": frequency, "c": compounding},
    )
    row = conn.execute(
        text("SELECT id FROM escalation_policies WHERE name=:n AND scope=:s"),
        {"n": name, "s": POLICY_SCOPE},
    ).fetchone()
    return int(row[0])


def update_policy_core(conn, policy_id: int, start_year: int, start_month: int, frequency: str, compounding: str) -> None:
    conn.execute(
        text("""
            UPDATE escalation_policies
               SET start_year=:y,
                   start_month=:m,
                   frequency=:f,
                   compounding=:c
             WHERE id=:pid
        """),
        {"y": start_year, "m": start_month, "f": frequency, "c": compounding, "pid": policy_id},
    )


def replace_policy_components(conn, policy_id: int, ammon_id: int, cpi_id: int) -> None:
    conn.execute(text("DELETE FROM escalation_policy_components WHERE policy_id=:pid"), {"pid": policy_id})
    conn.execute(
        text("INSERT INTO escalation_policy_components (policy_id,index_series_id,weight_pct) VALUES (:p,:s,:w)"),
        {"p": policy_id, "s": ammon_id, "w": 45.0},
    )
    conn.execute(
        text("INSERT INTO escalation_policy_components (policy_id,index_series_id,weight_pct) VALUES (:p,:s,:w)"),
        {"p": policy_id, "s": cpi_id, "w": 55.0},
    )


def set_scenario_default_policy(conn, scenario_id: int, policy_id: int) -> None:
    conn.execute(
        text("UPDATE scenarios SET default_price_escalation_policy_id=:pid WHERE id=:sid"),
        {"pid": policy_id, "sid": scenario_id},
    )


# ---------- Main ----------
def main(db_url: str, scenario_id: Optional[int], start_year: int, end_year: int, month: int) -> None:
    engine = create_engine(db_url, future=True)

    print("[*] Seeding index series…")
    with engine.begin() as conn:
        ammon_id = get_or_create_index_series(conn, AMMONIA_CODE, AMMONIA_NAME)
        cpi_id = get_or_create_index_series(conn, CPI_CODE, CPI_NAME)
    print(f"[ok] index_series: {AMMONIA_CODE} id={ammon_id}, {CPI_CODE} id={cpi_id}")

    print("[*] Seeding index points…")
    with engine.begin() as conn:
        for y in range(start_year, end_year + 1):
            upsert_index_point(conn, ammon_id, y, month, 100.0)
            upsert_index_point(conn, cpi_id, y, month, 100.0)
    print(f"[ok] index_points upserted for {start_year}..{end_year} (month={month:02d})")

    print("[*] Seeding escalation policy (basket)…")
    with engine.begin() as conn:
        # 1) Try to get allowed literals from DDL
        ddl = _fetch_table_sql(conn, "escalation_policies") or ""
        allowed = list(_parse_compounding_in_list(ddl))
        # Fallback candidate list if DDL parse failed or empty
        if not allowed:
            allowed = ["none", "no", "flat", "n", "off", "nil", "simple", "compound"]

        policy_id = _existing_policy_id(conn, POLICY_NAME)
        if policy_id is None:
            # Insert stub with a provisional compounding that hopefully passes; if not, brute-force.
            provisional = allowed[0]
            try:
                policy_id = insert_policy_stub(conn, POLICY_NAME, start_year, month, POLICY_FREQ, provisional)
            except IntegrityError:
                # We need a legal value → brute force by inserting with a guaranteed passing value
                # Create a temporary stub with 'simple' (often allowed), else brute-force
                for cand in allowed:
                    try:
                        policy_id = insert_policy_stub(conn, POLICY_NAME, start_year, month, POLICY_FREQ, cand)
                        # If it passes, immediately roll back that part by updating later; keep cand
                        provisional = cand
                        break
                    except IntegrityError:
                        continue
                else:
                    raise  # none passed; surface the original error

            # Now, if provisional is not the "no compounding" we want, probe a better one
            # Prefer a 'no-compounding' semantic
            prefer = ["none", "no", "flat", "n", "off", "nil"]
            chosen = None
            try_list = [v for v in prefer if v in allowed] or allowed
            chosen = _probe_compounding_literal(conn, policy_id, try_list)
            update_policy_core(conn, policy_id, start_year, month, POLICY_FREQ, chosen)
        else:
            # Existing row → detect a legal 'no-compounding' literal by probing update
            prefer = ["none", "no", "flat", "n", "off", "nil"]
            try_list = [v for v in prefer if v in allowed] or allowed
            chosen = _probe_compounding_literal(conn, policy_id, try_list)
            update_policy_core(conn, policy_id, start_year, month, POLICY_FREQ, chosen)

        # Components
        replace_policy_components(conn, policy_id, ammon_id, cpi_id)

    print(f"[ok] escalation_policies upserted for '{POLICY_NAME}' with components 45/55")

    if scenario_id:
        with engine.begin() as conn:
            set_scenario_default_policy(conn, scenario_id, policy_id)
        print(f"[ok] scenarios.default_price_escalation_policy_id set to {policy_id} for scenario {scenario_id}")

    print("[done] Seed complete. Safe to re-run.")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--db", default=default_db_url(), help="SQLAlchemy DB URL")
    ap.add_argument("--scenario", type=int, default=None, help="Scenario ID to set as default policy")
    ap.add_argument("--start-year", type=int, default=DEFAULT_START_YEAR)
    ap.add_argument("--end-year", type=int, default=DEFAULT_END_YEAR)
    ap.add_argument("--month", type=int, default=DEFAULT_MONTH)
    args = ap.parse_args()

    main(args.db, args.scenario, args.start_year, args.end_year, args.month)
