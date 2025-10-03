# backend/app/api/escalation_runtime.py
from __future__ import annotations
from dataclasses import dataclass
from decimal import Decimal, getcontext
from pathlib import Path
import sqlite3
from typing import Optional, List, Tuple

getcontext().prec = 28
DB_PATH = Path(__file__).resolve().parents[2] / "app.db"

def _db() -> sqlite3.Connection:
    cx = sqlite3.connect(str(DB_PATH))
    cx.row_factory = sqlite3.Row
    cx.execute("PRAGMA foreign_keys = ON;")
    return cx

@dataclass
class Policy:
    id: int
    scope: str  # "price", "cogs", "both"
    start_year: int
    start_month: int
    frequency: str  # "annual" | "quarterly" | "monthly"
    compounding: str  # "compound" | "simple"
    rate_pct: Optional[Decimal]  # nullable
    cap_pct: Optional[Decimal]
    floor_pct: Optional[Decimal]

@dataclass
class PolicyComponent:
    index_series_id: int
    weight_pct: Decimal
    base_index_value: Optional[Decimal]

def _months_between(y1: int, m1: int, y2: int, m2: int) -> int:
    return (y2 - y1) * 12 + (m2 - m1)

def _periods_between(freq: str, months: int) -> int:
    if months <= 0:
        return 0
    if freq == "annual":
        return months // 12
    if freq == "quarterly":
        return months // 3
    if freq == "monthly":
        return months
    return months // 12  # fallback

def _load_policy(cx: sqlite3.Connection, policy_id: int) -> Tuple[Policy, List[PolicyComponent]]:
    p = cx.execute("""
        SELECT id, scope, start_year, start_month, frequency, compounding,
               rate_pct, cap_pct, floor_pct
        FROM escalation_policies WHERE id=?
    """, (policy_id,)).fetchone()
    if not p:
        raise ValueError("policy not found")

    comps = cx.execute("""
        SELECT index_series_id, weight_pct, base_index_value
        FROM escalation_policy_components
        WHERE policy_id=?
        ORDER BY id
    """, (policy_id,)).fetchall()

    return Policy(
        id=p["id"],
        scope=p["scope"],
        start_year=p["start_year"],
        start_month=p["start_month"],
        frequency=p["frequency"],
        compounding=p["compounding"],
        rate_pct=Decimal(str(p["rate_pct"])) if p["rate_pct"] is not None else None,
        cap_pct=Decimal(str(p["cap_pct"])) if p["cap_pct"] is not None else None,
        floor_pct=Decimal(str(p["floor_pct"])) if p["floor_pct"] is not None else None,
    ), [
        PolicyComponent(
            index_series_id=row["index_series_id"],
            weight_pct=Decimal(str(row["weight_pct"])),
            base_index_value=Decimal(str(row["base_index_value"])) if row["base_index_value"] is not None else None,
        ) for row in comps
    ]

def _latest_index_value(cx: sqlite3.Connection, series_id: int, year: int, month: int) -> Optional[Decimal]:
    # mevcut ay (year, month) için değer arar; yoksa en yakın önceki aya döner
    row = cx.execute("""
        SELECT value FROM index_points
        WHERE series_id=? AND (year < ? OR (year = ? AND month <= ?))
        ORDER BY year DESC, month DESC
        LIMIT 1
    """, (series_id, year, year, month)).fetchone()
    return Decimal(str(row["value"])) if row else None

def _index_factor(cx: sqlite3.Connection, comps: List[PolicyComponent], year: int, month: int) -> Decimal:
    if not comps:
        return Decimal("1")
    # Ağırlıkları 100’e normalize ederek karışık endeks faktörü hesapla
    total_w = sum(c.weight_pct for c in comps)
    if total_w <= 0:
        return Decimal("1")

    weighted = Decimal("0")
    for c in comps:
        cur = _latest_index_value(cx, c.index_series_id, year, month)
        if cur is None:
            raise RuntimeError(f"missing index point for series_id={c.index_series_id} at {year}-{month:02d}")
        base = c.base_index_value if c.base_index_value is not None else cur  # base yoksa 1.00 yapma: cur/cur=1
        ratio = (cur / base) if base != 0 else Decimal("1")
        weighted += (c.weight_pct / total_w) * ratio
    return weighted  # 1.0 = değişim yok

def _cap_floor(value: Decimal, cap: Optional[Decimal], floor: Optional[Decimal]) -> Decimal:
    # cap/floor yüzdelik artışa uygulanır (örn 0.10 = %10)
    if cap is not None and value > (Decimal("1") + cap):
        return Decimal("1") + cap
    if floor is not None and value < (Decimal("1") + floor):
        return Decimal("1") + floor
    return value

def compute_escalation_factor(policy_id: int, year: int, month: int) -> Decimal:
    """
    Dönem (year,month) için politika faktörünü üretir.
    - Bileşik endeks bileşenleri varsa: karışım endeksi (cur/base)
    - Aksi halde: rate_pct + frekans + compounding ile büyütme
    cap/floor sonuca uygulanır.
    """
    with _db() as cx:
        pol, comps = _load_policy(cx, policy_id)

        # Öncelik: index tabanlı
        if comps:
            factor = _index_factor(cx, comps, year, month)
            return _cap_floor(factor, pol.cap_pct, pol.floor_pct)

        # Yoksa sabit oran
        if pol.rate_pct is None:
            return Decimal("1")

        months = _months_between(pol.start_year, pol.start_month, year, month)
        n = _periods_between(pol.frequency, months)
        if n <= 0:
            return Decimal("1")

        r = pol.rate_pct  # ör: 0.10 => %10
        if pol.frequency == "annual":
            per = r
        elif pol.frequency == "quarterly":
            per = r / Decimal("4")
        else:  # monthly
            per = r / Decimal("12")

        if pol.compounding == "compound":
            factor = (Decimal("1") + per) ** n
        else:
            factor = Decimal("1") + per * n

        return _cap_floor(factor, pol.cap_pct, pol.floor_pct)
