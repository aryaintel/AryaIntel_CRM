# backend/app/api/service_pricing.py
from pathlib import Path
from decimal import Decimal, getcontext
import sqlite3
from fastapi import APIRouter, HTTPException, Query

getcontext().prec = 28
router = APIRouter(prefix="/api/services", tags=["pricing"])

DB_PATH = Path(__file__).resolve().parents[2] / "app.db"


# ---------- DB ----------
def _db() -> sqlite3.Connection:
    cx = sqlite3.connect(str(DB_PATH))
    cx.row_factory = sqlite3.Row
    cx.execute("PRAGMA foreign_keys = ON;")
    return cx


# ---------- Utils ----------
def _parse_ym(ym: str) -> tuple[int, int]:
    try:
        y, m = ym.split("-")
        return int(y), int(m)
    except Exception:
        raise HTTPException(400, "ym must be 'YYYY-MM'")


def _months_between(y0: int, m0: int, y1: int, m1: int) -> int:
    """Inclusive-exclusive: from (y0,m0) up to (y1,m1)."""
    return (y1 - y0) * 12 + (m1 - m0)


def _index_value(cx: sqlite3.Connection, series_id: int, year: int, month: int) -> Decimal:
    row = cx.execute(
        "SELECT value FROM index_points WHERE series_id=? AND year=? AND month=?",
        (series_id, year, month),
    ).fetchone()
    if not row:
        raise HTTPException(409, f"missing index point for series_id={series_id} at {year}-{month:02d}")
    return Decimal(str(row["value"]))


# ---------- Formulation ----------
def _formulation_factor(cx: sqlite3.Connection, formulation_id: int, year: int, month: int) -> Decimal:
    comps = cx.execute(
        "SELECT index_series_id, weight_pct, base_index_value "
        "FROM formulation_components WHERE formulation_id=?",
        (formulation_id,),
    ).fetchall()
    if not comps:
        raise HTTPException(409, "formulation has no components")

    factor = Decimal("0")
    for c in comps:
        base = c["base_index_value"]
        if base is None:
            raise HTTPException(409, "base_index_value is NULL (set Base Ref)")
        curr = _index_value(cx, c["index_series_id"], year, month)
        ratio = curr / Decimal(str(base))
        w = Decimal(str(c["weight_pct"])) / Decimal("100")
        factor += w * ratio
    return factor


# ---------- Escalation ----------
def _policy_row(cx: sqlite3.Connection, policy_id: int) -> sqlite3.Row:
    row = cx.execute(
        "SELECT id, name, scope, rate_pct, index_series_id, start_year, start_month, "
        "       cap_pct, floor_pct, frequency, compounding "
        "FROM escalation_policies WHERE id=?",
        (policy_id,),
    ).fetchone()
    if not row:
        raise HTTPException(404, "escalation policy not found")
    return row


def _blend_index_ratio(
    cx: sqlite3.Connection,
    policy_id: int,
    target_y: int,
    target_m: int,
    base_y: int,
    base_m: int,
) -> Decimal:
    """
    Karışım bileşenleri varsa onları, yoksa policy.index_series_id'yi kullanarak
    (target/base) oranını hesaplar. Bileşendeki base_index_value varsa onu baz alır.
    """
    comps = cx.execute(
        "SELECT index_series_id, weight_pct, base_index_value "
        "FROM escalation_policy_components WHERE policy_id=?",
        (policy_id,),
    ).fetchall()

    # Karışım yoksa policy.index_series_id tek başına %100
    if not comps:
        idx_id_row = cx.execute(
            "SELECT index_series_id FROM escalation_policies WHERE id=?",
            (policy_id,),
        ).fetchone()
        idx_id = idx_id_row["index_series_id"] if idx_id_row else None
        if idx_id is None:
            # Ne oran ne endeks tanımlı → 1.0 (etkisiz) sayalım
            return Decimal("1")
        target = _index_value(cx, idx_id, target_y, target_m)
        base = _index_value(cx, idx_id, base_y, base_m)
        if base == 0:
            raise HTTPException(409, "base index value is zero")
        return (target / base).quantize(Decimal("0.0000001"))

    # Karışım: ağırlıklı ortalama oran
    total = Decimal("0")
    for c in comps:
        idx_id = c["index_series_id"]
        w = Decimal(str(c["weight_pct"])) / Decimal("100")
        target = _index_value(cx, idx_id, target_y, target_m)
        if c["base_index_value"] is not None:
            base = Decimal(str(c["base_index_value"]))
        else:
            base = _index_value(cx, idx_id, base_y, base_m)
        if base == 0:
            raise HTTPException(409, "base index value is zero (component)")
        total += w * (target / base)
    return total.quantize(Decimal("0.0000001"))


