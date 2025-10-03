import React, { useEffect, useMemo, useState } from "react";
import { apiGet, apiPost, apiPut, apiDelete } from "../../../lib/api";

/* ---------- Types ---------- */
type Props = {
  scenarioId: number;
  onChanged?: () => void;
  onMarkedReady?: () => void;
  isReady?: boolean;
};

type BOQItem = {
  id?: number;
  scenario_id?: number;

  section?: string | null;
  category?: "bulk_with_freight" | "bulk_ex_freight" | "freight" | null;

  item_name: string;
  unit: string;

  quantity: number | null | undefined;
  unit_price: number | null | undefined;
  unit_cogs?: number | null | undefined;

  frequency: "once" | "monthly" | "per_shipment" | "per_tonne";
  months?: number | null | undefined;

  start_year?: number | null | undefined;
  start_month?: number | null | undefined;

  is_active: boolean | null | undefined;
  notes?: string | null;
};

/* ---------- Utils ---------- */
function cls(...a: (string | false | undefined)[]) {
  return a.filter(Boolean).join(" ");
}
function num(v: any): number {
  const n = Number(v);
  return Number.isFinite(n) ? n : 0;
}
function pad2(n: number) {
  return String(n).padStart(2, "0");
}
function addMonths(y: number, m: number, k: number) {
  const d0 = new Date(y, m - 1, 1);
  const d1 = new Date(d0.getFullYear(), d0.getMonth() + k, 1);
  return { year: d1.getFullYear(), month: d1.getMonth() + 1 };
}
function ymKey(y: number, m: number) {
  return `${y}-${pad2(m)}`;
}

/* HTML5 month input (YYYY-MM) */
function MonthInput({
  value,
  onChange,
  className,
}: {
  value: { year: number | null | undefined; month: number | null | undefined };
  onChange: (next: { year: number | null; month: number | null }) => void;
  className?: string;
}) {
  const str = value.year && value.month ? `${value.year}-${pad2(value.month)}` : "";
  return (
    <input
      type="month"
      value={str}
      onChange={(e: React.ChangeEvent<HTMLInputElement>) => {
        const v = e.target.value; // "YYYY-MM" | ""
        if (!v) return onChange({ year: null, month: null });
        const [y, m] = v.split("-").map((t) => Number(t));
        onChange({
          year: Number.isFinite(y) ? y : null,
          month: Number.isFinite(m) ? m : null,
        });
      }}
      className={cls(
        "w-full px-2 py-1 rounded border border-gray-300 focus:outline-none focus:ring",
        className
      )}
    />
  );
}

const CATEGORY_OPTIONS: Array<BOQItem["category"]> = [
  "bulk_with_freight",
  "bulk_ex_freight",
  "freight",
];

