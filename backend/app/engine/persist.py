# relative path: backend/app/engine/persist.py
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
    Idempotent upsert of a single (yyyymm, series, value) fact row into engine_facts_monthly.

    Beklenen UNIQUE index: (run_id, sheet_code, category_code, yyyymm, series)
    """
    _validate_yyyymm(yyyymm)
    val = _to_decimal(value)
    cx.execute(
        text(
            """
            INSERT INTO engine_facts_monthly
                (scenario_id, run_id, sheet_code, category_code, yyyymm, series, value)
            VALUES
                (:scenario_id, :run_id, :sheet_code, :category_code, :yyyymm, :series, :value)
            ON CONFLICT(run_id, sheet_code, category_code, yyyymm, series)
            DO UPDATE SET
                value = excluded.value,
                scenario_id = excluded.scenario_id
            """
        ),
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
    Aylık tek satırda revenue/cogs/gp yazmak için yardımcı.
    gp yoksa ve compute_gp_if_missing=True ise, revenue ve cogs verilmişse gp = revenue - cogs yazılır.
    """
    _validate_yyyymm(yyyymm)

    rev_d = _to_decimal(revenue) if revenue is not None else None
    cogs_d = _to_decimal(cogs) if cogs is not None else None
    gp_d = _to_decimal(gp) if gp is not None else None

    if gp_d is None and compute_gp_if_missing and (rev_d is not None) and (cogs_d is not None):
        gp_d = rev_d - cogs_d

    if rev_d is not None:
        upsert_fact(
            cx,
            scenario_id=scenario_id,
            run_id=run_id,
            sheet_code=sheet_code,
            category_code=category_code,
            yyyymm=yyyymm,
            series=Series.REVENUE,
            value=rev_d,
        )

    if cogs_d is not None:
        upsert_fact(
            cx,
            scenario_id=scenario_id,
            run_id=run_id,
            sheet_code=sheet_code,
            category_code=category_code,
            yyyymm=yyyymm,
            series=Series.COGS,
            value=cogs_d,
        )

    if gp_d is not None:
        upsert_fact(
            cx,
            scenario_id=scenario_id,
            run_id=run_id,
            sheet_code=sheet_code,
            category_code=category_code,
            yyyymm=yyyymm,
            series=Series.GP,
            value=gp_d,
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
    Toplu persist. Her satır sözlüğünde şunlar bulunabilir:
      scenario_id, run_id, yyyymm, sheet_code, category_code, revenue?, cogs?, gp?
    """
    count = 0
    for r in rows:
        scenario_id = int(r["scenario_id"])
        run_id = int(r["run_id"])
        yyyymm = str(r["yyyymm"])
        sheet_code = str(r.get("sheet_code") or default_sheet or "")
        category_code = str(r.get("category_code") or default_category or "")
        if not sheet_code or not category_code:
            raise ValueError("sheet_code ve category_code zorunlu (ya açıkça ya da default ile).")

        revenue = r.get("revenue")
        cogs = r.get("cogs")
        gp = r.get("gp")

        persist_triplet(
            cx,
            scenario_id=scenario_id,
            run_id=run_id,
            sheet_code=sheet_code,
            category_code=category_code,
            yyyymm=yyyymm,
            revenue=revenue,
            cogs=cogs,
            gp=gp,
            compute_gp_if_missing=compute_gp_if_missing,
        )
        count += 1
    return count


def persist_records(
    cx: Connection,
    rows: Iterable[Mapping[str, object]],
    *,
    scenario_id: int,
    run_id: int,
) -> int:
    """
    Tam “series-aware” satırlar: her satırda sheet_code, category_code, yyyymm, series, value.
    """
    n = 0
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
        n += 1
    return n


# -------------------------
# Quarterly aggregation (oQ) — NEW
# -------------------------

def persist_quarterly_from_monthly(
    cx: Connection,
    *,
    scenario_id: int,
    run_id: int,
    src_sheet_prefix: str = "c.Sales-",
    dst_sheet_prefix: str = "oQ.Finance-",
    categories: Optional[Sequence[str]] = None,
) -> int:
    """
    Kaynak aylık fact'lerden (src_sheet_prefix) quarterly cash (oQ) üretir ve yazar.
    - series: revenue, cogs, gp
    - idempotent: aynı run_id/scenario_id + hedef prefix + kategori seti için önce siler, sonra yazar.
    - çeyrek sonu yyyymm: 03/06/09/12

    DÖNDÜRÜR: yazılan satır sayısı (insert + upsert toplamı).
    """
    # 1) Kategori seti yoksa kaynaktan keşfet
    if not categories:
        res = cx.execute(
            text(
                """
                SELECT DISTINCT category_code
                FROM engine_facts_monthly
                WHERE scenario_id = :scenario_id
                  AND run_id      = :run_id
                  AND sheet_code  LIKE :src_like
                """
            ),
            {"scenario_id": scenario_id, "run_id": run_id, "src_like": f"{src_sheet_prefix}%"},
        )
        categories = [row[0] for row in res.fetchall()]

    if not categories:
        return 0

    # 2) Hedefi idempotent kılmak için mevcut kayıtları sil (yalnız ilgili kategoriler)
    cx.execute(
        text(
            f"""
            DELETE FROM engine_facts_monthly
            WHERE scenario_id = :scenario_id
              AND run_id      = :run_id
              AND sheet_code  LIKE :dst_like
              AND category_code IN ({",".join([":c"+str(i) for i in range(len(categories))])})
            """
        ),
        {
            "scenario_id": scenario_id,
            "run_id": run_id,
            "dst_like": f"{dst_sheet_prefix}%",
            **{f"c{i}": cat for i, cat in enumerate(categories)},
        },
    )

    # 3) Aylıkları quarter'a topla (SQL tarafında quarter sonu hesaplayarak)
    res = cx.execute(
        text(
            f"""
            SELECT
              category_code,
              /* quarter end yyyymm */
              ((yyyymm / 100) * 100) +
              CASE
                WHEN (yyyymm % 100) BETWEEN 1 AND 3  THEN 3
                WHEN (yyyymm % 100) BETWEEN 4 AND 6  THEN 6
                WHEN (yyyymm % 100) BETWEEN 7 AND 9  THEN 9
                ELSE 12
              END AS q_end,
              series,
              SUM(value) AS sum_value
            FROM engine_facts_monthly
            WHERE scenario_id = :scenario_id
              AND run_id      = :run_id
              AND sheet_code  LIKE :src_like
              AND series IN (:rev, :cogs, :gp)
              AND category_code IN ({",".join([":k"+str(i) for i in range(len(categories))])})
            GROUP BY category_code, q_end, series
            ORDER BY category_code, q_end, series
            """
        ),
        {
            "scenario_id": scenario_id,
            "run_id": run_id,
            "src_like": f"{src_sheet_prefix}%",
            "rev": Series.REVENUE,
            "cogs": Series.COGS,
            "gp": Series.GP,
            **{f"k{i}": cat for i, cat in enumerate(categories)},
        },
    )

    # 4) Yaz (upsert) — hedef sheet: "oQ.Finance-<CAT>"
    written = 0
    for category_code, q_end, series, sum_value in res.fetchall():
        sheet_code = f"{dst_sheet_prefix}{category_code}"
        upsert_fact(
            cx,
            scenario_id=scenario_id,
            run_id=run_id,
            sheet_code=sheet_code,
            category_code=category_code,
            yyyymm=str(int(q_end)),
            series=series,
            value=sum_value,
        )
        written += 1
    return written


def persist_quarterly_from_sales(
    cx: Connection,
    *,
    scenario_id: int,
    run_id: int,
    categories: Optional[Sequence[str]] = None,
) -> int:
    """
    Kısayol: c.Sales-* kaynaklı quarterly persist (oQ.Finance-*) üretir.
    """
    return persist_quarterly_from_monthly(
        cx,
        scenario_id=scenario_id,
        run_id=run_id,
        src_sheet_prefix="c.Sales-",
        dst_sheet_prefix="oQ.Finance-",
        categories=categories,
    )


# -------------------------
# Internal helpers
# -------------------------

def _validate_yyyymm(yyyymm: str) -> None:
    if len(yyyymm) != 6 or not yyyymm.isdigit():
        raise ValueError(f"yyyymm 'YYYYMM' olmalı, gelen: {yyyymm!r}")
    year = int(yyyymm[:4])
    month = int(yyyymm[4:])
    if month < 1 or month > 12:
        raise ValueError(f"yyyymm ayı 01..12 arasında olmalı, gelen: {yyyymm}")


def _to_decimal(x: Number) -> Decimal:
    # float artefaktlarını engellemek için str üstünden çevir
    return Decimal(str(x))
