#!/usr/bin/env python3
# Pathway: C:/Dev/AryaIntel_CRM/backend/scripts/20251014_widen_sesc_scope_and_standardize.py
"""
Widen CHECK on scenario_escalation_policies.scope to include Title/Upper case variants
(e.g., 'ALL', 'Services', 'Capex') and standardize existing rows accordingly.

Usage:
  python backend/scripts/20251014_widen_sesc_scope_and_standardize.py --db sqlite:///C:/Dev/AryaIntel_CRM/backend/app.db
"""
import argparse, re, sys
from sqlalchemy import create_engine, text

TARGET_TABLE = "scenario_escalation_policies"
COLUMN = "scope"
TITLE_TOKENS = ["Services", "Capex", "ALL"]
LOWER_MAP = {"services":"Services", "capex":"Capex", "all":"ALL"}

def log(m): print(m, flush=True)

def fetch_create_sql(engine):
    with engine.connect() as conn:
        row = conn.execute(text("SELECT sql FROM sqlite_master WHERE type='table' AND name=:t"), {"t": TARGET_TABLE}).fetchone()
        return row[0] if row and row[0] else None

def parse_check_tokens(create_sql: str):
    m = re.search(r"CHECK\\s*\\(\\s*%s\\s*IN\\s*\\(([^)]*)\\)\\s*\\)" % re.escape(COLUMN), create_sql, flags=re.IGNORECASE)
    if not m: return []
    inner = m.group(1)
    out = []
    for piece in inner.split(","):
        s = piece.strip()
        if not s: continue
        if (s[0] in "'\\\"" and s[-1] == s[0]) and len(s) >= 2:
            s = s[1:-1]
        out.append(s)
    return out

def inject_tokens(create_sql: str, need_tokens):
    def repl(m):
        inner = m.group(1)
        toks = []
        for piece in inner.split(","):
            s = piece.strip()
            if not s: continue
            if (s[0] in "'\\\"" and s[-1] == s[0]) and len(s) >= 2:
                s = s[1:-1]
            toks.append(s)
        for t in need_tokens:
            if t not in toks:
                toks.append(t)
        rebuilt = ", ".join(f"'{t}'" for t in toks)
        return f"CHECK({COLUMN} IN ({rebuilt}))"
    new_sql, n = re.subn(r"CHECK\\s*\\(\\s*%s\\s*IN\\s*\\(([^)]*)\\)\\s*\\)" % re.escape(COLUMN), repl, create_sql, count=1, flags=re.IGNORECASE)
    return new_sql if n else None

def sqlite_rebuild_with_sql(engine, widened_sql: str):
    from sqlalchemy import text as _t
    with engine.connect() as conn:
        cols = [r[1] for r in conn.execute(_t(f"PRAGMA table_info('{TARGET_TABLE}')")).fetchall()]
        col_list = ", ".join(f'"{c}"' for c in cols)
        idx_rows = conn.execute(_t("SELECT name, sql FROM sqlite_master WHERE type='index' AND tbl_name=:t AND sql IS NOT NULL"), {"t": TARGET_TABLE}).fetchall()
        trg_rows = conn.execute(_t("SELECT name, sql FROM sqlite_master WHERE type='trigger' AND tbl_name=:t"), {"t": TARGET_TABLE}).fetchall()
    tmp = f"{TARGET_TABLE}__tmp"
    with engine.begin() as conn:
        conn.execute(_t("PRAGMA foreign_keys=OFF"))
        conn.execute(_t(f"DROP TABLE IF EXISTS {tmp}"))
        widened_sql_tmp = re.sub(r"(?i)^(CREATE\\s+TABLE\\s+)(\"?%s\"?)" % re.escape(TARGET_TABLE), r"\\1%s" % tmp, widened_sql, count=1)
        conn.execute(_t(widened_sql_tmp))
        conn.execute(_t(f'INSERT INTO {tmp} ({col_list}) SELECT {col_list} FROM {TARGET_TABLE}'))
        conn.execute(_t(f"DROP TABLE {TARGET_TABLE}"))
        conn.execute(_t(f"ALTER TABLE {tmp} RENAME TO {TARGET_TABLE}"))
        for name, idx_sql in idx_rows:
            if idx_sql: conn.execute(_t(idx_sql))
        for name, trg_sql in trg_rows:
            if trg_sql: conn.execute(_t(trg_sql))
        conn.execute(_t("PRAGMA foreign_keys=ON"))

def standardize(engine):
    changed = 0
    with engine.begin() as conn:
        for low, canon in LOWER_MAP.items():
            r = conn.execute(text(f"UPDATE {TARGET_TABLE} SET {COLUMN}=:canon WHERE lower({COLUMN})=:low"), {"canon": canon, "low": low})
            changed += r.rowcount or 0
    return changed

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--db", required=True)
    args = ap.parse_args()
    engine = create_engine(args.db)
    if engine.dialect.name != "sqlite":
        log("[warn] Only implemented for SQLite."); sys.exit(0)
    create_sql = fetch_create_sql(engine)
    if not create_sql:
        log("[error] Could not fetch DDL"); sys.exit(1)
    tokens = parse_check_tokens(create_sql)
    log(f"[info] existing CHECK tokens: {tokens or 'NONE'}")
    need = [t for t in TITLE_TOKENS if t not in tokens]
    if need:
        log(f"[info] widening CHECK by adding: {need}")
        widened = inject_tokens(create_sql, need)
        if not widened:
            log("[error] Could not locate CHECK(scope IN (...))"); sys.exit(1)
        sqlite_rebuild_with_sql(engine, widened)
        log("[ok] table rebuilt")
    else:
        log("[skip] CHECK already contains desired tokens")
    changed = standardize(engine)
    log(f"[done] standardized rows updated={changed}")
    with engine.connect() as conn:
        dist = conn.execute(text(f"SELECT {COLUMN}, COUNT(*) FROM {TARGET_TABLE} GROUP BY {COLUMN} ORDER BY {COLUMN}")).fetchall()
    log(f"[info] scope distribution: {dist}")

if __name__ == "__main__":
    main()