/* ---------- Pivot Preview Component ---------- */
function MonthlyPreviewPivot({
  rows,
  totals,
}: {
  rows: Array<{ key: string; y: number; m: number; revenue: number; cogs: number; gm: number }>;
  totals: { revenue: number; cogs: number; gm: number };
}) {
  const cols = rows.map((r) => `${r.y}/${pad2(r.m)}`);
  const metrics = [
    { key: "revenue", label: "Revenue" as const },
    { key: "cogs", label: "COGS" as const },
    { key: "gm", label: "GM" as const },
  ] as const;

  function getCell(metric: "revenue" | "cogs" | "gm", idx: number) {
    const r = rows[idx];
    return (r?.[metric] ?? 0).toLocaleString(undefined, { maximumFractionDigits: 2 });
  }

  return (
    <div className="overflow-x-auto">
      <table className="min-w-full text-sm">
        <thead className="bg-gray-50">
          <tr>
            <th className="px-3 py-2 text-left w-36">Metric</th>
            {cols.map((c) => (
              <th key={c} className="px-3 py-2 text-right whitespace-nowrap">
                {c}
              </th>
            ))}
            <th className="px-3 py-2 text-right">Total</th>
          </tr>
        </thead>
        <tbody>
          {metrics.map((m) => (
            <tr key={m.key} className="odd:bg-white even:bg-gray-50">
              <td className="px-3 py-2 font-medium">{m.label}</td>
              {rows.map((_, i) => (
                <td key={i} className="px-3 py-2 text-right">
                  {getCell(m.key, i)}
                </td>
              ))}
              <td className="px-3 py-2 text-right font-semibold">
                {totals[m.key].toLocaleString(undefined, { maximumFractionDigits: 2 })}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
      <div className="px-3 py-2 text-xs text-gray-500">
        Not: <code>monthly</code> satırlar girilen <b>Duration</b> süresince yayılır;
        <code> once</code>/<code>per_shipment</code>/<code>per_tonne</code> tek seferlik kabul edilir.
      </div>
    </div>
  );
}

/* ========================================================= */

export default function BOQTable({ scenarioId, onChanged, onMarkedReady, isReady }: Props) {
  const [rows, setRows] = useState<BOQItem[]>([]);
  const [draft, setDraft] = useState<BOQItem | null>(null);
  const [loading, setLoading] = useState(false);
  const [err, setErr] = useState<string | null>(null);
  const [showPreview, setShowPreview] = useState(false);

  async function load() {
    setLoading(true);
    setErr(null);
    try {
      const data = await apiGet<BOQItem[]>(`/scenarios/${scenarioId}/boq`);
      setRows(Array.isArray(data) ? data : []);
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

  /* Satır toplamları (liste üstünde) */
  const totals = useMemo(() => {
    let rev = 0,
      cogs = 0,
      gm = 0;
    for (const r of rows) {
      const q = num(r.quantity);
      const p = num(r.unit_price);
      const uc = num(r.unit_cogs ?? 0);
      const lr = q * p;
      const lc = q * uc;
      rev += lr;
      cogs += lc;
      gm += lr - lc;
    }
    return { rev, cogs, gm };
  }, [rows]);

  function startAdd() {
    setDraft({
      section: "",
      category: "bulk_with_freight",
      item_name: "",
      unit: "",
      quantity: 0,
      unit_price: 0,
      unit_cogs: 0,
      frequency: "once",
      months: null,
      start_year: null,
      start_month: null,
      is_active: true,
      notes: "",
    });
  }
  function cancelAdd() {
    setDraft(null);
  }

  async function saveNew() {
    if (!draft) return;
    try {
      const created = await apiPost<BOQItem>(`/scenarios/${scenarioId}/boq`, {
        ...draft,
        quantity: num(draft.quantity),
        unit_price: num(draft.unit_price),
        unit_cogs: draft.unit_cogs == null ? null : num(draft.unit_cogs),
        months: draft.months == null ? null : num(draft.months),
      });
      setRows((p) => [...p, created]);
      setDraft(null);
      onChanged?.();
    } catch (e: any) {
      alert(e?.response?.data?.detail || e?.message || "Save failed.");
    }
  }

  async function saveEdit(r: BOQItem) {
    if (!r.id) return;
    try {
      const upd = await apiPut<BOQItem>(`/scenarios/${scenarioId}/boq/${r.id}`, {
        ...r,
        quantity: num(r.quantity),
        unit_price: num(r.unit_price),
        unit_cogs: r.unit_cogs == null ? null : num(r.unit_cogs),
        months: r.months == null ? null : num(r.months),
      });
      setRows((p) => p.map((x) => (x.id === r.id ? upd : x)));
      onChanged?.();
    } catch (e: any) {
      alert(e?.response?.data?.detail || e?.message || "Update failed.");
    }
  }

  async function delRow(r: BOQItem) {
    if (!r.id) return;
    if (!confirm("Delete BOQ item?")) return;
    try {
      await apiDelete(`/scenarios/${scenarioId}/boq/${r.id}`);
      setRows((p) => p.filter((x) => x.id !== r.id));
      onChanged?.();
    } catch (e: any) {
      alert(e?.response?.data?.detail || e?.message || "Delete failed.");
    }
  }

  async function markReady() {
    if (!confirm("Mark BOQ as ready and move to TWC?")) return;
    try {
      await apiPost(`/scenarios/${scenarioId}/boq/mark-ready`, {});
      onChanged?.();
      onMarkedReady?.();
    } catch (e: any) {
      alert(e?.response?.data?.detail || e?.message || "Cannot mark as ready.");
    }
  }

  /* ======= Monthly Preview (strict TS uyumlu) ======= */
  type MonthAgg = { revenue: number; cogs: number; gm: number };

  function getOrInit(map: Map<string, MonthAgg>, key: string): MonthAgg {
    const cur = map.get(key);
    if (cur) return cur;
    const blank: MonthAgg = { revenue: 0, cogs: 0, gm: 0 };
    map.set(key, blank);
    return blank;
  }

  const schedule = useMemo(() => {
    const agg = new Map<string, MonthAgg>();
    const HORIZON = 36;

    const active = rows.filter(
      (r): r is BOQItem & { is_active: true; start_year: number; start_month: number } =>
        !!r.is_active && typeof r.start_year === "number" && typeof r.start_month === "number"
    );

    for (const r of active) {
      const qty = num(r.quantity);
      const price = num(r.unit_price);
      const uc = num(r.unit_cogs ?? 0);
      const lineRev = qty * price;
      const lineCogs = qty * uc;

      const startY = r.start_year!;
      const startM = r.start_month!;

      const freq = r.frequency;
      if (freq === "monthly") {
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
        const key = ymKey(startY, startM);
        const cur = getOrInit(agg, key);
        cur.revenue += lineRev;
        cur.cogs += lineCogs;
        cur.gm += lineRev - lineCogs;
      }
    }

    const rowsOut = [...agg.entries()]
      .map(([key, v]) => ({
        key,
        y: Number(key.slice(0, 4)),
        m: Number(key.slice(5, 7)),
        revenue: v.revenue,
        cogs: v.cogs,
        gm: v.gm,
      }))
      .sort((a, b) => a.y - b.y || a.m - b.m);

    const totals = rowsOut.reduce(
      (s, r) => {
        s.revenue += r.revenue;
        s.cogs += r.cogs;
        s.gm += r.gm;
        return s;
      },
      { revenue: 0, cogs: 0, gm: 0 }
    );

    return { rows: rowsOut, totals };
  }, [rows]);

  /* ========================================================= */

  return (
    <div className="space-y-3">
      <div className="flex items-center justify-between">
        <h3 className="font-semibold text-lg">BOQ (Bill of Quantities)</h3>
        <div className="flex gap-2">
          <button
            onClick={load}
            className="px-3 py-1.5 rounded-md border text-sm hover:bg-gray-50 disabled:opacity-60 disabled:cursor-not-allowed"
            disabled={loading}
          >
            Refresh
          </button>
          <button
            onClick={startAdd}
            className="px-3 py-1.5 rounded-md bg-indigo-600 text-white text-sm hover:bg-indigo-500"
          >
            + Add BOQ Item
          </button>
          <button
            onClick={() => setShowPreview((v) => !v)}
            className="px-3 py-1.5 rounded-md border text-sm hover:bg-gray-50 disabled:opacity-60 disabled:cursor-not-allowed"
            title="Aylık simülasyon (Revenue/COGS/GM)"
          >
            {showPreview ? "Hide Preview" : "Show Preview"}
          </button>
          <button
            onClick={markReady}
            className={cls(
              "px-3 py-1.5 rounded-md text-sm",
              isReady || rows.length === 0
                ? "bg-indigo-300 text-white cursor-not-allowed"
                : "bg-indigo-600 text-white hover:bg-indigo-500"
            )}
            disabled={isReady || rows.length === 0}
            title={
              isReady
                ? "Already marked ready"
                : rows.length === 0
                ? "Add at least one BOQ item first"
                : "Mark BOQ Ready and move to TWC"
            }
          >
            Mark BOQ Ready → TWC
          </button>
        </div>
      </div>

      {err && (
        <div className="text-sm text-red-600 bg-red-50 border border-red-200 p-2 rounded">
          {err}
        </div>
      )}

      <div className="overflow-x-auto border rounded bg-white">
        <table className="min-w-full text-sm">
          <thead className="bg-gray-50">
            <tr>
              <th className="px-3 py-2">Section</th>
              <th className="px-3 py-2">Category</th>
              <th className="px-3 py-2">Item</th>
              <th className="px-3 py-2">Unit</th>
              <th className="px-3 py-2 text-right">Qty</th>
              <th className="px-3 py-2 text-right">Unit Price</th>
              <th className="px-3 py-2 text-right">Unit COGS</th>
              <th className="px-3 py-2">Freq</th>
              <th className="px-3 py-2 text-right">Duration</th>
              <th className="px-3 py-2">Start (Y/M)</th>
              <th className="px-3 py-2">Active</th>
              <th className="px-3 py-2 text-right">Line Rev</th>
              <th className="px-3 py-2 text-right">Line COGS</th>
              <th className="px-3 py-2 text-right">Line GM</th>
              <th className="px-3 py-2 w-36">Actions</th>
            </tr>
          </thead>

          <tbody>
            {draft && (
              <tr className="bg-amber-50/40">
                <td className="px-3 py-2">
                  <input
                    className="w-full px-2 py-1 rounded border border-gray-300"
                    placeholder="Section"
                    value={draft.section ?? ""}
                    onChange={(e) => setDraft({ ...draft, section: e.target.value })}
                  />
                </td>
                <td className="px-3 py-2">
                  <select
                    className="w-full px-2 py-1 rounded border border-gray-300"
                    value={draft.category ?? "bulk_with_freight"}
                    onChange={(e) =>
                      setDraft({
                        ...draft,
                        category: e.target.value as BOQItem["category"],
                      })
                    }
                  >
                    {CATEGORY_OPTIONS.map((c) => (
                      <option key={c || "none"} value={c || "bulk_with_freight"}>
                        {c === "bulk_with_freight"
                          ? "Bulk (w/ Freight)"
                          : c === "bulk_ex_freight"
                          ? "Bulk (ex Freight)"
                          : "Freight"}
                      </option>
                    ))}
                  </select>
                </td>
                <td className="px-3 py-2">
                  <input
                    className="w-full px-2 py-1 rounded border border-gray-300"
                    placeholder="Item"
                    value={draft.item_name}
                    onChange={(e) => setDraft({ ...draft, item_name: e.target.value })}
                  />
                </td>
                <td className="px-3 py-2">
                  <input
                    className="w-full px-2 py-1 rounded border border-gray-300"
                    placeholder="kg"
                    value={draft.unit}
                    onChange={(e) => setDraft({ ...draft, unit: e.target.value })}
                  />
                </td>
                <td className="px-3 py-2">
                  <input
                    type="number"
                    className="w-full px-2 py-1 rounded border border-gray-300 text-right"
                    value={num(draft.quantity)}
                    onChange={(e) => setDraft({ ...draft, quantity: Number(e.target.value) })}
                  />
                </td>
                <td className="px-3 py-2">
                  <input
                    type="number"
                    className="w-full px-2 py-1 rounded border border-gray-300 text-right"
                    value={num(draft.unit_price)}
                    onChange={(e) => setDraft({ ...draft, unit_price: Number(e.target.value) })}
                  />
                </td>
                <td className="px-3 py-2">
                  <input
                    type="number"
                    className="w-full px-2 py-1 rounded border border-gray-300 text-right"
                    value={num(draft.unit_cogs ?? 0)}
                    onChange={(e) => setDraft({ ...draft, unit_cogs: Number(e.target.value) })}
                  />
                </td>
                <td className="px-3 py-2">
                  <select
                    className="w-full px-2 py-1 rounded border border-gray-300"
                    value={draft.frequency}
                    onChange={(e) =>
                      setDraft({
                        ...draft,
                        frequency: e.target.value as BOQItem["frequency"],
                      })
                    }
                  >
                    <option value="once">once</option>
                    <option value="monthly">monthly</option>
                    <option value="per_shipment">per_shipment</option>
                    <option value="per_tonne">per_tonne</option>
                  </select>
                </td>
                <td className="px-3 py-2">
                  <input
                    type="number"
                    className="w-full px-2 py-1 rounded border border-gray-300 text-right"
                    value={draft.months ?? ""}
                    onChange={(e) =>
                      setDraft({
                        ...draft,
                        months: e.target.value === "" ? null : Number(e.target.value),
                      })
                    }
                    title="Duration in months"
                    placeholder="months"
                  />
                </td>
                <td className="px-3 py-2">
                  <MonthInput
                    value={{
                      year: draft.start_year ?? null,
                      month: draft.start_month ?? null,
                    }}
                    onChange={({ year, month }) =>
                      setDraft({ ...draft, start_year: year, start_month: month })
                    }
                  />
                </td>
                <td className="px-3 py-2 text-center">
                  <input
                    type="checkbox"
                    checked={!!draft.is_active}
                    onChange={(e) => setDraft({ ...draft, is_active: e.target.checked })}
                  />
                </td>
                <td className="px-3 py-2 text-right">
                  {(num(draft.quantity) * num(draft.unit_price)).toLocaleString(undefined, {
                    maximumFractionDigits: 2,
                  })}
                </td>
                <td className="px-3 py-2 text-right">
                  {(num(draft.quantity) * num(draft.unit_cogs ?? 0)).toLocaleString(undefined, {
                    maximumFractionDigits: 2,
                  })}
                </td>
                <td className="px-3 py-2 text-right">
                  {(
                    num(draft.quantity) * num(draft.unit_price) -
                    num(draft.quantity) * num(draft.unit_cogs ?? 0)
                  ).toLocaleString(undefined, { maximumFractionDigits: 2 })}
                </td>
                <td className="px-3 py-2">
                  <div className="flex gap-2">
                    <button
                      onClick={saveNew}
                      className="px-2 py-1 rounded border hover:bg-gray-50 text-sm"
                    >
                      Save
                    </button>
                    <button
                      onClick={cancelAdd}
                      className="px-2 py-1 rounded border hover:bg-gray-50 text-sm"
                    >
                      Cancel
                    </button>
                  </div>
                </td>
              </tr>
            )}

            {rows.map((r) => {
              const lineRev = num(r.quantity) * num(r.unit_price);
              const lineCogs = num(r.quantity) * num(r.unit_cogs ?? 0);
              const lineGM = lineRev - lineCogs;

              return (
                <tr key={r.id} className="odd:bg-white even:bg-gray-50">
                  <td className="px-3 py-2">
                    <input
                      className="w-full px-2 py-1 rounded border border-gray-300"
                      value={r.section ?? ""}
                      onChange={(e) =>
                        setRows((p) =>
                          p.map((x) => (x.id === r.id ? { ...x, section: e.target.value } : x))
                        )
                      }
                    />
                  </td>
                  <td className="px-3 py-2">
                    <select
                      className="w-full px-2 py-1 rounded border border-gray-300"
                      value={r.category ?? "bulk_with_freight"}
                      onChange={(e) =>
                        setRows((p) =>
                          p.map((x) =>
                            x.id === r.id
                              ? {
                                  ...x,
                                  category: e.target.value as BOQItem["category"],
                                }
                              : x
                          )
                        )
                      }
                    >
                      {CATEGORY_OPTIONS.map((c) => (
                        <option key={c || "none"} value={c || "bulk_with_freight"}>
                          {c === "bulk_with_freight"
                            ? "Bulk (w/ Freight)"
                            : c === "bulk_ex_freight"
                            ? "Bulk (ex Freight)"
                            : "Freight"}
                        </option>
                      ))}
                    </select>
                  </td>
                  <td className="px-3 py-2">
                    <input
                      className="w-full px-2 py-1 rounded border border-gray-300"
                      value={r.item_name}
                      onChange={(e) =>
                        setRows((p) =>
                          p.map((x) => (x.id === r.id ? { ...x, item_name: e.target.value } : x))
                        )
                      }
                    />
                  </td>
                  <td className="px-3 py-2">
                    <input
                      className="w-full px-2 py-1 rounded border border-gray-300"
                      value={r.unit}
                      onChange={(e) =>
                        setRows((p) => p.map((x) => (x.id === r.id ? { ...x, unit: e.target.value } : x)))
                      }
                    />
                  </td>
                  <td className="px-3 py-2">
                    <input
                      type="number"
                      className="w-full px-2 py-1 rounded border border-gray-300 text-right"
                      value={num(r.quantity)}
                      onChange={(e) =>
                        setRows((p) =>
                          p.map((x) => (x.id === r.id ? { ...x, quantity: Number(e.target.value) } : x))
                        )
                      }
                    />
                  </td>
                  <td className="px-3 py-2">
                    <input
                      type="number"
                      className="w-full px-2 py-1 rounded border border-gray-300 text-right"
                      value={num(r.unit_price)}
                      onChange={(e) =>
                        setRows((p) =>
                          p.map((x) => (x.id === r.id ? { ...x, unit_price: Number(e.target.value) } : x))
                        )
                      }
                    />
                  </td>
                  <td className="px-3 py-2">
                    <input
                      type="number"
                      className="w-full px-2 py-1 rounded border border-gray-300 text-right"
                      value={num(r.unit_cogs ?? 0)}
                      onChange={(e) =>
                        setRows((p) =>
                          p.map((x) => (x.id === r.id ? { ...x, unit_cogs: Number(e.target.value) } : x))
                        )
                      }
                    />
                  </td>
                  <td className="px-3 py-2">
                    <select
                      className="w-full px-2 py-1 rounded border border-gray-300"
                      value={r.frequency}
                      onChange={(e) =>
                        setRows((p) =>
                          p.map((x) =>
                            x.id === r.id
                              ? {
                                  ...x,
                                  frequency: e.target.value as BOQItem["frequency"],
                                }
                              : x
                          )
                        )
                      }
                    >
                      <option value="once">once</option>
                      <option value="monthly">monthly</option>
                      <option value="per_shipment">per_shipment</option>
                      <option value="per_tonne">per_tonne</option>
                    </select>
                  </td>
                  <td className="px-3 py-2">
                    <input
                      type="number"
                      className="w-full px-2 py-1 rounded border border-gray-300 text-right"
                      value={r.months ?? ""}
                      onChange={(e) =>
                        setRows((p) =>
                          p.map((x) =>
                            x.id === r.id
                              ? {
                                  ...x,
                                  months: e.target.value === "" ? null : Number(e.target.value),
                                }
                              : x
                          )
                        )
                      }
                      title="Duration in months"
                      placeholder="months"
                    />
                  </td>
                  <td className="px-3 py-2">
                    <MonthInput
                      value={{
                        year: r.start_year ?? null,
                        month: r.start_month ?? null,
                      }}
                      onChange={({ year, month }) =>
                        setRows((p) =>
                          p.map((x) =>
                            x.id === r.id ? { ...x, start_year: year, start_month: month } : x
                          )
                        )
                      }
                    />
                  </td>
                  <td className="px-3 py-2 text-center">
                    <input
                      type="checkbox"
                      checked={!!r.is_active}
                      onChange={(e) =>
                        setRows((p) =>
                          p.map((x) => (x.id === r.id ? { ...x, is_active: e.target.checked } : x))
                        )
                      }
                    />
                  </td>
                  <td className="px-3 py-2 text-right">
                    {lineRev.toLocaleString(undefined, { maximumFractionDigits: 2 })}
                  </td>
                  <td className="px-3 py-2 text-right">
                    {lineCogs.toLocaleString(undefined, { maximumFractionDigits: 2 })}
                  </td>
                  <td className="px-3 py-2 text-right">
                    {lineGM.toLocaleString(undefined, { maximumFractionDigits: 2 })}
                  </td>
                  <td className="px-3 py-2">
                    <div className="flex gap-2">
                      <button
                        onClick={() => saveEdit(r)}
                        className="px-2 py-1 rounded border hover:bg-gray-50 text-sm"
                      >
                        Save
                      </button>
                      <button
                        onClick={() => delRow(r)}
                        className="px-2 py-1 rounded border hover:bg-gray-50 text-sm"
                      >
                        Delete
                      </button>
                    </div>
                  </td>
                </tr>
              );
            })}
          </tbody>

          <tfoot>
            <tr className="bg-gray-100 font-semibold">
              <td className="px-3 py-2" colSpan={11}>
                Totals
              </td>
              <td className="px-3 py-2 text-right">
                {totals.rev.toLocaleString(undefined, { maximumFractionDigits: 2 })}
              </td>
              <td className="px-3 py-2 text-right">
                {totals.cogs.toLocaleString(undefined, { maximumFractionDigits: 2 })}
              </td>
              <td className="px-3 py-2 text-right">
                {totals.gm.toLocaleString(undefined, { maximumFractionDigits: 2 })}
              </td>
              <td />
            </tr>
          </tfoot>
        </table>
      </div>

      {showPreview && (
        <div className="mt-3 border rounded bg-white">
          <div className="px-3 py-2 border-b bg-gray-50 font-medium">Preview • Monthly schedule (active items)</div>
          <MonthlyPreviewPivot rows={schedule.rows} totals={schedule.totals} />
        </div>
      )}
    </div>
  );
}
