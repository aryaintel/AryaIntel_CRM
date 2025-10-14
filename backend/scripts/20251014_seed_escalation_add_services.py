#!/usr/bin/env python3
# Pathway: C:/Dev/AryaIntel_CRM/backend/scripts/20251014_seed_escalation_add_services.py
"""
Add 'services' scoped escalation policies per scenario (idempotent, CHECK-aware).

Usage:
  python backend/scripts/20251014_seed_escalation_add_services.py --db sqlite:///C:/Dev/AryaIntel_CRM/backend/app.db
  python backend/scripts/20251014_seed_escalation_add_services.py --db sqlite:///C:/Dev/AryaIntel_CRM/backend/app.db --scenario 1
"""
import argparse
from sqlalchemy import create_engine, text
from sqlalchemy.engine import Connection
from sqlalchemy.exc import IntegrityError

def log(m): print(m, flush=True)

def cols(conn: Connection, table: str):
    return [c[1] for c in conn.execute(text(f"PRAGMA table_info('{table}')")).fetchall()]

def probe_token(conn: Connection, token: str) -> bool:
    try:
        conn.execute(text("SAVEPOINT sp_probe_svc"))
        sid = conn.execute(text("SELECT id FROM scenarios ORDER BY id LIMIT 1")).scalar() or 1
        cs = cols(conn, "scenario_escalation_policies")
        parts, vals = ["scenario_id"], {"scenario_id": sid}
        def add(c,v):
            if c in cs: parts.append(c); vals[c]=v
        add("name", "__probe__(services)")
        add("scope", token)
        add("method", "index")
        add("index_code", "GEN_CPI")
        add("base_year", 2000)
        add("base_month", 1)
        add("step_per_month", 1)
        add("freq", "monthly")
        add("is_active", 0)
        conn.execute(text(f"INSERT INTO scenario_escalation_policies ({', '.join(parts)}) VALUES ({', '.join(':'+p for p in parts)})"), vals)
        conn.execute(text("ROLLBACK TO sp_probe_svc"))
        conn.execute(text("RELEASE sp_probe_svc"))
        return True
    except IntegrityError:
        try:
            conn.execute(text("ROLLBACK TO sp_probe_svc"))
            conn.execute(text("RELEASE sp_probe_svc"))
        except Exception:
            pass
        return False
    except Exception:
        try:
            conn.execute(text("ROLLBACK TO sp_probe_svc"))
            conn.execute(text("RELEASE sp_probe_svc"))
        except Exception:
            pass
        return False

def scenario_iter(conn: Connection):
    return conn.execute(text("SELECT id, start_date, months FROM scenarios ORDER BY id")).all()

def existing_policy(conn: Connection, sid: int, scope: str) -> bool:
    return bool(conn.execute(text("SELECT 1 FROM scenario_escalation_policies WHERE scenario_id=:sid AND scope=:sc LIMIT 1"),
                             {"sid": sid, "sc": scope}).fetchone())

def any_policy_for_scenario(conn: Connection, sid: int):
    return conn.execute(text("SELECT scope, base_year, base_month FROM scenario_escalation_policies WHERE scenario_id=:sid ORDER BY id LIMIT 1"),
                        {"sid": sid}).mappings().first()

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--db", required=True, help="SQLAlchemy URL")
    ap.add_argument("--scenario", type=int, default=None)
    args = ap.parse_args()
    engine = create_engine(args.db)
    dialect = engine.dialect.name
    log(f"[info] dialect={dialect}")
    # Decide allowed 'services' token via probe
    allowed_token = None
    for tok in ["services", "Services", "SERVICES"]:
        with engine.begin() as conn:
            if probe_token(conn, tok):
                allowed_token = tok; break
    if not allowed_token:
        log("[warn] 'services' not allowed by CHECK; nothing to do."); return
    log(f"[info] services token accepted by CHECK: {allowed_token}")
    created = 0; touched = 0
    with engine.begin() as conn:
        scenarios = scenario_iter(conn)
    for sid, start_date, months in scenarios:
        sid = int(sid)
        if args.scenario and sid != args.scenario:
            continue
        with engine.begin() as conn:
            if existing_policy(conn, sid, allowed_token):
                log(f"[skip] scenario {sid}: '{allowed_token}' policy exists"); 
                continue
            base = any_policy_for_scenario(conn, sid)
            if base and base.get("base_year") and base.get("base_month"):
                by, bm = int(base["base_year"]), int(base["base_month"])
            else:
                y, m, _ = [int(x) for x in str(start_date).split("-")]
                by, bm = y, m
            cs = cols(conn, "scenario_escalation_policies")
            parts, vals = ["scenario_id"], {"scenario_id": sid}
            def add(c, v):
                if c in cs: parts.append(c); vals[c]=v
            add("name", f"Default CPI Escalation ({allowed_token})")
            add("scope", allowed_token)
            add("method", "index")
            add("index_code", "GEN_CPI")
            add("base_year", by)
            add("base_month", bm)
            add("step_per_month", 1)
            add("freq", "monthly")
            add("is_active", 1)
            conn.execute(text(f"INSERT INTO scenario_escalation_policies ({', '.join(parts)}) VALUES ({', '.join(':'+p for p in parts)})"), vals)
            created += 1; touched += 1
            log(f"[ok] scenario {sid}: inserted '{allowed_token}' policy (base {by}-{bm:02d})")
    log(f"[done] inserted={created}, scenarios_touched={touched}")

if __name__ == "__main__":
    main()