def _apply_cap_floor(multiplier: Decimal, cap_pct, floor_pct) -> Decimal:
    """
    cap/floor yüzde olarak veriliyor (örn 15 → %15). Bunları toplam çarpana uygular.
    cap=floor None ise dokunulmaz.
    """
    if cap_pct is None and floor_pct is None:
        return multiplier

    def pct_to_factor(p):
        # %15 → 1.15 , %-10 → 0.90
        return (Decimal("1") + (Decimal(str(p)) / Decimal("100")))

    if cap_pct is not None:
        cap_f = pct_to_factor(cap_pct)
        if multiplier > cap_f:
            multiplier = cap_f
    if floor_pct is not None:
        floor_f = pct_to_factor(floor_pct)
        if multiplier < floor_f:
            multiplier = floor_f
    return multiplier


def _escalation_multiplier(cx: sqlite3.Connection, policy_id: int, target_y: int, target_m: int) -> Decimal:
    """
    Policy'ye göre toplam artış çarpanı. Policy iki yoldan çalışır:
      - rate_pct → frekansa göre periyot sayısı ile (compound ya da simple) artış
      - index_series / components → endeks oranı
    cap/floor sonunda uygulanır.
    """
    p = _policy_row(cx, policy_id)

    # 1) Oran bazlı
    if p["rate_pct"] is not None:
        rate = Decimal(str(p["rate_pct"])) / Decimal("100")
        start_y = int(p["start_year"])
        start_m = int(p["start_month"])
        freq = (p["frequency"] or "annual").lower()
        comp = (p["compounding"] or "compound").lower()

        months = _months_between(start_y, start_m, target_y, target_m)
        if months <= 0:
            mult = Decimal("1")
        else:
            if freq == "monthly":
                periods = months
            elif freq == "quarterly":
                periods = months // 3
            else:  # annual
                periods = months // 12

            if periods <= 0:
                mult = Decimal("1")
            else:
                if comp == "simple":
                    mult = (Decimal("1") + rate * Decimal(periods))
                else:  # compound
                    one_plus = (Decimal("1") + rate)
                    mult = one_plus ** Decimal(periods)

        mult = _apply_cap_floor(mult, p["cap_pct"], p["floor_pct"])
        return mult.quantize(Decimal("0.0000001"))

    # 2) Endeks bazlı
    has_components = cx.execute(
        "SELECT 1 FROM escalation_policy_components WHERE policy_id=? LIMIT 1", (policy_id,)
    ).fetchone()
    if p["index_series_id"] is not None or has_components:
        start_y = int(p["start_year"])
        start_m = int(p["start_month"])
        mult = _blend_index_ratio(cx, policy_id, target_y, target_m, start_y, start_m)
        mult = _apply_cap_floor(mult, p["cap_pct"], p["floor_pct"])
        return mult.quantize(Decimal("0.0000001"))

    # Hiçbir kural yoksa etkisiz
    return Decimal("1")


