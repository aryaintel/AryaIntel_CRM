#!/usr/bin/env python3
"""
Flexible seeding for engine_category_map

Why:
- Some DBs don't have `product_families`; others keep family codes on `products`
  (e.g., columns like family_code/family/category), or as product_attributes.
- This script adapts to what's available OR seeds from a scenario directly.

Modes:
  1) families (default): derive source_code from product family info
     - tries JOIN products -> product_families (if exists)
     - else tries products.family_code / products.family / products.category
     - else tries product_attributes(name='family_code') / 'family' / 'category'
  2) scenario: take all products used in scenario_boq_items for a scenario and
     assign a single category code (e.g., AN) or via name LIKE rules.

Rules mapping:
  --rules "AN=AN,EM=EM,IE=IE,Services=Services"
  Meaning: source_code (left side) -> engine category_code (right side).

Examples:
  # Use families mode (default) and also write product_attributes(engine_category)
  python scripts/20251015_seed_engine_categories_flex.py \
    --db sqlite:///C:/Dev/AryaIntel_CRM/backend/app.db \
    --rules "AN=AN,EM=EM,IE=IE,Services=Services" \
    --write-attr

  # Seed only products present in scenario 1 as AN (quick start):
  python scripts/20251015_seed_engine_categories_flex.py \
    --db sqlite:///C:/Dev/AryaIntel_CRM/backend/app.db \
    --mode scenario --scenario 1 --category AN

Safety:
- Inserts new rows if missing; re-activates inactive matches.
- Does not delete or override different categories for the same product.
"""
from __future__ import annotations
import argparse, sqlite3, re, sys
from typing import Dict, List, Tuple, Optional

def parse_db_url(db_url: str) -> str:
    if db_url.startswith("sqlite:///"):
        path = db_url[len("sqlite:///"):]
        if re.match(r"^/[A-Za-z]:/", path):
            path = path[1:]
        return path
    return db_url

def parse_rules(s: str) -> Dict[str, str]:
    out: Dict[str, str] = {}
    if not s:
        return out
    for part in s.split(","):
        part = part.strip()
        if not part:
            continue
        if "=" not in part:
            raise SystemExit(f"Bad rule '{part}', expected left=right")
        left, right = [x.strip() for x in part.split("=", 1)]
        if not left or not right:
            raise SystemExit(f"Bad rule '{part}', empty side")
        out[left] = right
    return out

def table_exists(conn: sqlite3.Connection, name: str) -> bool:
    cur = conn.cursor()
    cur.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (name,))
    return cur.fetchone() is not None

def col_exists(conn: sqlite3.Connection, table: str, col: str) -> bool:
    cur = conn.cursor()
    try:
        cur.execute(f"PRAGMA table_info({table})")
        cols = [r[1] for r in cur.fetchall()]
        return col in cols
    except sqlite3.OperationalError:
        return False

def ensure_seed_categories(conn: sqlite3.Connection):
    cur = conn.cursor()
    cur.execute("""
        INSERT OR IGNORE INTO engine_categories(code,name,sort_order) VALUES
        ('AN','Ammonium Nitrate',10),
        ('EM','Emulsion',20),
        ('IE','Initiating Explosives',30),
        ('Services','Services',40)
    """)
    conn.commit()

def upsert_map(conn: sqlite3.Connection, product_ids: List[int], category_code: str, write_attr: bool=False) -> Tuple[int,int,int]:
    """
    Returns: (inserted, activated, attrs_inserted)
    """
    cur = conn.cursor()
    # existing
    cur.execute("""
        SELECT ref_id, category_code, is_active
        FROM engine_category_map
        WHERE scope='product'
    """)
    existing = {(r[0], r[1]): r[2] for r in cur.fetchall()}

    to_insert = []
    to_update = []
    for pid in product_ids:
        key = (pid, category_code)
        if key not in existing:
            to_insert.append((pid, category_code))
        elif not existing[key]:
            to_update.append((1, pid, category_code))

    ins = act = attr_ins = 0
    if to_insert:
        cur.executemany("""
            INSERT INTO engine_category_map(scope, ref_id, category_code, is_active)
            VALUES('product', ?, ?, 1)
        """, to_insert)
        ins = len(to_insert)
    if to_update:
        cur.executemany("""
            UPDATE engine_category_map SET is_active=?
            WHERE scope='product' AND ref_id=? AND category_code=?
        """, to_update)
        act = len(to_update)

    if write_attr and (ins or act):
        cur.execute("""
            SELECT product_id, value
            FROM product_attributes
            WHERE name='engine_category'
        """)
        have_attr = {(r[0], r[1]) for r in cur.fetchall()}
        attr_to_insert = []
        for pid in product_ids:
            if (pid, category_code) not in have_attr:
                attr_to_insert.append((pid, 'engine_category', category_code))
        if attr_to_insert:
            cur.executemany("""
                INSERT INTO product_attributes(product_id, name, value)
                VALUES(?, ?, ?)
            """, attr_to_insert)
            attr_ins = len(attr_to_insert)

    return ins, act, attr_ins

