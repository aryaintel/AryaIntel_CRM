// frontend/src/pages/scenario/tabs/FXTab.tsx
import React, { useEffect, useMemo, useState } from "react";
import { apiGet, apiPost, apiPut, apiDelete, ApiError } from "../../../lib/api";

type Props = {
  scenarioId: number;
  onMarkedReady?: () => void;
  isReady?: boolean;
};

type FXRate = {
  id?: number;
  scenario_id?: number;
  currency: string;           // e.g. USD, EUR
  rate_to_base: number;       // to scenario base
  start_year: number;
  start_month: number;        // 1..12
  end_year?: number | null;
  end_month?: number | null;
  source?: string | null;     // manual|cbrt|ecb|...
  notes?: string | null;
  is_active: boolean;
};

type ResolveResponse = {
  scenario_id: number;
  currency: string;
  year: number;
  month: number;
  rate_to_base: number | null;
  source?: string | null;
  matched_rule_id?: number | null;
};

function cls(...a: (string | false | undefined)[]) {
  return a.filter(Boolean).join(" ");
}
const ISO = (s: string) => s.toUpperCase().trim();

const emptyRow = (y: number, m: number): FXRate => ({
  currency: "USD",
  rate_to_base: 1,
  start_year: y,
  start_month: m,
  end_year: null,
  end_month: null,
  source: "manual",
  notes: "",
  is_active: true,
});