# ---------- Shared preview core ----------
def _build_preview_payload(
    *,
    ym: str,
    base_price: Decimal,
    factor: Decimal,
    esc_mult: Decimal,
    qty: Decimal,
    currency: str | None,
    name: str,
    row_id: int,
    policy_id: int | None,
    source: str,
) -> dict:
    unit_base = (base_price * factor)
    unit_price = (unit_base * esc_mult).quantize(Decimal("0.01"))
    line_total = (unit_price * qty).quantize(Decimal("0.01"))

    return {
        "id": row_id,
        "name": name,
        "period": ym,
        "currency": currency,
        "base_price": str(base_price),
        "formulation_factor": str(factor),
        "escalation_multiplier": str(esc_mult),
        "unit_price": str(unit_price),
        "quantity": str(qty),
        "line_total": str(line_total),
        "policy_id": int(policy_id) if policy_id is not None else None,
        "source": source,
    }


# ---------- Endpoints ----------
@router.get("/{service_id}/price-preview")
def service_price_preview(service_id: int, ym: str = Query(..., description="YYYY-MM")):
    y, m = _parse_ym(ym)
    with _db() as cx:
        row = cx.execute(
            """
            SELECT
                s.id,
                s.service_name,
                s.quantity,
                s.currency,
                s.formulation_id,
                s.price_escalation_policy_id,
                sc.default_price_escalation_policy_id,
                f.base_price,
                f.base_currency
            FROM scenario_services s
            LEFT JOIN product_formulations f ON s.formulation_id = f.id
            LEFT JOIN scenarios sc ON sc.id = s.scenario_id
            WHERE s.id = ?
            """,
            (service_id,),
        ).fetchone()

        if not row:
            raise HTTPException(404, "service not found")
        if row["formulation_id"] is None:
            raise HTTPException(409, "service has no formulation_id")

        # 1) Formülasyon faktörü
        factor = _formulation_factor(cx, row["formulation_id"], y, m)

        # 2) Escalation multiplier (varsa)
        policy_id = row["price_escalation_policy_id"] or row["default_price_escalation_policy_id"]
        esc_mult = Decimal("1")
        if policy_id:
            esc_mult = _escalation_multiplier(cx, int(policy_id), y, m)

        # 3) Fiyatlar & çıktı
        base_price = Decimal(str(row["base_price"] or 0))
        qty = Decimal(str(row["quantity"] or 1))
        currency = row["base_currency"] or row["currency"]

        return _build_preview_payload(
            ym=ym,
            base_price=base_price,
            factor=factor,
            esc_mult=esc_mult,
            qty=qty,
            currency=currency,
            name=row["service_name"],
            row_id=row["id"],
            policy_id=int(policy_id) if policy_id else None,
            source="service",
        )


@router.get("/boq/{boq_id}/price-preview")
def boq_price_preview(boq_id: int, ym: str = Query(..., description="YYYY-MM")):
    """
    BOQ satırı için fiyat önizleme.
    Satır bazında policy_id varsa onu, yoksa senaryonun default policy'sini uygular.
    """
    y, m = _parse_ym(ym)
    with _db() as cx:
        row = cx.execute(
            """
            SELECT
                b.id,
                b.item_name,
                b.quantity,
                NULL AS currency,          -- BOQ satırında genelde currency yok; formülasyondan alınır
                b.formulation_id,
                f.base_price,
                f.base_currency,
                b.price_escalation_policy_id,
                sc.default_price_escalation_policy_id
            FROM scenario_boq_items b
            LEFT JOIN product_formulations f ON b.formulation_id = f.id
            LEFT JOIN scenarios sc ON sc.id = b.scenario_id
            WHERE b.id = ?
            """,
            (boq_id,),
        ).fetchone()

        if not row:
            raise HTTPException(404, "boq line not found")
        if row["formulation_id"] is None:
            raise HTTPException(409, "boq has no formulation_id")

        # 1) Formülasyon faktörü
        factor = _formulation_factor(cx, row["formulation_id"], y, m)

        # 2) Escalation multiplier (varsa)
        policy_id = row["price_escalation_policy_id"] or row["default_price_escalation_policy_id"]
        esc_mult = Decimal("1")
        if policy_id:
            esc_mult = _escalation_multiplier(cx, int(policy_id), y, m)

        # 3) Fiyatlar & çıktı
        base_price = Decimal(str(row["base_price"] or 0))
        qty = Decimal(str(row["quantity"] or 1))
        currency = row["base_currency"] or row["currency"]

        return _build_preview_payload(
            ym=ym,
            base_price=base_price,
            factor=factor,
            esc_mult=esc_mult,
            qty=qty,
            currency=currency,
            name=row["item_name"],
            row_id=row["id"],
            policy_id=int(policy_id) if policy_id else None,
            source="boq",
        )


