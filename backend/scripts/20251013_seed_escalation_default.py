#!/usr/bin/env python3
# Pathway: C:/Dev/AryaIntel_CRM/backend/scripts/20251013_seed_escalation_default.py
"""
Seed default Rise & Fall (index-based) policies for scenarios (idempotent, CHECK-aware + PROBE fallback).

- Tries to parse CHECK(scope IN (...)) from CREATE TABLE DDL.
- If not found, PROBES allowed tokens using SQLite SAVEPOINTs (no changes persisted).
- If a global token is allowed (ALL/GLOBAL/*/ANY/ALL_SECTIONS/ALL_ITEMS), inserts **one** policy per scenario.
- Else, inserts one policy per each allowed section token (e.g., AN/EM/IE/Services or their DB-specific forms).
- Skips scenarios that already have any scenario_escalation_policies rows.
- Ensures index_series('GEN_CPI') and index_points for each scenario window.

Usage (from backend folder):
  python scripts/20251013_seed_escalation_default.py --db sqlite:///C:/Dev/AryaIntel_CRM/backend/app.db --cpi-monthly 0.003
"""

import argparse
import re
from typing import List, Optional, Sequence, Tuple

from sqlalchemy import create_engine, text
from sqlalchemy.engine import Connection
from sqlalchemy.exc import IntegrityError

GLOBAL_ALIASES = {"all", "global", "*", "any", "all_sections", "all_items"}
CANDIDATE_SECTIONS = [
    # canonical
    "AN", "EM", "IE", "Services",
    # common variants
    "SERVICES", "SERVICE", "Srv", "SRV", "SVC", "svc",
]


def _log(m: str) -> None:
    print(m, flush=True)


def _fetch_table_sql(conn: Connection, table: str) -> Optional[str]:
    row = conn.execute(text("SELECT sql FROM sqlite_master WHERE type='table' AND name=:t"), {"t": table}).fetchone()
    return row[0] if row and row[0] else None


def _parse_check_tokens(create_sql: str, column: str) -> List[str]:
    # Find any "... CHECK ( <column> IN ( ... ) ) ..." occurrence
    m = re.search(r"CHECK\s*\(\s*%s\s*IN\s*\(([^)]*)\)\s*\)" % re.escape(column), create_sql, flags=re.IGNORECASE)
    if not m:
        return []
    inner = m.group(1)
    tokens = []
    for piece in inner.split(","):
        s = piece.strip()
        if not s:
            continue
        if (s[0] in "'\"" and s[-1] == s[0]) and len(s) >= 2:
            s = s[1:-1]
        tokens.append(s)
    return tokens


def _iter_scenarios(conn: Connection) -> Sequence[Tuple[int, str, int]]:
    return conn.execute(text("SELECT id, start_date, months FROM scenarios ORDER BY id")).all()


def _yyyymm_iter(start_date: str, months: int):
    y, m, _ = [int(x) for x in str(start_date).split("-")]
    for i in range(months):
        yy = y + (m - 1 + i) // 12
        mm = (m - 1 + i) % 12 + 1
        yield yy, mm


def ensure_series(conn: Connection, code: str, name: str) -> int:
    row = conn.execute(text("SELECT id FROM index_series WHERE code=:c"), {"c": code}).fetchone()
    if row:
        return int(row[0])
    cols = [c[1] for c in conn.execute(text("PRAGMA table_info('index_series')")).fetchall()]
    parts, vals = [], {}
    for k, v in (("code", code), ("name", name), ("unit", "index")):
        if k in cols:
            parts.append(k); vals[k] = v
    conn.execute(text(f"INSERT INTO index_series ({', '.join(parts)}) VALUES ({', '.join(':'+p for p in parts)})"), vals)
    new_id = conn.execute(text("SELECT id FROM index_series WHERE code=:c"), {"c": code}).fetchone()[0]
    return int(new_id)


def ensure_points(conn: Connection, series_id: int, start_year: int, start_month: int, months: int, monthly_growth: float):
    base = 100.0
    value = base
    for i, (y, m) in enumerate(_yyyymm_iter(f"{start_year:04d}-{start_month:02d}-01", months)):
        exists = conn.execute(text("""
            SELECT 1 FROM index_points WHERE series_id=:sid AND year=:y AND month=:m
        """), {"sid": series_id, "y": y, "m": m}).fetchone()
        if exists:
            continue
        if i > 0:
            value *= (1.0 + monthly_growth)
        conn.execute(text("""
            INSERT INTO index_points (series_id, year, month, value)
            VALUES (:sid, :y, :m, :v)
        """), {"sid": series_id, "y": y, "m": m, "v": value})


def _existing_policy_any(conn: Connection, scenario_id: int) -> bool:
    r = conn.execute(text("SELECT 1 FROM scenario_escalation_policies WHERE scenario_id=:sid LIMIT 1"),
                     {"sid": scenario_id}).fetchone()
    return bool(r)


def _existing_policy_for_scope(conn: Connection, scenario_id: int, scope: str) -> bool:
    r = conn.execute(text("SELECT 1 FROM scenario_escalation_policies WHERE scenario_id=:sid AND scope=:sc LIMIT 1"),
                     {"sid": scenario_id, "sc": scope}).fetchone()
    return bool(r)


def _cols(conn: Connection, table: str) -> List[str]:
    return [c[1] for c in conn.execute(text(f"PRAGMA table_info('{table}')")).fetchall()]