export default function FXTab({ scenarioId, onMarkedReady, isReady }: Props) {
  const [rows, setRows] = useState<FXRate[]>([]);
  const [loading, setLoading] = useState(false);
  const [err, setErr] = useState<string | null>(null);

  // form/drawer
  const [editing, setEditing] = useState<FXRate | null>(null);
  const [show, setShow] = useState(false);

  // resolve panel
  const now = useMemo(() => {
    const d = new Date();
    return { y: d.getFullYear(), m: d.getMonth() + 1 };
  }, []);
  const [resCurrency, setResCurrency] = useState("USD");
  const [resYear, setResYear] = useState<number>(now.y);
  const [resMonth, setResMonth] = useState<number>(now.m);
  const [resolved, setResolved] = useState<ResolveResponse | null>(null);

  // Base URL'ler (PUT/DELETE iki varyasyonu da destekle)
  const listBase = `/scenarios/${scenarioId}/fx`; // GET/POST + resolve
  const idBase = `/scenarios/fx`;                 // tercih edilen PUT/DELETE
  const fallbackIdBase = listBase;                // bazı kurulumlarda PUT/DELETE aynı list path’inde olabilir

  async function reload() {
    setLoading(true);
    setErr(null);
    try {
      // Backend iki farklı biçimde dönebiliyor: [] ya da {items:[...]}
      const data = await apiGet<any>(`${listBase}`);
      const items: FXRate[] = Array.isArray(data) ? data : (data?.items ?? []);
      setRows(Array.isArray(items) ? items : []);
    } catch (e: any) {
      const msg =
        (e instanceof ApiError && e.message) ||
        e?.response?.data?.detail ||
        e?.message ||
        "Failed to load FX rates.";
      setErr(String(msg));
      setRows([]);
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    reload();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [scenarioId]);

  function openCreate() {
    setEditing(emptyRow(now.y, now.m));
    setShow(true);
  }
  function openEdit(row: FXRate) {
    setEditing({ ...row });
    setShow(true);
  }
  function closeForm() {
    setShow(false);
    setEditing(null);
  }

  async function saveForm() {
    if (!editing) return;
    const payload: FXRate = {
      ...editing,
      currency: ISO(editing.currency || "USD"),
      rate_to_base: Number(editing.rate_to_base || 0),
      start_year: Number(editing.start_year),
      start_month: Number(editing.start_month),
      end_year:
        editing.end_year === undefined || editing.end_year === null || (editing.end_year as any) === ""
          ? null
          : Number(editing.end_year),
      end_month:
        editing.end_month === undefined || editing.end_month === null || (editing.end_month as any) === ""
          ? null
          : Number(editing.end_month),
      is_active: !!editing.is_active,
    };

    try {
      if (editing.id) {
        // Önce tercih edilen /scenarios/fx/:id
        try {
          await apiPut<FXRate>(`${idBase}/${editing.id}`, payload);
        } catch {
          // Eski sürüm uyumluluğu: /scenarios/:scenarioId/fx/:id
          await apiPut<FXRate>(`${fallbackIdBase}/${editing.id}`, payload);
        }
      } else {
        await apiPost<FXRate>(`${listBase}`, payload);
      }
      closeForm();
      await reload();
    } catch (e: any) {
      setErr(e?.response?.data?.detail || e?.message || "Failed to save FX rate.");
    }
  }

  async function removeRow(id?: number) {
    if (!id) return;
    if (!confirm("Delete this FX rate?")) return;
    try {
      try {
        await apiDelete(`${idBase}/${id}`);
      } catch {
        await apiDelete(`${fallbackIdBase}/${id}`);
      }
      await reload();
    } catch (e: any) {
      setErr(e?.response?.data?.detail || e?.message || "Failed to delete.");
    }
  }

  async function toggleActive(row: FXRate) {
    if (!row.id) return;
    try {
      const body = { ...row, is_active: !row.is_active };
      try {
        await apiPut(`${idBase}/${row.id}`, body);
      } catch {
        await apiPut(`${fallbackIdBase}/${row.id}`, body);
      }
      await reload();
    } catch (e: any) {
      setErr(e?.response?.data?.detail || e?.message || "Failed to update.");
    }
  }

  async function resolveRate() {
    setErr(null);
    setResolved(null);
    try {
      const q = new URLSearchParams({
        currency: ISO(resCurrency),
        year: String(resYear),
        month: String(resMonth),
      }).toString();
      const data = await apiGet<ResolveResponse>(`${listBase}/resolve?${q}`);
      setResolved(data);
    } catch (e: any) {
      setErr(e?.response?.data?.detail || e?.message || "Resolve failed.");
    }
  }

  async function markReady() {
    if (!confirm("Mark FX as ready and move to TAX?")) return;
    try {
      await apiPost(`/scenarios/${scenarioId}/workflow/mark-fx-ready`, {});
      onMarkedReady?.();
    } catch (e: any) {
      alert(e?.response?.data?.detail || e?.message || "Cannot mark FX as ready.");
    }
  }

  return (
    <div className="space-y-4">
      {/* Header */}
      <div className="flex items-center justify-between">
        <h3 className="text-xl font-semibold">FX Rates</h3>
        <div className="flex flex-wrap gap-2 justify-end">
          <button
            onClick={reload}
            className={cls(
              "px-3 py-1.5 rounded-md border text-sm hover:bg-gray-50 disabled:opacity-60 disabled:cursor-not-allowed",
              loading && "cursor-progress"
            )}
            disabled={loading}
          >
            Refresh
          </button>
          <button
            onClick={openCreate}
            className="px-3 py-1.5 rounded-md border text-sm hover:bg-gray-50"
          >
            + New Rate
          </button>
          <button
            onClick={markReady}
            className={cls(
              "px-3 py-1.5 rounded-md bg-indigo-600 text-white text-sm hover:bg-indigo-500",
              (isReady || rows.length === 0) && "opacity-60 cursor-not-allowed"
            )}
            disabled={isReady || rows.length === 0}
            title={
              isReady
                ? "Already marked ready"
                : rows.length === 0
                ? "Add at least one FX rate first"
                : "Mark FX as ready and move to TAX"
            }
          >
            Mark FX Ready →
          </button>
        </div>
      </div>

      {err && (
        <div className="p-3 rounded-md border border-red-300 bg-red-50 text-red-700">
          {err}
        </div>
      )}

      {/* Table */}
      <div className="overflow-auto border rounded-xl bg-white">
        <table className="min-w-full text-sm">
          <thead className="bg-gray-50 text-gray-700">
            <tr>
              <th className="p-2 text-left">Currency</th>
              <th className="p-2 text-right">Rate → Base</th>
              <th className="p-2 text-left">Start</th>
              <th className="p-2 text-left">End</th>
              <th className="p-2 text-left">Source</th>
              <th className="p-2 text-left">Notes</th>
              <th className="p-2 text-center">Active</th>
              <th className="p-2 text-right">Actions</th>
            </tr>
          </thead>
          <tbody>
            {loading ? (
              <tr>
                <td className="p-3" colSpan={8}>
                  Loading…
                </td>
              </tr>
            ) : rows.length === 0 ? (
              <tr>
                <td className="p-4 text-gray-500" colSpan={8}>
                  No FX rates yet. Use <b>+ New Rate</b>.
                </td>
              </tr>
            ) : (
              rows.map((r) => (
                <tr key={r.id} className="border-t">
                  <td className="p-2">{r.currency}</td>
                  <td className="p-2 text-right">
                    {Number(r.rate_to_base || 0).toLocaleString(undefined, {
                      maximumFractionDigits: 6,
                    })}
                  </td>
                  <td className="p-2">
                    {r.start_year}/{String(r.start_month).padStart(2, "0")}
                  </td>
                  <td className="p-2">
                    {r.end_year && r.end_month
                      ? `${r.end_year}/${String(r.end_month).padStart(2, "0")}`
                      : "—"}
                  </td>
                  <td className="p-2">{r.source || "—"}</td>
                  <td className="p-2">{r.notes || "—"}</td>
                  <td className="p-2 text-center">
                    <input
                      type="checkbox"
                      checked={!!r.is_active}
                      onChange={() => toggleActive(r)}
                    />
                  </td>
                  <td className="p-2 text-right">
                    <button
                      className="px-2 py-1 rounded-md border mr-2 hover:bg-gray-50"
                      onClick={() => openEdit(r)}
                    >
                      Edit
                    </button>
                    <button
                      className="px-2 py-1 rounded-md border hover:bg-red-50 text-red-600"
                      onClick={() => removeRow(r.id)}
                    >
                      Delete
                    </button>
                  </td>
                </tr>
              ))
            )}
          </tbody>
        </table>
      </div>

      {/* Resolve panel */}
      <div className="border rounded-xl p-3 sm:p-4 bg-white">
        <div className="flex items-end gap-3 flex-wrap">
          <div>
            <div className="text-xs text-gray-600">Currency</div>
            <input
              className="border rounded-md px-2 py-1 uppercase"
              value={resCurrency}
              onChange={(e) => setResCurrency(e.target.value)}
            />
          </div>
          <div>
            <div className="text-xs text-gray-600">Year</div>
            <input
              type="number"
              className="border rounded-md px-2 py-1"
              value={resYear}
              onChange={(e) => setResYear(Number(e.target.value))}
            />
          </div>
          <div>
            <div className="text-xs text-gray-600">Month</div>
            <input
              type="number"
              min={1}
              max={12}
              className="border rounded-md px-2 py-1"
              value={resMonth}
              onChange={(e) => setResMonth(Number(e.target.value))}
            />
          </div>
          <button
            className="px-3 py-2 rounded-md border hover:bg-gray-50"
            onClick={resolveRate}
          >
            Resolve Rate
          </button>
        </div>

        {resolved && (
          <div className="mt-3 text-sm">
            <div>
              <span className="text-gray-600 mr-1">Result:</span>
              <b>
                {resolved.currency} @ {resolved.year}/
                {String(resolved.month).padStart(2, "0")} →{" "}
                {resolved.rate_to_base == null
                  ? "—"
                  : resolved.rate_to_base.toLocaleString(undefined, {
                      maximumFractionDigits: 6,
                    })}
              </b>
            </div>
            <div className="text-gray-500">
              {resolved.source ? `source: ${resolved.source}` : ""}{" "}
              {resolved.matched_rule_id ? `(rule #${resolved.matched_rule_id})` : ""}
            </div>
          </div>
        )}
      </div>

      {/* Drawer / Form */}
      {show && editing && (
        <div className="fixed inset-0 bg-black/30 z-40 flex items-end sm:items-center justify-center">
          <div className="bg-white w-full sm:max-w-2xl rounded-t-2xl sm:rounded-2xl shadow-xl p-4 sm:p-6 space-y-4">
            <div className="flex items-center justify-between">
              <h4 className="text-lg font-semibold">
                {editing.id ? "Edit FX Rate" : "New FX Rate"}
              </h4>
              <button className="px-3 py-1 rounded-md border" onClick={closeForm}>
                Close
              </button>
            </div>

            <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
              <div>
                <label className="text-xs text-gray-600">Currency (ISO-4217) *</label>
                <input
                  className="w-full border rounded-md px-2 py-1 uppercase"
                  value={editing.currency}
                  onChange={(e) =>
                    setEditing((s) => s && { ...s, currency: e.target.value })
                  }
                />
              </div>
              <div>
                <label className="text-xs text-gray-600">Rate to Base *</label>
                <input
                  type="number"
                  step="0.000001"
                  className="w-full border rounded-md px-2 py-1 text-right"
                  value={editing.rate_to_base}
                  onChange={(e) =>
                    setEditing((s) => s && { ...s, rate_to_base: Number(e.target.value) })
                  }
                />
              </div>

              <div className="grid grid-cols-2 gap-2">
                <div>
                  <label className="text-xs text-gray-600">Start Year</label>
                  <input
                    type="number"
                    className="w-full border rounded-md px-2 py-1"
                    value={editing.start_year}
                    onChange={(e) =>
                      setEditing((s) => s && { ...s, start_year: Number(e.target.value) })
                    }
                  />
                </div>
                <div>
                  <label className="text-xs text-gray-600">Start Month</label>
                  <input
                    type="number"
                    min={1}
                    max={12}
                    className="w-full border rounded-md px-2 py-1"
                    value={editing.start_month}
                    onChange={(e) =>
                      setEditing((s) => s && { ...s, start_month: Number(e.target.value) })
                    }
                  />
                </div>
              </div>

              <div className="grid grid-cols-2 gap-2">
                <div>
                  <label className="text-xs text-gray-600">End Year (optional)</label>
                  <input
                    type="number"
                    className="w-full border rounded-md px-2 py-1"
                    value={editing.end_year ?? ""}
                    onChange={(e) =>
                      setEditing(
                        (s) =>
                          s && {
                            ...s,
                            end_year: e.target.value === "" ? null : Number(e.target.value),
                          }
                      )
                    }
                  />
                </div>
                <div>
                  <label className="text-xs text-gray-600">End Month (optional)</label>
                  <input
                    type="number"
                    min={1}
                    max={12}
                    className="w-full border rounded-md px-2 py-1"
                    value={editing.end_month ?? ""}
                    onChange={(e) =>
                      setEditing(
                        (s) =>
                          s && {
                            ...s,
                            end_month: e.target.value === "" ? null : Number(e.target.value),
                          }
                      )
                    }
                  />
                </div>
              </div>

              <div>
                <label className="text-xs text-gray-600">Source</label>
                <input
                  className="w-full border rounded-md px-2 py-1"
                  value={editing.source ?? ""}
                  onChange={(e) =>
                    setEditing((s) => s && { ...s, source: e.target.value })
                  }
                />
              </div>

              <div className="sm:col-span-2">
                <label className="text-xs text-gray-600">Notes</label>
                <textarea
                  className="w-full border rounded-md px-2 py-1"
                  rows={3}
                  value={editing.notes ?? ""}
                  onChange={(e) =>
                    setEditing((s) => s && { ...s, notes: e.target.value })
                  }
                />
              </div>

              <div className="flex items-center gap-2">
                <input
                  id="fxActive"
                  type="checkbox"
                  checked={!!editing.is_active}
                  onChange={(e) =>
                    setEditing((s) => s && { ...s, is_active: e.target.checked })
                  }
                />
                <label htmlFor="fxActive" className="text-sm">
                  Active
                </label>
              </div>
            </div>

            <div className="flex items-center justify-end gap-2">
              <button className="px-3 py-2 rounded-md border" onClick={closeForm}>
                Cancel
              </button>
              <button className="px-3 py-2 rounded-md bg-black text-white" onClick={saveForm}>
                Save
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