# ---------- Scenario-level previews ----------
def _service_row_preview(cx: sqlite3.Connection, row: sqlite3.Row, y: int, m: int, ym: str) -> dict:
    """scenario_services satırını fiyatla."""
    if row["formulation_id"] is None:
        raise HTTPException(409, f"service id={row['id']} has no formulation_id")

    factor = _formulation_factor(cx, row["formulation_id"], y, m)

    policy_id = row["price_escalation_policy_id"] or row["default_price_escalation_policy_id"]
    esc_mult = Decimal("1")
    if policy_id:
        esc_mult = _escalation_multiplier(cx, int(policy_id), y, m)

    base_price = Decimal(str(row["base_price"] or 0))
    qty = Decimal(str(row["quantity"] or 1))
    currency = row["base_currency"] or row["currency"]
    return _build_preview_payload(
        ym=ym,
        base_price=base_price,
        factor=factor,
        esc_mult=esc_mult,
        qty=qty,
        currency=currency,
        name=row["service_name"],
        row_id=row["id"],
        policy_id=int(policy_id) if policy_id else None,
        source="service",
    )


def _boq_row_preview(cx: sqlite3.Connection, row: sqlite3.Row, y: int, m: int, ym: str) -> dict:
    """scenario_boq_items satırını fiyatla."""
    if row["formulation_id"] is None:
        raise HTTPException(409, f"boq id={row['id']} has no formulation_id")

    factor = _formulation_factor(cx, row["formulation_id"], y, m)

    policy_id = row["price_escalation_policy_id"] or row["default_price_escalation_policy_id"]
    esc_mult = Decimal("1")
    if policy_id:
        esc_mult = _escalation_multiplier(cx, int(policy_id), y, m)

    base_price = Decimal(str(row["base_price"] or 0))
    qty = Decimal(str(row["quantity"] or 1))
    currency = row["base_currency"] or row["currency"]
    return _build_preview_payload(
        ym=ym,
        base_price=base_price,
        factor=factor,
        esc_mult=esc_mult,
        qty=qty,
        currency=currency,
        name=row["item_name"],
        row_id=row["id"],
        policy_id=int(policy_id) if policy_id else None,
        source="boq",
    )


# ... (dosyanın üst kısmı aynı)

