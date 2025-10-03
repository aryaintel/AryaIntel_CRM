import { useEffect, useMemo, useState } from "react";
import type { ScenarioDetail, ProductMonth } from "../../../types/scenario";
import { Card, Field, KV } from "../../../components/ui";
import {
  fmt,
  fmtMonthYY,
  getNumberClass,
  FIRST_COL_W,
  MONTH_COL_W,
} from "../../../utils/format";
import { apiPut, ApiError } from "../../../lib/api";
import {
  buildMonthsList,
  isInWindow,
  monthIndex,
} from "../../../utils/scenarioWindow";

type VolumesMap = Record<number, number[]>; // productId -> quantities

export default function VolumesTab({
  data,
  refresh,
}: {
  data: ScenarioDetail;
  refresh: () => void;
}) {
  const monthsList = useMemo(() => buildMonthsList(data), [data]);
  const [volumes, setVolumes] = useState<VolumesMap>({});
  const [exMode, setExMode] = useState<"constant" | "growth">("constant");
  const [growthPct, setGrowthPct] = useState<string>("5");

  // backend -> grid init
  useEffect(() => {
    const m = data.months;
    const next: VolumesMap = {};
    for (const p of data.products) {
      const arr = new Array(m).fill(0);
      for (const r of p.months ?? []) {
        if (!isInWindow(data, r.year, r.month)) continue;
        const idx = monthIndex(data, r.year, r.month);
        if (idx >= 0 && idx < m) arr[idx] = r.quantity ?? 0;
      }
      next[p.id] = arr;
    }
    setVolumes(next);
  }, [data]);

  const setCell = (pid: number, midx: number, val: number) => {
    setVolumes((v) => ({
      ...v,
      [pid]: (v[pid] ?? new Array(data.months).fill(0)).map((x, i) =>
        i === midx ? val : x,
      ),
    }));
  };

  const extrapolateAll = () => {
    const months = data.months;
    const rate = Number(growthPct || "0") / 100;
    setVolumes((v) => {
      const copy: VolumesMap = { ...v };
      for (const p of data.products) {
        const row = [...(copy[p.id] ?? new Array(months).fill(0))];
        const first = row[0] ?? 0;
        if (first <= 0) {
          copy[p.id] = row;
          continue;
        }
        for (let i = 1; i < months; i++) {
          row[i] =
            exMode === "constant"
              ? first
              : Math.round(first * Math.pow(1 + rate, i));
        }
        copy[p.id] = row;
      }
      return copy;
    });
  };

  const saveAllVolumes = async () => {
    try {
      for (const p of data.products) {
        const arr = volumes[p.id] ?? [];
        const payload: ProductMonth[] = arr.map((q, i) => ({
          year: monthsList[i].y,
          month: monthsList[i].m,
          quantity: Number(q || 0),
        }));
        await apiPut(
          `/business-cases/scenarios/products/${p.id}/months`,
          payload,
        );
      }
      await refresh();
      alert("Volumes saved.");
    } catch (e: any) {
      alert(
        (e instanceof ApiError && e.message) || e?.message || "Save failed",
      );
    }
  };

  // quick sim (Revenue / COGS / GM)
  const sim = useMemo(() => {
    const m = data.months;
    const revenue = new Array(m).fill(0);
    const cogs = new Array(m).fill(0);
    for (const p of data.products) {
      const vols = volumes[p.id] ?? new Array(m).fill(0);
      for (let i = 0; i < m; i++) {
        revenue[i] += (vols[i] ?? 0) * (p.price ?? 0);
        cogs[i] += (vols[i] ?? 0) * (p.unit_cogs ?? 0);
      }
    }
    const gm = revenue.map((x, i) => x - cogs[i]);
    const totals = {
      revenue: revenue.reduce((a, b) => a + b, 0),
      cogs: cogs.reduce((a, b) => a + b, 0),
      gm: gm.reduce((a, b) => a + b, 0),
    };
    return { revenue, cogs, gm, totals };
  }, [data, volumes, monthsList.length]);

  return (
    <div className="space-y-4">
      <Card>
        <div className="grid grid-cols-1 md:grid-cols-4 gap-3 items-end">
          <Field label="Extrapolation mode">
            <select
              value={exMode}
              onChange={(e) => setExMode(e.target.value as "constant" | "growth")}
              className="w-full px-3 py-2 rounded-md border text-sm"
            >
              <option value="constant">Constant (copy 1st month)</option>
              <option value="growth">Growth rate (from 1st month)</option>
            </select>
          </Field>
          {exMode === "growth" && (
            <Field label="Monthly growth (%)">
              <input
                type="number"
                value={growthPct}
                onChange={(e) => setGrowthPct(e.target.value)}
                className="w-full px-3 py-2 rounded-md border text-sm"
              />
            </Field>
          )}
          <div />
          <div className="flex md:justify-end">
            <button
              onClick={extrapolateAll}
              className="px-3 py-2 rounded-md border text-sm hover:bg-gray-50"
            >
              Extrapolate All
            </button>
          </div>
        </div>
      </Card>

      <Card>
        <div className="text-sm font-medium mb-2">
          Volumes (by product × month)
        </div>
        <div className="overflow-x-auto">
          <table className="min-w-max text-xs table-fixed">
            <thead>
              <tr className="border-b">
                <th
                  className="sticky left-0 z-10 bg-white py-1 px-2 text-left"
                  style={{ width: FIRST_COL_W, minWidth: FIRST_COL_W }}
                >
                  Product
                </th>
                {monthsList.map((mm, i) => (
                  <th
                    key={i}
                    className="py-1 px-2 text-right whitespace-nowrap"
                    style={{ width: MONTH_COL_W, minWidth: MONTH_COL_W }}
                  >
                    {fmtMonthYY(mm.y, mm.m)}
                  </th>
                ))}
              </tr>
            </thead>
            <tbody>
              {data.products.map((p) => (
                <tr key={p.id} className="border-b last:border-0">
                  <td
                    className="sticky left-0 z-10 bg-white py-1 px-2 font-medium"
                    style={{ width: FIRST_COL_W, minWidth: FIRST_COL_W }}
                  >
                    {p.name}
                  </td>
                  {(volumes[p.id] ?? new Array(data.months).fill(0)).map(
                    (q, i) => (
                      <td
                        key={i}
                        className="py-1 px-2 text-right align-middle"
                        style={{ width: MONTH_COL_W, minWidth: MONTH_COL_W }}
                      >
                        <input
                          type="number"
                          value={q ?? 0}
                          onChange={(e) =>
                            setCell(p.id, i, Number(e.target.value))
                          }
                          className="w-full px-1.5 py-1 rounded border text-xs text-right tabular-nums"
                        />
                      </td>
                    ),
                  )}
                </tr>
              ))}
            </tbody>
          </table>
        </div>
        <div className="mt-3 flex justify-end">
          <button
            onClick={saveAllVolumes}
            className="px-3 py-1.5 rounded-md bg-indigo-600 text-white text-sm hover:bg-indigo-500"
          >
            Save All
          </button>
        </div>
      </Card>

      <Card>
        <div className="text-sm font-medium mb-2">
          Simulation (Revenue / COGS / GM)
        </div>
        {!sim ? (
          <div className="text-sm text-gray-500">No data.</div>
        ) : (
          <>
            <div className="grid grid-cols-1 md:grid-cols-3 gap-3 mb-3">
              <KV label="Revenue (total)" value={fmt(sim.totals.revenue)} />
              <KV label="COGS (total)" value={fmt(sim.totals.cogs)} />
              <KV label="Gross Margin (total)" value={fmt(sim.totals.gm)} />
            </div>
            <div className="overflow-x-auto">
              <table className="min-w-max text-xs table-fixed">
                <thead>
                  <tr className="border-b">
                    <th
                      className="sticky left-0 bg-white py-1 px-2 text-left"
                      style={{ width: FIRST_COL_W, minWidth: FIRST_COL_W }}
                    >
                      Line
                    </th>
                    {monthsList.map((mm, i) => (
                      <th
                        key={i}
                        className="py-1 px-2 text-right whitespace-nowrap"
                        style={{ width: MONTH_COL_W, minWidth: MONTH_COL_W }}
                      >
                        {fmtMonthYY(mm.y, mm.m)}
                      </th>
                    ))}
                  </tr>
                </thead>
                <tbody>
                  {[
                    { label: "Revenue", arr: sim.revenue },
                    { label: "COGS", arr: sim.cogs },
                    { label: "Gross Margin", arr: sim.gm },
                  ].map((row) => (
                    <tr key={row.label} className="border-b last:border-0">
                      <td
                        className="sticky left-0 bg-white py-1 px-2 font-medium"
                        style={{ width: FIRST_COL_W, minWidth: FIRST_COL_W }}
                      >
                        {row.label}
                      </td>
                      {row.arr.map((v, idx) => (
                        <td
                          key={idx}
                          className={`py-1 px-2 text-right ${getNumberClass(
                            v,
                          )}`}
                          style={{ width: MONTH_COL_W, minWidth: MONTH_COL_W }}
                        >
                          {fmt(v)}
                        </td>
                      ))}
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </>
        )}
      </Card>
    </div>
  );
}
