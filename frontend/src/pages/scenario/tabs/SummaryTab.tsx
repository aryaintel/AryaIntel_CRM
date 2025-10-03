// [REPLACE FILE] frontend/src/pages/scenario/tabs/SummaryTab.tsx
import React, { useEffect, useMemo, useState } from "react";
import { apiGet } from "../../../lib/api";

/** Props */
type Props = {
  scenarioId: number;
  startDate: string; // ISO (YYYY-MM-DD)
  months: number;    // horizon (e.g. 36)
};

/** Backend summary API types */
type SummaryItem = {
  ym: string;                // "YYYY-MM"
  revenue_boq: number;
  services_rev: number;
  rebates_contra: number;
  cogs_boq: number;
  services_cogs: number;
  overheads: number;
  capex_depr: number;
  fx: number;
  tax: number;
  gm: number;
  net: number;
};
type SummaryResp = {
  scenario_id: number;
  from: string;
  to: string;
  mode: "monthly" | "ytd" | string;
  items: SummaryItem[];
};

/** BOQ (fallback için minimal) */
type BOQItem = {
  is_active?: boolean | number | null;
  quantity?: number | null;
  unit_price?: number | null;
  unit_cogs?: number | null;
  frequency?: "once" | "monthly" | "per_shipment" | "per_tonne" | string | null;
  months?: number | null;
  start_year?: number | null;
  start_month?: number | null;
};

/** UI row (server veya fallback normalize) */
type UIRow = {
  key: string;
  y: number;
  m: number;
  revenue_boq: number;
  services_rev: number;
  rebates_contra: number;
  cogs_boq: number;
  services_cogs: number;
  overheads: number;
  capex_depr: number;
  fx: number;
  tax: number;
};

/* ---------- Helpers ---------- */
function pad2(n: number) { return String(n).padStart(2, "0"); }
function ymFromISO(iso: string) {
  const d = new Date(iso);
  return { y: d.getFullYear(), m: d.getMonth() + 1 };
}
function ymAdd(y: number, m: number, k: number) {
  const base = y * 12 + (m - 1) + k;
  return { y: Math.floor(base / 12), m: (base % 12) + 1 };
}
function ymKey(y: number, m: number) { return `${y}-${pad2(m)}`; }
function monthsBetweenInclusive(y0: number, m0: number, y1: number, m1: number) {
  return (y1 * 12 + (m1 - 1)) - (y0 * 12 + (m0 - 1)) + 1;
}
function parseYM(ym: string) {
  const [yy, mm] = ym.split("-").map(Number);
  return { y: yy, m: mm };
}
function isActiveFlag(v: unknown) { return v === true || v === 1 || v === "1"; }

const moneyFmt = new Intl.NumberFormat(undefined, { minimumFractionDigits: 0, maximumFractionDigits: 0 });
function fmtMoney(n: number, dashForZero = true) { return dashForZero && Math.abs(n) < 1e-9 ? "–" : moneyFmt.format(n); }
function fmtPct(n: number) { return Number.isFinite(n) ? `${n.toFixed(1)}%` : "–"; }

function num(v: any): number {
  const n = Number(v);
  return Number.isFinite(n) ? n : 0;
}

/** Endpoint builders (CORS güvenli) */
function buildSummaryUrl(scenarioId: number, fromYM: string, toYM: string) {
  const q = `from=${encodeURIComponent(fromYM)}&to=${encodeURIComponent(toYM)}&mode=monthly`;
  return `/api/scenarios/${scenarioId}/summary?${q}`;
}
function buildRebatesPreviewUrl(scenarioId: number, fromYM: string, toYM: string) {
  const q = `from=${encodeURIComponent(fromYM)}&to=${encodeURIComponent(toYM)}&mode=monthly`;
  return `/api/scenarios/${scenarioId}/rebates/preview?${q}`;
}

/** KPI cell */
function KPI({ label, value, hint }: { label: string; value: string; hint?: string }) {
  return (
    <div className="rounded-md border bg-white p-3 shadow-sm">
      <div className="text-[11px] text-gray-500">{label}</div>
      <div className="text-xl font-semibold tabular-nums">{value}</div>
      {hint ? <div className="text-[11px] text-gray-500 mt-1">{hint}</div> : null}
    </div>
  );
}