@router.get("/scenarios/{scenario_id}/price-preview")
def scenario_price_preview(
    scenario_id: int,
    ym: str = Query(..., description="YYYY-MM"),
    strict: int = Query(1, description="1=error on missing data, 0=skip and collect issues"),
):
    """
    Verilen ay için senaryodaki SERVICE + BOQ satırlarını fiyatla ve topla.
    strict=0 ise hatalı satırları atlayıp 'issues' altında raporlar.
    """
    y, m = _parse_ym(ym)
    try:
        with _db() as cx:
            svcs = cx.execute(
                """
                SELECT s.id, s.service_name, s.quantity, s.currency, s.formulation_id,
                       s.price_escalation_policy_id,
                       sc.default_price_escalation_policy_id,
                       f.base_price, f.base_currency
                FROM scenario_services s
                LEFT JOIN product_formulations f ON s.formulation_id = f.id
                LEFT JOIN scenarios sc ON sc.id = s.scenario_id
                WHERE s.scenario_id = ?
                """,
                (scenario_id,),
            ).fetchall()

            boqs = cx.execute(
                """
                SELECT b.id, b.item_name, b.quantity, NULL as currency, b.formulation_id,
                       f.base_price, f.base_currency,
                       b.price_escalation_policy_id,
                       sc.default_price_escalation_policy_id
                FROM scenario_boq_items b
                LEFT JOIN product_formulations f ON b.formulation_id = f.id
                LEFT JOIN scenarios sc ON sc.id = b.scenario_id
                WHERE b.scenario_id = ?
                """,
                (scenario_id,),
            ).fetchall()

            lines, issues = [], []
            total = Decimal("0")

            def _accumulate(make_preview, row):
                nonlocal total
                try:
                    p = make_preview(cx, row, y, m, ym)
                    lines.append(p)
                    # güvenli cast: str(...) ile Decimal'ı her durumda doğru kur
                    total += Decimal(str(p["line_total"]))
                except HTTPException as e:
                    if strict:
                        # aynen yukarı fırlat → 404/409 gibi anlamlı bir kod döner
                        raise
                    src = "service" if make_preview is _service_row_preview else "boq"
                    issues.append({"id": row["id"], "source": src, "error": e.detail})
                except Exception as e:
                    if strict:
                        raise HTTPException(400, f"unexpected error while pricing: {e}")
                    src = "service" if make_preview is _service_row_preview else "boq"
                    issues.append({"id": row["id"], "source": src, "error": str(e)})

            for r in svcs:
                _accumulate(_service_row_preview, r)
            for r in boqs:
                _accumulate(_boq_row_preview, r)

            return {
                "scenario_id": scenario_id,
                "period": ym,
                "total": str(total.quantize(Decimal("0.01"))),
                "lines": lines,
                "issues": issues,
            }
    except HTTPException:
        # HTTPException’ları olduğu gibi döndür (409/404 vs.)
        raise
    except Exception as e:
        # 500 yerine kontrollü 400 dön: debug kolaylaşır
        raise HTTPException(400, f"scenario_price_preview failed: {e}")


@router.get("/scenarios/{scenario_id}/price-range")
def scenario_price_range(
    scenario_id: int,
    from_: str = Query(..., alias="from", description="YYYY-MM (inclusive)"),
    to: str = Query(..., description="YYYY-MM (exclusive)"),
    strict: int = Query(1, description="1=error on missing data, 0=skip and collect issues"),
):
    """
    from (dâhil) → to (hariç) arasındaki her ay için aylık toplamları ve genel toplamı döndürür.
    """
    y0, m0 = _parse_ym(from_)
    y1, m1 = _parse_ym(to)
    months = _months_between(y0, m0, y1, m1)
    if months <= 0:
        raise HTTPException(400, "'to' must be after 'from'")

    months_out = []
    grand_total = Decimal("0")
    all_issues = []

    for k in range(months):
        yy = y0 + (m0 - 1 + k) // 12
        mm = (m0 - 1 + k) % 12 + 1
        ym = f"{yy:04d}-{mm:02d}"
        try:
            res = scenario_price_preview(scenario_id=scenario_id, ym=ym, strict=strict)  # reuse
        except HTTPException as e:
            if strict:
                raise
            all_issues.append({"period": ym, "error": e.detail})
            continue

        months_out.append({"period": ym, "total": res["total"]})
        grand_total += Decimal(res["total"])
        if res.get("issues"):
            all_issues.extend([{"period": ym, **x} for x in res["issues"]])

    return {
        "scenario_id": scenario_id,
        "from": from_,
        "to": to,
        "months": months_out,
        "grand_total": str(grand_total.quantize(Decimal("0.01"))),
        "issues": all_issues,
    }