def _probe_token(conn: Connection, scenario_id: int, scope_token: str, base_year: int, base_month: int) -> bool:
    """Try INSERT within a SAVEPOINT and roll back. Returns True if CHECK accepts the token."""
    cols = _cols(conn, "scenario_escalation_policies")
    parts, vals = ["scenario_id"], {"scenario_id": scenario_id}
    def add(c, v):
        if c in cols:
            parts.append(c); vals[c] = v
    add("name", f"__probe__{scope_token}")
    add("scope", scope_token)
    add("method", "index")
    add("index_code", "GEN_CPI")
    add("base_year", base_year)
    add("base_month", base_month)
    add("step_per_month", 1)
    add("freq", "monthly")
    add("is_active", 1)

    try:
        conn.execute(text("SAVEPOINT sp_probe"))
        conn.execute(text(f"INSERT INTO scenario_escalation_policies ({', '.join(parts)}) VALUES ({', '.join(':'+p for p in parts)})"), vals)
        conn.execute(text("ROLLBACK TO sp_probe"))
        conn.execute(text("RELEASE sp_probe"))
        return True
    except IntegrityError:
        # CHECK or other constraint failed → token not allowed
        try:
            conn.execute(text("ROLLBACK TO sp_probe"))
            conn.execute(text("RELEASE sp_probe"))
        except Exception:
            pass
        return False
    except Exception:
        try:
            conn.execute(text("ROLLBACK TO sp_probe"))
            conn.execute(text("RELEASE sp_probe"))
        except Exception:
            pass
        return False


def seed_for_scope(conn: Connection, scenario_id: int, scope_token: str, base_year: int, base_month: int) -> bool:
    if _existing_policy_for_scope(conn, scenario_id, scope_token):
        return False
    cols = _cols(conn, "scenario_escalation_policies")
    parts, vals = ["scenario_id"], {"scenario_id": scenario_id}
    def add(c, v):
        if c in cols:
            parts.append(c); vals[c] = v
    add("name", f"Default CPI Escalation ({scope_token})")
    add("scope", scope_token)
    add("method", "index")
    add("index_code", "GEN_CPI")
    add("base_year", base_year)
    add("base_month", base_month)
    add("step_per_month", 1)
    add("freq", "monthly")
    add("is_active", 1)
    conn.execute(text(f"INSERT INTO scenario_escalation_policies ({', '.join(parts)}) VALUES ({', '.join(':'+p for p in parts)})"), vals)
    return True


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--db", default="sqlite:///C:/Dev/AryaIntel_CRM/backend/app.db", help="SQLAlchemy URL")
    ap.add_argument("--cpi-monthly", type=float, default=0.003)
    ap.add_argument("--scenario", type=int, default=None)
    args = ap.parse_args()

    engine = create_engine(args.db)
    dialect = engine.dialect.name
    _log(f"[info] dialect={dialect}")
    with engine.begin() as conn:
        dblist = conn.execute(text("PRAGMA database_list")).fetchall()
        _log(f"[info] database_list={dblist}")

    # Ensure CPI series exists
    with engine.begin() as conn:
        series_id = ensure_series(conn, "GEN_CPI", "Generic CPI")
        _log(f"[info] index_series GEN_CPI id={series_id}")

    # Collect scenarios
    with engine.begin() as conn:
        scenarios = _iter_scenarios(conn)
        _log(f"[info] scenarios_count={len(scenarios)}")

    if not scenarios:
        _log("[warn] no scenarios found. exiting.")
        return

    # Try to parse CHECK tokens from DDL
    parsed_tokens: List[str] = []
    with engine.begin() as conn:
        ddl = _fetch_table_sql(conn, "scenario_escalation_policies")
        if ddl:
            parsed_tokens = _parse_check_tokens(ddl, "scope")
            if parsed_tokens:
                _log(f"[info] parsed_scope_tokens={parsed_tokens}")
        else:
            _log("[warn] could not fetch DDL from sqlite_master for scenario_escalation_policies")

    created_total = 0
    scenarios_touched = 0

    for sid, start_date, months in scenarios:
        sid = int(sid); months = int(months)
        if args.scenario and sid != args.scenario:
            continue
        y, m, _ = [int(x) for x in str(start_date).split("-")]

        with engine.begin() as conn:
            if _existing_policy_any(conn, sid):
                _log(f"[skip] scenario {sid} already has policy rows; skipping")
                continue

        # prepare index points
        with engine.begin() as conn:
            ensure_points(conn, series_id, y, m, months, args.cpi_monthly)

        # Decide allowed tokens for this DB
        allowed_tokens: List[str] = []
        if parsed_tokens:
            allowed_tokens = parsed_tokens[:]
        else:
            # PROBE path: test tokens safely with SAVEPOINTs
            probe_set = list(GLOBAL_ALIASES) + CANDIDATE_SECTIONS
            with engine.begin() as conn:
                for tok in probe_set:
                    ok = _probe_token(conn, max(1, sid), tok if tok != "*" else "*", y, m)
                    if ok:
                        allowed_tokens.append(tok)
            _log(f"[info] probe_allowed_tokens={allowed_tokens}")

        if not allowed_tokens:
            _log(f"[warn] scenario {sid}: no compatible scope tokens found; cannot seed")
            continue

        # Prefer global if exists among allowed (case-insensitive)
        lt = {t.lower(): t for t in allowed_tokens}
        global_tok = next((lt[t] for t in lt if t in GLOBAL_ALIASES), None)

        scopes_to_seed = [global_tok] if global_tok else allowed_tokens

        with engine.begin() as conn:
            created = 0
            for sc in scopes_to_seed:
                if seed_for_scope(conn, sid, sc, y, m):
                    created += 1
            created_total += created
            scenarios_touched += 1
            _log(f"[ok] scenario {sid}: created {created} policy row(s) (scopes={scopes_to_seed})")

    _log(f"[done] inserted_policies={created_total}, scenarios_touched={scenarios_touched}")


if __name__ == "__main__":
    main()