def families_mode(conn: sqlite3.Connection, rules: Dict[str,str], write_attr: bool=False, dry_run: bool=False):
    """
    Determine a source_code per product, then map via rules.
    Source candidates (in order):
      1) JOIN product_families.code
      2) products.family_code / products.family / products.category
      3) product_attributes: family_code / family / category
    """
    cur = conn.cursor()
    # 1) Try join
    products_with_code: List[Tuple[int,str]] = []
    if table_exists(conn, "product_families") and col_exists(conn, "products", "product_family_id"):
        cur.execute("""
            SELECT p.id, pf.code
            FROM products p
            JOIN product_families pf ON pf.id = p.product_family_id
        """)
        products_with_code = [(r[0], r[1]) for r in cur.fetchall()]

    # 2) Fallback to columns on products
    if not products_with_code:
        candidate_cols = [c for c in ("family_code","family","category","category_code") if col_exists(conn, "products", c)]
        for c in candidate_cols:
            cur.execute(f"SELECT id, {c} FROM products WHERE {c} IS NOT NULL AND TRIM({c})!=''")
            got = [(r[0], r[1]) for r in cur.fetchall()]
            if got:
                products_with_code = got
                break

    # 3) Fallback to product_attributes
    if not products_with_code and table_exists(conn, "product_attributes"):
        for attr_name in ("family_code","family","category"):
            cur.execute("""
                SELECT product_id, value FROM product_attributes
                WHERE name=? AND value IS NOT NULL AND TRIM(value)!=''
            """, (attr_name,))
            got = [(r[0], r[1]) for r in cur.fetchall()]
            if got:
                products_with_code = got
                break

    if not products_with_code:
        print("[INFO] Could not determine any family/category code for products. Nothing to do.")
        return

    # Group products by source_code
    by_code: Dict[str, List[int]] = {}
    for pid, code in products_with_code:
        code = str(code).strip()
        if not code:
            continue
        by_code.setdefault(code, []).append(pid)

    # Plan: apply rules
    all_ins = all_act = all_attr = 0
    for src_code, pids in by_code.items():
        if src_code in rules:
            cat = rules[src_code]
            print(f"[PLAN] {src_code} -> {cat} for {len(pids)} products")
            if not dry_run:
                ins, act, attr = upsert_map(conn, pids, cat, write_attr=write_attr)
                all_ins += ins; all_act += act; all_attr += attr
        else:
            print(f"[SKIP] No rule for source code: {src_code} ({len(pids)} products)")
    if not dry_run:
        conn.commit()
        print(f"[OK] engine_category_map upserted. inserted={all_ins}, activated={all_act}, attrs={all_attr}")

def scenario_mode(conn: sqlite3.Connection, scenario_id: int, category: str, write_attr: bool=False, dry_run: bool=False):
    cur = conn.cursor()
    cur.execute("""
        SELECT DISTINCT product_id
        FROM scenario_boq_items
        WHERE scenario_id=? AND is_active=1 AND product_id IS NOT NULL
    """, (scenario_id,))
    pids = [r[0] for r in cur.fetchall()]
    if not pids:
        print("[INFO] No products found in scenario_boq_items for this scenario.")
        return
    print(f"[PLAN] Scenario {scenario_id}: map {len(pids)} products -> {category}")
    if dry_run:
        return
    ins, act, attr = upsert_map(conn, pids, category, write_attr=write_attr)
    conn.commit()
    print(f"[OK] engine_category_map upserted. inserted={ins}, activated={act}, attrs={attr}")

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--db", dest="db_url", required=True)
    ap.add_argument("--mode", choices=["families","scenario"], default="families")
    ap.add_argument("--rules", default="", help="CSV: family_code=category_code,... (families mode)")
    ap.add_argument("--write-attr", action="store_true")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--scenario", type=int, help="scenario id (scenario mode)")
    ap.add_argument("--category", help="engine category code (scenario mode)")
    args = ap.parse_args()

    db_path = parse_db_url(args.db_url)
    conn = sqlite3.connect(db_path)
    try:
        ensure_seed_categories(conn)
        if args.mode == "families":
            rules = parse_rules(args.rules)
            if not rules:
                raise SystemExit("--rules is required in families mode")
            families_mode(conn, rules, write_attr=args.write_attr, dry_run=args.dry_run)
        else:
            if not args.scenario or not args.category:
                raise SystemExit("--scenario and --category are required in scenario mode")
            scenario_mode(conn, args.scenario, args.category, write_attr=args.write_attr, dry_run=args.dry_run)
    finally:
        conn.close()

if __name__ == "__main__":
    main()
