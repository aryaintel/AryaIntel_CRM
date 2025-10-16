# Path: backend/app/engine/an_calculator.py
# C:/Dev/AryaIntel_CRM/backend/app/engine/an_calculator.py
"""
AN Engine — R+F index-based monthly facts with Freight & Mgmt Fee split
----------------------------------------------------------------------
This module computes monthly Revenue / COGS / GP for the AN category,
matching Tender Excel pages:
  - c.Sales-AN (monthly, revenue components)
  - oQ.Finance-AN (quarterly aggregated)
  - oA.Finance-AN (annual aggregated)

It is intentionally **pure** in computation and **thin** in data access:
- Data fetch helpers are isolated and use existing tables:
  index_series, index_points, escalation_policies, escalation_policy_components,
  scenario_boq_items, scenario_products, engine_runs, engine_facts_monthly, scenarios.
- No schema changes required by default. If your schema includes a `series` column
  on `engine_facts_monthly`, it will be used; otherwise a clear error is raised
  when multiple series would be persisted (see `persist_an_facts`).
  (Recommended: add `series TEXT` to `engine_facts_monthly` to store multiple series.)

USAGE (pipeline):
    from app.engine.an_calculator import compute_an_facts, persist_an_facts

    facts_m, facts_q, facts_a = compute_an_facts(db, scenario_id)
    persist_an_facts(db, run_id, scenario_id, facts_m, facts_q, facts_a)

Where each facts_* is a list[FactRow]:
    FactRow = dict(sheet_code, category_code, yyyymm, series, value)

Design notes:
- R+F = weighted index basket from escalation_policies/components.
- Frequency = annual (Excel parity). Multiplier at year boundaries.
- Freight & Management Fee separated both on revenue and cost side (zeros if not modeled).
- GP is computed **ex-tax**: GP = total_revenue − (cogs_ex_tax + freight_cost).

Author: AryaIntel CRM Engine Team
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, Iterable, List, Optional, Tuple
from datetime import date

from sqlalchemy.orm import Session
from sqlalchemy import text
from app.services.engine_persist import upsert_fact, Series


# --------------------------- Small date helpers ---------------------------

def ym_to_int(y: int, m: int) -> int:
    return y * 100 + m

def int_to_ym(yyyymm: int) -> Tuple[int, int]:
    y = yyyymm // 100
    m = yyyymm % 100
    return y, m

def add_months(yyyymm: int, n: int) -> int:
    y, m = int_to_ym(yyyymm)
    total = (y * 12 + (m - 1)) + n
    ny = total // 12
    nm = total % 12 + 1
    return ym_to_int(ny, nm)

def ym_range(start_yyyymm: int, months: int) -> List[int]:
    return [add_months(start_yyyymm, i) for i in range(months)]


# ------------------------------- Data types -------------------------------

@dataclass
class ANInputs:
    """
    Inputs for AN computation (per scenario). Prices are base-month (contract) snapshots.
    All monetary values are in scenario currency; FX handled upstream if needed.
    """
    # Contract horizon
    start_yyyymm: int
    months: int

    # Base prices (c.Sales-AN style)
    sales_price: float               # base sales unit price (ex-tax)
    unit_cogs: float                 # base ex-tax COGS per unit
    quantity_per_month: float        # monthly volume

    # Revenue components
    freight_unit_price: float = 0.0  # base freight revenue per unit
    mgmt_fee_unit_price: float = 0.0 # base management fee revenue per unit

    # Cost components
    freight_unit_cost: float = 0.0   # base freight cost per unit

    # Escalation / R+F
    escalation_policy_id: Optional[int] = None  # weighted index basket
    escalation_frequency: str = "annual"        # Excel parity

@dataclass
class FactRow:
    sheet_code: str
    category_code: str
    yyyymm: int
    series: str
    value: float


# -------------------------- Data fetcher functions ------------------------

def _get_scenario_horizon(db: Session, scenario_id: int) -> Tuple[int, int]:
    """
    Read (start_date, months) from scenarios to produce start_yyyymm and horizon.
    """
    row = db.execute(text("""
        SELECT strftime('%Y', start_date) as y, strftime('%m', start_date) as m, months
        FROM scenarios WHERE id=:sid
    """), {"sid": scenario_id}).mappings().first()
    if not row:
        raise ValueError(f"Scenario {scenario_id} not found")
    start_yyyymm = int(row["y"]) * 100 + int(row["m"])
    months = int(row["months"])
    return start_yyyymm, months


def _get_an_base_prices(db: Session, scenario_id: int) -> Tuple[float, float, float, float, float]:
    """
    Fetch base unit prices for AN for the active AN line.
    Priority:
      1) scenario_boq_items mapped to AN via engine_category_map
      2) scenario_boq_items with category='AN'
      3) scenario_products mapped to AN (or name contains 'AN')
    Returns: (sales_price, unit_cogs, freight_unit_price, mgmt_fee_unit_price, freight_unit_cost)

    NOTE: This function assumes a single primary AN line per scenario (Excel parity).
    If multiple exist, first row by id ASC is used.
    """
    # 1) BOQ via category map
    row = db.execute(text("""
        WITH an_boq AS (
            SELECT b.*
            FROM scenario_boq_items b
            JOIN engine_category_map ecm
              ON ecm.scope='scenario_boq_item' AND ecm.ref_id=b.id AND ecm.category_code='AN' AND ecm.is_active=1
            WHERE b.scenario_id=:sid
            ORDER BY b.id ASC
            LIMIT 1
        )
        SELECT unit_price AS sales_price,
               COALESCE(unit_cogs, 0.0) AS unit_cogs
        FROM an_boq
    """), {"sid": scenario_id}).mappings().first()
    if row:
        return float(row["sales_price"] or 0), float(row["unit_cogs"] or 0), 0.0, 0.0, 0.0

    # 2) BOQ with category literal
    row = db.execute(text("""
        SELECT unit_price AS sales_price,
               COALESCE(unit_cogs, 0.0) AS unit_cogs
        FROM scenario_boq_items
        WHERE scenario_id=:sid AND (UPPER(category)='AN' OR category='Ammonium Nitrate')
        ORDER BY id ASC LIMIT 1
    """), {"sid": scenario_id}).mappings().first()
    if row:
        return float(row["sales_price"] or 0), float(row["unit_cogs"] or 0), 0.0, 0.0, 0.0

    # 3) Scenario products fallback
    row = db.execute(text("""
        WITH an_products AS (
            SELECT sp.*
            FROM scenario_products sp
            LEFT JOIN engine_category_map ecm
              ON ecm.scope='scenario_product' AND ecm.ref_id=sp.id AND ecm.category_code='AN' AND ecm.is_active=1
            WHERE sp.scenario_id=:sid
              AND sp.is_active=1
              AND (ecm.id IS NOT NULL OR UPPER(sp.name) LIKE '%AN%')
            ORDER BY sp.id ASC
            LIMIT 1
        )
        SELECT
            price           AS sales_price,
            unit_cogs       AS unit_cogs
        FROM an_products
    """), {"sid": scenario_id}).mappings().first()

    if not row:
        raise ValueError("No active AN line found (map a BOQ item or scenario product to 'AN').")

    return float(row["sales_price"] or 0), float(row["unit_cogs"] or 0), 0.0, 0.0, 0.0


def _get_monthly_quantity(db: Session, scenario_id: int) -> float:
    """
    Fetch monthly quantity for AN. Priority:
      1) Sum of BOQ quantities mapped to AN (engine_category_map)
      2) Sum of BOQ quantities where category='AN'
      3) Fallback 1.0
    """
    row = db.execute(text("""
        -- 1) Mapped BOQ
        SELECT SUM(b.quantity) AS q
        FROM scenario_boq_items b
        JOIN engine_category_map ecm
          ON ecm.scope='scenario_boq_item' AND ecm.ref_id=b.id AND ecm.category_code='AN' AND ecm.is_active=1
        WHERE b.scenario_id=:sid
    """), {"sid": scenario_id}).mappings().first()
    if row and row["q"] is not None:
        return float(row["q"])

    row = db.execute(text("""
        -- 2) Literal category fallback
        SELECT SUM(quantity) AS q
        FROM scenario_boq_items
        WHERE scenario_id=:sid AND (UPPER(category)='AN' OR category='Ammonium Nitrate')
    """), {"sid": scenario_id}).mappings().first()
    if row and row["q"] is not None:
        return float(row["q"])

    return 1.0  # minimal fallback; prefer to drive from BOQ


def _load_policy_components(db: Session, policy_id: int) -> List[Tuple[int, float, Optional[float]]]:
    """
    Returns a list of (index_series_id, weight_pct, base_index_value?).
    """
    rows = db.execute(text("""
        SELECT index_series_id, weight_pct, base_index_value
        FROM escalation_policy_components
        WHERE policy_id=:pid
        ORDER BY id ASC
    """), {"pid": policy_id}).fetchall()
    return [(int(r[0]), float(r[1]), (None if r[2] is None else float(r[2]))) for r in rows]


def _index_point_on_or_before(db: Session, series_id: int, yyyymm: int) -> Optional[float]:
    """
    Returns the index value for given series on the month, or the latest before it.
    """
    y, m = int_to_ym(yyyymm)
    row = db.execute(text("""
        SELECT value FROM index_points
        WHERE series_id=:sid
          AND (year < :y OR (year=:y AND month<=:m))
        ORDER BY year DESC, month DESC
        LIMIT 1
    """), {"sid": series_id, "y": y, "m": m}).mappings().first()
    return None if not row else float(row["value"])


def _compute_rnf_multipliers(db: Session, policy_id: Optional[int], start_yyyymm: int, months: int, frequency: str="annual") -> List[float]:
    """
    Compute monthly multipliers from a weighted index basket policy.
    Base = basket value at contract start_yyyymm (or per-component base_index_value if provided).
    Frequency 'annual' means multiplier only changes at each 12M boundary per Excel parity.
    """
    if not policy_id:
        return [1.0] * months

    comps = _load_policy_components(db, policy_id)
    if not comps:
        return [1.0] * months

    # Basket base value at start
    base_vals: List[float] = []
    for series_id, weight_pct, base_override in comps:
        base = base_override if base_override is not None else _index_point_on_or_before(db, series_id, start_yyyymm)
        if base is None or base == 0:
            base = 1.0
        base_vals.append(base)

    def basket_value(yyyymm: int) -> float:
        v = 0.0
        for (series_id, weight_pct, base_override), base_val in zip(comps, base_vals):
            cur = _index_point_on_or_before(db, series_id, yyyymm) or base_val
            v += (cur / base_val) * (weight_pct / 100.0)
        return v

    months_list = ym_range(start_yyyymm, months)

    if frequency.lower().startswith("annual"):
        # Lock each 12-month block to the first month's basket value in that block
        multipliers: List[float] = []
        for i, _ in enumerate(months_list):
            block = (i // 12) * 12
            anchor_yyyymm = months_list[block]
            b = basket_value(anchor_yyyymm)
            multipliers.append(b)
        return multipliers

    # Fallback: fully monthly (changes each month)
    return [basket_value(yyyymm) for yyyymm in months_list]


# --------------------------- Core computation -----------------------------

def compute_an_facts(db: Session, scenario_id: int,
                     escalation_policy_id: Optional[int]=None,
                     frequency: str="annual") -> Tuple[List[FactRow], List[FactRow], List[FactRow]]:
    """
    Compute AN monthly facts and produce sheet-aware series for:
      - c.Sales-AN (monthly)
      - oQ.Finance-AN (quarterly aggregate)
      - oA.Finance-AN (annual aggregate)

    Returns: (facts_monthly, facts_quarterly, facts_annual)
    """
    start_yyyymm, months = _get_scenario_horizon(db, scenario_id)
    sales_price, unit_cogs, freight_rev_u, mgmt_fee_u, freight_cost_u = _get_an_base_prices(db, scenario_id)
    qty = _get_monthly_quantity(db, scenario_id)

    # Policy resolution: prefer function arg else scenario default
    if not escalation_policy_id:
        row = db.execute(text("SELECT default_price_escalation_policy_id AS pid FROM scenarios WHERE id=:sid"),
                         {"sid": scenario_id}).mappings().first()
        escalation_policy_id = int(row["pid"]) if row and row["pid"] else None

    multipliers = _compute_rnf_multipliers(db, escalation_policy_id, start_yyyymm, months, frequency)

    # Month-by-month series
    facts_m: List[FactRow] = []
    yyyymms = ym_range(start_yyyymm, months)

    for i, yyyymm in enumerate(yyyymms):
        mult = multipliers[i]
        # Revenue components (unit * qty * mult)
        sales_rev   = qty * sales_price   * mult
        freight_rev = qty * freight_rev_u * mult
        mgmt_rev    = qty * mgmt_fee_u    * mult
        total_rev   = sales_rev + freight_rev + mgmt_rev

        # Costs
        cogs_ex_tax = qty * unit_cogs       * mult
        freight_cost= qty * freight_cost_u  * mult

        gp = total_rev - (cogs_ex_tax + freight_cost)

        # c.Sales-AN
        for series, val in [
            ("sales_revenue", sales_rev),
            ("freight_revenue", freight_rev),
            ("mgmt_fee_revenue", mgmt_rev),
            ("total_revenue", total_rev),
        ]:
            facts_m.append(FactRow("c.Sales-AN", "AN", yyyymm, series, float(round(val, 6))))

        # finance base series (monthly) for aggregation
        for series, val in [
            ("revenue", total_rev),
            ("cogs_ex_tax", cogs_ex_tax),
            ("freight_cost", freight_cost),
            ("gp", gp),
        ]:
            facts_m.append(FactRow("o.base-AN", "AN", yyyymm, series, float(round(val, 6))))

    # Aggregations
    def agg(series_filter: Iterable[str], period: str) -> List[FactRow]:
        out: List[FactRow] = []
        bucket: Dict[Tuple[int, int, str], float] = {}  # (year, quarter|12, series) -> sum
        for fr in facts_m:
            if fr.sheet_code != "o.base-AN" or fr.series not in series_filter:
                continue
            y, m = int_to_ym(fr.yyyymm)
            if period == "quarter":
                q = (m - 1) // 3 + 1
                key = (y, q, fr.series)
            elif period == "annual":
                key = (y, 12, fr.series)
            else:
                raise ValueError("period must be 'quarter' or 'annual'")
            bucket[key] = bucket.get(key, 0.0) + fr.value

        if period == "quarter":
            sheet = "oQ.Finance-AN"
        else:
            sheet = "oA.Finance-AN"

        for (y, q_or_12, series), val in bucket.items():
            if period == "quarter":
                yyyymm_key = y * 100 + (q_or_12 * 3)  # store at quarter-end month (03,06,09,12)
            else:
                yyyymm_key = y * 100 + 12
            out.append(FactRow(sheet, "AN", yyyymm_key, series, float(round(val, 6))))
        return out

    finance_series = ("revenue", "cogs_ex_tax", "freight_cost", "gp")
    facts_q = agg(finance_series, "quarter")
    facts_a = agg(finance_series, "annual")

    # Filter out the helper sheet
    facts_m = [fr for fr in facts_m if fr.sheet_code != "o.base-AN"]

    return facts_m, facts_q, facts_a


# ------------------------------- Persist API ------------------------------

def _has_series_column(db: Session) -> bool:
    """Detect if engine_facts_monthly has a 'series' column (schema variant support)."""
    cols = db.execute(text("PRAGMA table_info('engine_facts_monthly')")).fetchall()
    colnames = { (c[1] if isinstance(c, (list, tuple)) else c["name"]) for c in cols }
    return "series" in { str(n) for n in colnames }


def persist_an_facts(db: Session, run_id: int, scenario_id: int,
                     facts_m: List[FactRow], facts_q: List[FactRow], facts_a: List[FactRow]) -> None:
    """
    Idempotent persist of AN facts using series-aware upsert.
    Requires 'series' column (migration 20251016).

    - Writes/updates a single row per (run_id, sheet_code, category_code, yyyymm, series).
    - Does NOT rely on created_at; DB default/trigger may populate it if present.
    """
    all_facts = facts_m + facts_q + facts_a

    # Schema guard
    if not _has_series_column(db):
        raise RuntimeError(
            "engine_facts_monthly lacks 'series' column. Please run migration 20251016_add_series_to_engine_facts."
        )

    bind = db.get_bind()
    if bind is None:
        # Fallback: use session connection
        bind = db.connection().engine

    with bind.begin() as cx:
        for fr in all_facts:
            # Normalize and validate
            sheet_code = str(fr["sheet_code"])
            category_code = str(fr["category_code"])
            yyyymm = str(fr["yyyymm"])
            series = str(fr["series"])
            value = fr["value"]
            upsert_fact(
                cx,
                scenario_id=scenario_id,
                run_id=run_id,
                sheet_code=sheet_code,
                category_code=category_code,
                yyyymm=yyyymm,
                series=series,
                value=value,
            )