/** SummaryTab */
export default function SummaryTab({ scenarioId, startDate, months }: Props) {
  const [resp, setResp] = useState<SummaryResp | null>(null);
  const [loading, setLoading] = useState(false);
  const [err, setErr] = useState<string | null>(null);

  // Fallback (server summary başarısızsa)
  const [usingFallback, setUsingFallback] = useState(false);
  const [fallbackRows, setFallbackRows] = useState<UIRow[]>([]);
  const [fallbackNote, setFallbackNote] = useState<string | null>(null);

  // Derive [from,to] from scenario start & months
  const { fromYM, toYM, startY, startM } = useMemo(() => {
    const { y, m } = ymFromISO(startDate);
    const to = ymAdd(y, m, Math.max(1, months) - 1);
    return { fromYM: ymKey(y, m), toYM: ymKey(to.y, to.m), startY: y, startM: m };
  }, [startDate, months]);

  async function loadSummary() {
    setLoading(true);
    setErr(null);
    setUsingFallback(false);
    setFallbackRows([]);
    setFallbackNote(null);
    try {
      const url = buildSummaryUrl(scenarioId, fromYM, toYM);
      const data = await apiGet<SummaryResp>(url);
      setResp(data);
    } catch (e: any) {
      const message = e?.response?.data?.detail || e?.message || "Failed to load summary.";
      setErr(String(message));
      // Fallback'a geç
      await loadFallback();
    } finally {
      setLoading(false);
    }
  }

  /** Fallback: BOQ + Rebates Preview'dan yerelde özet üret */
  async function loadFallback() {
    try {
      // 1) Ay aralığını hazırla
      const { y: y0, m: m0 } = parseYM(fromYM);
      const { y: y1, m: m1 } = parseYM(toYM);
      const n = monthsBetweenInclusive(y0, m0, y1, m1);

      const map = new Map<string, UIRow>();
      for (let i = 0; i < n; i++) {
        const { y, m } = ymAdd(y0, m0, i);
        const key = ymKey(y, m);
        map.set(key, {
          key, y, m,
          revenue_boq: 0, services_rev: 0, rebates_contra: 0,
          cogs_boq: 0, services_cogs: 0, overheads: 0, capex_depr: 0, fx: 0, tax: 0,
        });
      }

      // 2) BOQ çek
      const boqUrl = `/scenarios/${scenarioId}/boq`;
      const boq = await apiGet<BOQItem[]>(boqUrl);

      // 3) BOQ katkılarını dağıt
      for (const r of boq) {
        if (!isActiveFlag(r.is_active)) continue;
        const sy = num(r.start_year);
        const sm = num(r.start_month);
        if (!sy || !sm) continue;

        const freq = String(r.frequency || "once").toLowerCase();
        const span = Math.max(1, num(r.months || 1));
        const lineRev = num(r.quantity) * num(r.unit_price);
        const lineCogs = num(r.quantity) * num(r.unit_cogs);

        if (freq === "monthly") {
          for (let k = 0; k < span; k++) {
            const { y, m } = ymAdd(sy, sm, k);
            const key = ymKey(y, m);
            const row = map.get(key);
            if (!row) continue; // horizon dışı
            row.revenue_boq += lineRev;
            row.cogs_boq += lineCogs;
          }
        } else {
          const key = ymKey(sy, sm);
          const row = map.get(key);
          if (row) {
            row.revenue_boq += lineRev;
            row.cogs_boq += lineCogs;
          }
        }
      }

      // 4) Rebates overlay
      try {
        const rUrl = buildRebatesPreviewUrl(scenarioId, fromYM, toYM);
        const r = await apiGet<{ items: { ym: string; accrual: number }[] }>(rUrl);
        for (const it of r.items || []) {
          const row = map.get(it.ym);
          if (row) row.rebates_contra = num(it.accrual); // already contra (negative)
        }
      } catch (re: any) {
        setFallbackNote(
          `Rebates overlay failed: ${re?.response?.status || "ERR"} — proceeding without rebates preview`
        );
      }

      // 5) Diziye çevir & sırala
      const rows = [...map.values()].sort((a, b) => a.y - b.y || a.m - b.m);
      setFallbackRows(rows);
      setUsingFallback(true);
    } catch (fe: any) {
      setFallbackNote(`Fallback failed: ${fe?.message || String(fe)}`);
    }
  }

  useEffect(() => {
    if (scenarioId) loadSummary();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [scenarioId, fromYM, toYM]);

  // Normalize rows for UI
  const rows: UIRow[] = useMemo(() => {
    if (resp?.items?.length) {
      return resp.items.map((r) => {
        const { y, m } = parseYM(r.ym);
        return {
          key: r.ym,
          y, m,
          revenue_boq: r.revenue_boq,
          services_rev: r.services_rev,
          rebates_contra: r.rebates_contra,
          cogs_boq: r.cogs_boq,
          services_cogs: r.services_cogs,
          overheads: r.overheads,
          capex_depr: r.capex_depr,
          fx: r.fx,
          tax: r.tax,
        };
      });
    }
    return fallbackRows;
  }, [resp, fallbackRows]);

  /** Totals & KPIs */
  const totals = useMemo(() => {
    return rows.reduce(
      (s, r) => {
        const totalRev = r.revenue_boq + r.services_rev + r.rebates_contra;
        const totalCogs = r.cogs_boq + r.services_cogs;
        const gm = totalRev - totalCogs;

        s.revenue += totalRev;
        s.cogs += totalCogs;
        s.gm += gm;
        s.ebitda += gm - r.overheads;
        s.ebit += gm - r.overheads - r.capex_depr;
        s.net += (gm - r.overheads - r.capex_depr) + r.fx - r.tax;

        s.fx += r.fx; s.tax += r.tax;
        return s;
      },
      { revenue: 0, cogs: 0, gm: 0, ebitda: 0, ebit: 0, net: 0, fx: 0, tax: 0 }
    );
  }, [rows]);

  const kpi = useMemo(() => {
    const rev = totals.revenue, cogs = totals.cogs, gm = totals.gm;
    const gmPct = rev !== 0 ? (gm / rev) * 100 : 0;
    return { revenue: rev, cogs, gm, gmPct, ebitda: totals.ebitda, ebit: totals.ebit, net: totals.net };
  }, [totals]);

  return (
    <div className="space-y-4">
      {/* Header */}
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-2">
          <h3 className="font-semibold text-lg">Summary</h3>
          {usingFallback ? (
            <span className="text-[11px] px-2 py-0.5 rounded bg-amber-100 text-amber-700 border border-amber-200">
              Fallback (local calc)
            </span>
          ) : (
            <span className="text-[11px] px-2 py-0.5 rounded bg-emerald-100 text-emerald-700 border border-emerald-200">
              Server summary
            </span>
          )}
        </div>
        <div className="flex items-center gap-2">
          {loading && <span className="text-xs text-gray-500">Loading…</span>}
          <button onClick={loadSummary} className="px-3 py-1 rounded bg-gray-100 hover:bg-gray-200" disabled={loading}>
            Refresh
          </button>
        </div>
      </div>

      {/* KPIs */}
      <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
        <KPI label="Revenue" value={fmtMoney(kpi.revenue)} />
        <KPI label="COGS" value={fmtMoney(kpi.cogs)} />
        <KPI label="Gross Margin" value={fmtMoney(kpi.gm)} hint={fmtPct(kpi.gmPct)} />
        <KPI label="EBITDA (approx.)" value={fmtMoney(kpi.ebitda)} />
        <KPI label="EBIT (approx.)" value={fmtMoney(kpi.ebit)} />
        <KPI label="FX Impact" value={fmtMoney(totals.fx)} />
        <KPI label="Tax" value={fmtMoney(totals.tax)} />
        <KPI label="Net Income (approx.)" value={fmtMoney(kpi.net)} />
      </div>

      {/* Errors / Notes */}
      {err && <div className="text-sm text-red-600 bg-red-50 border border-red-200 p-2 rounded">{err}</div>}
      {usingFallback && fallbackNote && (
        <div className="text-xs text-amber-700 bg-amber-50 border border-amber-200 p-2 rounded">
          {fallbackNote}
        </div>
      )}

      {/* Monthly table */}
      <div className="overflow-auto border rounded bg-white">
        <table className="min-w-full text-[13px] tabular-nums">
          <thead className="sticky top-0 z-10">
            <tr className="bg-gray-100 text-gray-800">
              <th rowSpan={2} className="min-w-[90px] sticky left-0 z-20 bg-gray-100 border border-gray-300 px-3 py-2 text-left">Y/M</th>
              <th colSpan={4} className="border border-gray-300 px-3 py-2 text-center">Revenue</th>
              <th colSpan={4} className="border border-gray-300 px-3 py-2 text-center">Costs</th>
              <th rowSpan={2} className="border border-gray-300 px-3 py-2 text-center">Gross Margin</th>
              <th colSpan={2} className="border border-gray-300 px-3 py-2 text-center">Below the Line</th>
              <th rowSpan={2} className="border border-gray-300 px-3 py-2 text-center">Net (approx.)</th>
            </tr>
            <tr className="bg-gray-100 text-gray-800">
              <th className="border border-gray-300 px-3 py-2 text-right">BOQ</th>
              <th className="border border-gray-300 px-3 py-2 text-right">Services</th>
              <th className="border border-gray-300 px-3 py-2 text-right">Rebates (–)</th>
              <th className="border border-gray-300 px-3 py-2 text-right">Total</th>
              <th className="border border-gray-300 px-3 py-2 text-right">BOQ COGS</th>
              <th className="border border-gray-300 px-3 py-2 text-right">Services COGS</th>
              <th className="border border-gray-300 px-3 py-2 text-right">Overheads</th>
              <th className="border border-gray-300 px-3 py-2 text-right">Deprec.</th>
              <th className="border border-gray-300 px-3 py-2 text-right">FX</th>
              <th className="border border-gray-300 px-3 py-2 text-right">Tax</th>
            </tr>
          </thead>

          <tbody>
            {rows.map((r, idx) => {
              const totalRev = r.revenue_boq + r.services_rev + r.rebates_contra;
              const gm = totalRev - (r.cogs_boq + r.services_cogs);
              const net = gm - r.overheads - r.capex_depr + r.fx - r.tax;
              return (
                <tr key={r.key} className={idx % 2 === 0 ? "bg-white" : "bg-gray-50"}>
                  <td className="sticky left-0 z-10 bg-inherit border border-gray-300 px-3 py-2 text-left">{r.y}/{pad2(r.m)}</td>
                  <td className="border border-gray-300 px-3 py-2 text-right">{fmtMoney(r.revenue_boq)}</td>
                  <td className="border border-gray-300 px-3 py-2 text-right">{fmtMoney(r.services_rev)}</td>
                  <td className="border border-gray-300 px-3 py-2 text-right">{fmtMoney(r.rebates_contra)}</td>
                  <td className="border border-gray-300 px-3 py-2 text-right font-medium">{fmtMoney(totalRev)}</td>
                  <td className="border border-gray-300 px-3 py-2 text-right">{fmtMoney(r.cogs_boq)}</td>
                  <td className="border border-gray-300 px-3 py-2 text-right">{fmtMoney(r.services_cogs)}</td>
                  <td className="border border-gray-300 px-3 py-2 text-right">{fmtMoney(r.overheads)}</td>
                  <td className="border border-gray-300 px-3 py-2 text-right">{fmtMoney(r.capex_depr)}</td>
                  <td className="border border-gray-300 px-3 py-2 text-right font-medium">{fmtMoney(gm)}</td>
                  <td className="border border-gray-300 px-3 py-2 text-right">{fmtMoney(r.fx)}</td>
                  <td className="border border-gray-300 px-3 py-2 text-right">{fmtMoney(r.tax)}</td>
                  <td className="border border-gray-300 px-3 py-2 text-right font-semibold">{fmtMoney(net)}</td>
                </tr>
              );
            })}
          </tbody>

          <tfoot>
            <tr className="bg-emerald-50 font-semibold">
              <td className="sticky left-0 z-10 bg-emerald-50 border border-gray-300 px-3 py-2">Totals</td>
              <td className="border border-gray-300 px-3 py-2 text-right">
                {fmtMoney(rows.reduce((s, r) => s + r.revenue_boq, 0))}
              </td>
              <td className="border border-gray-300 px-3 py-2 text-right">
                {fmtMoney(rows.reduce((s, r) => s + r.services_rev, 0))}
              </td>
              <td className="border border-gray-300 px-3 py-2 text-right">
                {fmtMoney(rows.reduce((s, r) => s + r.rebates_contra, 0))}
              </td>
              <td className="border border-gray-300 px-3 py-2 text-right">
                {fmtMoney(rows.reduce((s, r) => s + (r.revenue_boq + r.services_rev + r.rebates_contra), 0))}
              </td>
              <td className="border border-gray-300 px-3 py-2 text-right">
                {fmtMoney(rows.reduce((s, r) => s + r.cogs_boq, 0))}
              </td>
              <td className="border border-gray-300 px-3 py-2 text-right">
                {fmtMoney(rows.reduce((s, r) => s + r.services_cogs, 0))}
              </td>
              <td className="border border-gray-300 px-3 py-2 text-right">
                {fmtMoney(rows.reduce((s, r) => s + r.overheads, 0))}
              </td>
              <td className="border border-gray-300 px-3 py-2 text-right">
                {fmtMoney(rows.reduce((s, r) => s + r.capex_depr, 0))}
              </td>
              <td className="border border-gray-300 px-3 py-2 text-right">
                {fmtMoney(rows.reduce((s, r) => s + ((r.revenue_boq + r.services_rev + r.rebates_contra) - (r.cogs_boq + r.services_cogs)), 0))}
              </td>
              <td className="border border-gray-300 px-3 py-2 text-right">
                {fmtMoney(rows.reduce((s, r) => s + r.fx, 0))}
              </td>
              <td className="border border-gray-300 px-3 py-2 text-right">
                {fmtMoney(rows.reduce((s, r) => s + r.tax, 0))}
              </td>
              <td className="border border-gray-300 px-3 py-2 text-right">
                {fmtMoney(rows.reduce((s, r) => {
                  const gm = (r.revenue_boq + r.services_rev + r.rebates_contra) - (r.cogs_boq + r.services_cogs);
                  return s + (gm - r.overheads - r.capex_depr + r.fx - r.tax);
                }, 0))}
              </td>
            </tr>
          </tfoot>
        </table>

        <div className="px-3 py-2 text-xs text-gray-500">
          {usingFallback ? (
            <>
              Excel-style layout (fallback): <strong>BOQ</strong> + <strong>/api/scenarios/:id/rebates/preview</strong> ile yerel hesap.
            </>
          ) : (
            <>
              Excel-style layout powered by <strong>/api/scenarios/:id/summary</strong> (BOQ + rebates overlay).
            </>
          )}
        </div>
      </div>

      {/* Contribution blocks */}
      <div className="grid grid-cols-1 md:grid-cols-3 gap-3">
        <div className="rounded-md border bg-white p-3">
          <div className="font-medium mb-2">Revenue Contributors</div>
          <ul className="text-sm space-y-1 text-gray-700">
            <li>• BOQ Revenue ✅</li>
            <li>• Services Revenue (placeholder) ⏳</li>
            <li>• Rebates (contra-revenue) ✅ (preview)</li>
          </ul>
        </div>
        <div className="rounded-md border bg-white p-3">
          <div className="font-medium mb-2">Cost & Overheads</div>
          <ul className="text-sm space-y-1 text-gray-700">
            <li>• BOQ COGS ✅</li>
            <li>• Services COGS (placeholder) ⏳</li>
            <li>• Overheads (placeholder) ⏳</li>
            <li>• CAPEX Depreciation (placeholder) ⏳</li>
          </ul>
        </div>
        <div className="rounded-md border bg-white p-3">
          <div className="font-medium mb-2">Below the Line</div>
          <ul className="text-sm space-y-1 text-gray-700">
            <li>• FX Impact (placeholder) ⏳</li>
            <li>• Tax (placeholder) ⏳</li>
            <li>• Net Income (approx.) derived on the table</li>
          </ul>
        </div>
      </div>
    </div>
  );
}
