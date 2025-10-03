import React, { useEffect, useMemo, useState } from "react";
import { apiGet } from "../../../lib/api";

/** Props */
type Props = {
  scenarioId: number;
};

/** BOQ Item (özet) */
type BOQItem = {
  id?: number;
  is_active: boolean | null | undefined;

  item_name: string;
  unit: string;

  quantity: number | null | undefined;
  unit_price: number | null | undefined;
  unit_cogs?: number | null | undefined;

  frequency: "once" | "monthly" | "per_shipment" | "per_tonne";
  months?: number | null | undefined;

  start_year?: number | null | undefined;
  start_month?: number | null | undefined;
};

type MonthAgg = { revenue: number; cogs: number; gm: number };

function num(v: any): number {
  const n = Number(v);
  return Number.isFinite(n) ? n : 0;
}
function pad2(n: number) {
  return String(n).padStart(2, "0");
}
function ymKey(y: number, m: number) {
  return `${y}-${pad2(m)}`;
}
function addMonths(y: number, m: number, k: number) {
  const d0 = new Date(y, m - 1, 1);
  const d1 = new Date(d0.getFullYear(), d0.getMonth() + k, 1);
  return { year: d1.getFullYear(), month: d1.getMonth() + 1 };
}
function getOrInit(map: Map<string, MonthAgg>, key: string): MonthAgg {
  const cur = map.get(key);
  if (cur) return cur;
  const blank: MonthAgg = { revenue: 0, cogs: 0, gm: 0 };
  map.set(key, blank);
  return blank;
}

/** P&L (BOQ’tan türeyen aylık Revenue/COGS/GM) */
export default function PLTab({ scenarioId }: Props) {
  const [boq, setBoq] = useState<BOQItem[]>([]);
  const [loading, setLoading] = useState(false);
  const [err, setErr] = useState<string | null>(null);

  async function load() {
    setLoading(true);
    setErr(null);
    try {
      const data = await apiGet<BOQItem[]>(`/scenarios/${scenarioId}/boq`);
      setBoq(data);
    } catch (e: any) {
      setErr(e?.response?.data?.detail || e?.message || "Failed to load BOQ.");
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    if (scenarioId) load();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [scenarioId]);

  // BOQ -> Aylık schedule (36 ay)
  const schedule = useMemo(() => {
    const agg = new Map<string, MonthAgg>();
    const HORIZON = 36;

    const active = boq.filter(
      (r): r is BOQItem & { is_active: true; start_year: number; start_month: number } =>
        !!r.is_active &&
        typeof r.start_year === "number" &&
        typeof r.start_month === "number"
    );

    for (const r of active) {
      const qty = num(r.quantity);
      const price = num(r.unit_price);
      const uc = num(r.unit_cogs ?? 0);
      const lineRev = qty * price;
      const lineCogs = qty * uc;

      const startY = r.start_year;
      const startM = r.start_month;

      if (r.frequency === "monthly") {
        const len = Math.max(1, num(r.months ?? 1));
        for (let k = 0; k < Math.min(len, HORIZON); k++) {
          const { year, month } = addMonths(startY, startM, k);
          const key = ymKey(year, month);
          const cur = getOrInit(agg, key);
          cur.revenue += lineRev;
          cur.cogs += lineCogs;
          cur.gm += lineRev - lineCogs;
        }
      } else {
        // once / per_shipment / per_tonne -> şimdilik tek seferlik
        const key = ymKey(startY, startM);
        const cur = getOrInit(agg, key);
        cur.revenue += lineRev;
        cur.cogs += lineCogs;
        cur.gm += lineRev - lineCogs;
      }
    }

    const rows = [...agg.entries()]
      .map(([key, v]) => ({
        key,
        y: Number(key.slice(0, 4)),
        m: Number(key.slice(5, 7)),
        ...v,
      }))
      .sort((a, b) => a.y - b.y || a.m - b.m);

    const totals = rows.reduce(
      (s, r) => {
        s.revenue += r.revenue;
        s.cogs += r.cogs;
        s.gm += r.gm;
        return s;
      },
      { revenue: 0, cogs: 0, gm: 0 }
    );

    return { rows, totals };
  }, [boq]);

  return (
    <div className="space-y-3">
      <div className="flex items-center justify-between">
        <h3 className="font-semibold text-lg">P&amp;L (BOQ bazlı aylık özet)</h3>
        <button
          onClick={load}
          className="px-3 py-1 rounded bg-gray-100 hover:bg-gray-200"
          disabled={loading}
        >
          Refresh
        </button>
      </div>

      {err && (
        <div className="text-sm text-red-600 bg-red-50 border border-red-200 p-2 rounded">
          {err}
        </div>
      )}

      {loading ? (
        <div className="text-sm text-gray-500">Loading…</div>
      ) : (
        <div className="overflow-x-auto border rounded bg-white">
          <table className="min-w-full text-sm">
            <thead className="bg-gray-50">
              <tr>
                <th className="px-3 py-2 text-left">Y/M</th>
                <th className="px-3 py-2 text-right">Revenue</th>
                <th className="px-3 py-2 text-right">COGS</th>
                <th className="px-3 py-2 text-right">Gross Margin</th>
              </tr>
            </thead>
            <tbody>
              {schedule.rows.map((r) => (
                <tr key={r.key} className="odd:bg-white even:bg-gray-50">
                  <td className="px-3 py-2">
                    {r.y}/{pad2(r.m)}
                  </td>
                  <td className="px-3 py-2 text-right">
                    {r.revenue.toLocaleString()}
                  </td>
                  <td className="px-3 py-2 text-right">
                    {r.cogs.toLocaleString()}
                  </td>
                  <td className="px-3 py-2 text-right">
                    {r.gm.toLocaleString()}
                  </td>
                </tr>
              ))}
            </tbody>
            <tfoot>
              <tr className="bg-emerald-50 font-semibold">
                <td className="px-3 py-2">Totals</td>
                <td className="px-3 py-2 text-right">
                  {schedule.totals.revenue.toLocaleString()}
                </td>
                <td className="px-3 py-2 text-right">
                  {schedule.totals.cogs.toLocaleString()}
                </td>
                <td className="px-3 py-2 text-right">
                  {schedule.totals.gm.toLocaleString()}
                </td>
              </tr>
            </tfoot>
          </table>
          <div className="px-3 py-2 text-xs text-gray-500">
            Not: Şimdilik yalnızca BOQ verileri baz alınır. Bir sonraki adımda
            TWC’den NWC etkisi ve CAPEX’ten amortisman/servis başlangıcı dahil edeceğiz.
          </div>
        </div>
      )}
    </div>
  );
}
