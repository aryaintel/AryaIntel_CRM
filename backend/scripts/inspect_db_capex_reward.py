# file: inspect_db_capex_reward.py
from pathlib import Path
import sqlite3
import argparse
from pprint import pprint

def find_db():
    cand = [
        Path("backend/app.db"),
        Path("app.db"),
        Path(__file__).resolve().parent / "app.db",
        Path(__file__).resolve().parent.parent / "app.db",
    ]
    for p in cand:
        if p.exists():
            return p.resolve()
    raise SystemExit("app.db bulunamadı. Proje kökünden çalıştırmayı deneyin.")

def pragma_table(cx, table):
    rows = cx.execute(f"PRAGMA table_info({table});").fetchall()
    cols = [dict(cid=r[0], name=r[1], type=r[2], notnull=r[3], default=r[4], pk=r[5]) for r in rows]
    return cols

def safe_select_one(cx, table, columns, where=""):
    # Kolon var mı yok mu kontrol ederek select hazırla
    existing = {c["name"] for c in pragma_table(cx, table)}
    cols = [c for c in columns if c in existing]
    if not cols:
        return {}
    sql = f"SELECT {', '.join(cols)} FROM {table} {where} LIMIT 1"
    row = cx.execute(sql).fetchone()
    return dict(row) if row else {}

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--scenario-id", type=int, default=1)
    args = ap.parse_args()

    db_path = find_db()
    print(f"DB: {db_path}")

    cx = sqlite3.connect(str(db_path))
    cx.row_factory = sqlite3.Row

    print("\n--- PRAGMA scenario_capex ---")
    pprint(pragma_table(cx, "scenario_capex"))

    print("\n--- PRAGMA scenarios ---")
    pprint(pragma_table(cx, "scenarios"))

    print("\n--- scenarios satırı (senaryo varsayılanları) ---")
    scen_cols_to_try = [
        # mevcut şema için
        "start_date", "months", "default_capex_reward_pct",
        # eski/alternatif adlar varsa
        "contract_start_year", "contract_start_month", "contract_term_months",
    ]
    scen = safe_select_one(cx, "scenarios", scen_cols_to_try, f"WHERE id = {args.scenario_id}")
    pprint(scen or {"info": "Kayıt yok veya sütunlar bulunamadı"})

    print("\n--- scenario_capex örnek satır(lar) ---")
    # reward alanları + amortisman alanları
    capex_cols = [
        "id", "scenario_id", "amount", "service_start_year", "service_start_month",
        "useful_life_months", "depr_method", "salvage_value",
        "reward_enabled", "reward_pct", "reward_spread_kind",
        "linked_boq_item_id", "term_months_override",
        # eski/alternatif isimler varsa:
        "one_off_cost", "start_year", "start_month", "depr_years",
    ]
    # ilk 5 kaydı getir
    existing = {c["name"] for c in pragma_table(cx, "scenario_capex")}
    cols = [c for c in capex_cols if c in existing]
    sql = f"SELECT {', '.join(cols)} FROM scenario_capex WHERE scenario_id = ? LIMIT 5"
    rows = [dict(r) for r in cx.execute(sql, (args.scenario_id,)).fetchall()]
    pprint(rows or [{"info": "CAPEX kaydı bulunamadı"}])

    # Kolon var/yok durumu hızlı özet
    print("\n--- Hızlı Özet ---")
    must_have_for_reward = ["reward_enabled", "reward_pct", "reward_spread_kind", "term_months_override"]
    missing = [c for c in must_have_for_reward if c not in existing]
    if missing:
        print("Eksik CAPEX kolonları (reward için):", missing)
    else:
        print("CAPEX reward kolonları mevcut.")

    scen_existing = {c["name"] for c in pragma_table(cx, "scenarios")}
    if {"start_date", "months"} <= scen_existing:
        print("Senaryo başlangıcı & süre: start_date + months ile türetilebilir.")
    elif {"contract_start_year", "contract_start_month", "contract_term_months"} <= scen_existing:
        print("Senaryo başlangıcı & süre: contract_* alanlarıyla mevcut.")
    else:
        print("Senaryo başlangıcı/süre için gerekli alanlar bulunamadı.")

if __name__ == "__main__":
    main()
