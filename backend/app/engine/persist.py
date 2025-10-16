# Path: backend/app/engine/persist.py
"""
Engine persistence helpers for series-aware facts.

Purpose
-------
Provide safe, idempotent upsert helpers to persist monthly facts with the new
`series` dimension (revenue | cogs | gp) under `engine_facts_monthly`.

This module does NOT compute business values; it only persists what the engine
calculates. It ensures we write/replace a single row per
(run_id, sheet_code, category_code, yyyymm, series).

Usage
-----
from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from backend.app.services.engine_persist import (
    Series, upsert_fact, persist_triplet, persist_many
)

with engine.begin() as cx:
    persist_triplet(
        cx,
        scenario_id=1, run_id=123,
        sheet_code="c.Sales-AN", category_code="AN",
        yyyymm="202601",
        revenue=12345.67, cogs=8901.23, gp=None  # gp will be computed as revenue - cogs
    )

Design Notes
------------
- No schema assumptions beyond existing columns:
  scenario_id, run_id, sheet_code, category_code, yyyymm, series, value
- Relies on UNIQUE index over (run_id, sheet_code, category_code, yyyymm, series).
- Uses INSERT ... ON CONFLICT ... DO UPDATE to be idempotent.
- Computes GP if not provided and rev/cogs are present.
"""

from __future__ import annotations
from dataclasses import dataclass
from decimal import Decimal
from typing import Iterable, Mapping, Optional, Sequence, Tuple, Union

from sqlalchemy.engine import Connection
from sqlalchemy import text

Number = Union[int, float, Decimal]

# -------------------------
# Public API
# -------------------------

class Series:
    REVENUE = "revenue"
    COGS = "cogs"
    GP = "gp"

def upsert_fact(
    cx: Connection,
    *,
    scenario_id: int,
    run_id: int,
    sheet_code: str,
    category_code: str,
    yyyymm: str,
    series: str,
    value: Number,
) -> None:
    """
    Idempotent upsert of a single (yyyymm, series, value) fact row.
    """
    _validate_yyyymm(yyyymm)
    val = _to_decimal(value)
    cx.execute(
        text("""
            INSERT INTO engine_facts_monthly
                (scenario_id, run_id, sheet_code, category_code, yyyymm, series, value)
            VALUES
                (:scenario_id, :run_id, :sheet_code, :category_code, :yyyymm, :series, :value)
            ON CONFLICT(run_id, sheet_code, category_code, yyyymm, series)
            DO UPDATE SET
                value = excluded.value,
                scenario_id = excluded.scenario_id
        """),
        {
            "scenario_id": scenario_id,
            "run_id": run_id,
            "sheet_code": sheet_code,
            "category_code": category_code,
            "yyyymm": yyyymm,
            "series": series,
            "value": str(val),
        },
    )

def persist_triplet(
    cx: Connection,
    *,
    scenario_id: int,
    run_id: int,
    sheet_code: str,
    category_code: str,
    yyyymm: str,
    revenue: Optional[Number] = None,
    cogs: Optional[Number] = None,
    gp: Optional[Number] = None,
    compute_gp_if_missing: bool = True,
) -> Tuple[Optional[Decimal], Optional[Decimal], Optional[Decimal]]:
    """
    Persist revenue/cogs/gp for a month in one go (any subset allowed).
    If gp is missing and compute_gp_if_missing=True, it will persist gp = revenue - cogs
    only when both revenue and cogs are provided.
    Returns the decimals actually written (rev, cogs, gp) — None if skipped.
    """
    _validate_yyyymm(yyyymm)

    rev_d = _to_decimal(revenue) if revenue is not None else None
    cogs_d = _to_decimal(cogs) if cogs is not None else None
    gp_d = _to_decimal(gp) if gp is not None else None

    if gp_d is None and compute_gp_if_missing and (rev_d is not None) and (cogs_d is not None):
        gp_d = rev_d - cogs_d

    if rev_d is not None:
        upsert_fact(cx,
            scenario_id=scenario_id, run_id=run_id,
            sheet_code=sheet_code, category_code=category_code,
            yyyymm=yyyymm,
            series=Series.REVENUE, value=rev_d
        )

    if cogs_d is not None:
        upsert_fact(cx,
            scenario_id=scenario_id, run_id=run_id,
            sheet_code=sheet_code, category_code=category_code,
            yyyymm=yyyymm,
            series=Series.COGS, value=cogs_d
        )

    if gp_d is not None:
        upsert_fact(cx,
            scenario_id=scenario_id, run_id=run_id,
            sheet_code=sheet_code, category_code=category_code,
            yyyymm=yyyymm,
            series=Series.GP, value=gp_d
        )

    return rev_d, cogs_d, gp_d

def persist_many(
    cx: Connection,
    rows: Iterable[Mapping[str, object]],
    *,
    default_sheet: Optional[str] = None,
    default_category: Optional[str] = None,
    compute_gp_if_missing: bool = True,
) -> int:
    """
    Batch persist. Each row mapping can contain:
      scenario_id (int), run_id (int), yyyymm (str, YYYYMM),
      sheet_code (str), category_code (str),
      revenue (num, optional), cogs (num, optional), gp (num, optional).

    Returns number of rows (months) processed.
    """
    count = 0
    for r in rows:
        scenario_id = int(r["scenario_id"])
        run_id = int(r["run_id"])
        yyyymm = str(r["yyyymm"])
        sheet_code = str(r.get("sheet_code") or default_sheet or "")
        category_code = str(r.get("category_code") or default_category or "")
        if not sheet_code or not category_code:
            raise ValueError("sheet_code and category_code are required (explicitly or via defaults).")

        revenue = r.get("revenue")
        cogs = r.get("cogs")
        gp = r.get("gp")

        persist_triplet(
            cx,
            scenario_id=scenario_id, run_id=run_id,
            sheet_code=sheet_code, category_code=category_code,
            yyyymm=yyyymm,
            revenue=revenue, cogs=cogs, gp=gp,
            compute_gp_if_missing=compute_gp_if_missing,
        )
        count += 1
    return count

# -------------------------
# Internal helpers
# -------------------------

def _validate_yyyymm(yyyymm: str) -> None:
    if len(yyyymm) != 6 or not yyyymm.isdigit():
        raise ValueError(f"yyyymm must be 'YYYYMM', got: {yyyymm!r}")
    year = int(yyyymm[:4])
    month = int(yyyymm[4:])
    if month < 1 or month > 12:
        raise ValueError(f"yyyymm month must be 01..12, got: {yyyymm}")

def _to_decimal(x: Number) -> Decimal:
    # Convert via str to avoid float artifacts
    return Decimal(str(x))


def persist_records(
    cx,
    rows,
    *,
    scenario_id: int,
    run_id: int,
):
    """
    Persist list of FactRow-like dicts where each row has:
      sheet_code, category_code, yyyymm, series, value
    """
    for fr in rows:
        upsert_fact(
            cx,
            scenario_id=scenario_id,
            run_id=run_id,
            sheet_code=str(fr["sheet_code"]),
            category_code=str(fr["category_code"]),
            yyyymm=str(fr["yyyymm"]),
            series=str(fr["series"]),
            value=fr["value"],
        )
