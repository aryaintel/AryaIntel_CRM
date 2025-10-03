// frontend/src/pages/scenario/tabs/TaxTab.tsx
import React, { useEffect, useMemo, useState } from "react";
import { apiGet, apiPost, apiPut, apiDelete, isApiError, ApiError } from "../../../lib/api";

type Props = { scenarioId: number; onMarkedReady?: () => void; isReady?: boolean };

/* =========================
   Types (aligned with backend)
   ========================= */
type TaxType = "vat" | "withholding" | "corp" | "custom";
type AppliesTo = "revenue" | "services" | "capex" | "profit" | "all";

type TaxRule = {
  id?: number;
  scenario_id?: number;

  name: string;
  tax_type: TaxType;
  applies_to: AppliesTo;

  rate_pct: number;
  start_year: number;
  start_month: number;
  end_year?: number | null;
  end_month?: number | null;

  is_inclusive: boolean;
  notes?: string | null;
  is_active: boolean;
};

type ResolveResp = { items: TaxRule[] }; // backend resolve artık liste döndürüyor

// Resolve UI scope (kept simple)
type ResolveScopeUi = "all" | "sales" | "services" | "capex";
const RESOLVE_SCOPES: ResolveScopeUi[] = ["all", "sales", "services", "capex"];

function cls(...a: (string | false | undefined)[]) {
  return a.filter(Boolean).join(" ");
}

// UI -> new backend mapping
const toAppliesTo = (s: ResolveScopeUi): AppliesTo =>
  s === "sales" ? "revenue" : s === "services" ? "services" : s === "capex" ? "capex" : "all";

const TAX_TYPES: TaxType[] = ["vat", "withholding", "corp", "custom"];
const APPLIES: AppliesTo[] = ["revenue", "services", "capex", "profit", "all"];

/* =========================
   Format helpers (en-US, 2 decimals)
   ========================= */
const fmt2 = new Intl.NumberFormat("en-US", { minimumFractionDigits: 2, maximumFractionDigits: 2 });
const fmt0 = new Intl.NumberFormat("en-US", { maximumFractionDigits: 0 });
const fmtPct = (x: any) => {
  const n = Number(x);
  return Number.isFinite(n) ? `${fmt2.format(n)} %` : "0.00 %";
};

const emptyRow = (y: number, m: number): TaxRule => ({
  name: "",
  tax_type: "custom",
  applies_to: "all",
  rate_pct: 0,
  start_year: y,
  start_month: m,
  end_year: null,
  end_month: null,
  is_inclusive: false,
  notes: "",
  is_active: true,
});

export default function TaxTab({ scenarioId, onMarkedReady, isReady }: Props) {
  const [rows, setRows] = useState<TaxRule[]>([]);
  const [loading, setLoading] = useState(false);
  const [err, setErr] = useState<string | null>(null);

  // form
  const [editing, setEditing] = useState<TaxRule | null>(null);
  const [show, setShow] = useState(false);

  // resolve panel
  const now = useMemo(() => {
    const d = new Date();
    return { y: d.getFullYear(), m: d.getMonth() + 1 };
  }, []);
  const [resScope, setResScope] = useState<ResolveScopeUi>("all");
  const [resYear, setResYear] = useState<number>(now.y);
  const [resMonth, setResMonth] = useState<number>(now.m);

  // artık liste tutuyoruz
  const [resolvedItems, setResolvedItems] = useState<TaxRule[] | null>(null);

  // Esnek path’ler (FX ile aynı yaklaşım)
  const listBase = `/scenarios/${scenarioId}/tax`; // GET/POST + resolve
  const idBase = `/scenarios/tax`;                 // tercih edilen PUT/DELETE
  const fallbackIdBase = listBase;                 // bazı kurulumlarda /scenarios/:id/tax/:ruleId

  /* =========================
     Data loading
     ========================= */
  async function reload() {
    setLoading(true);
    setErr(null);
    setResolvedItems(null);
    try {
      const data = await apiGet<any>(`${listBase}`);
      const items: TaxRule[] = Array.isArray(data) ? data : (data?.items ?? []);
      setRows(Array.isArray(items) ? items : []);
    } catch (e: any) {
      const msg =
        (e instanceof ApiError && e.message) || e?.response?.data?.detail || e?.message || "Failed to load tax rules.";
      setRows([]);
      setErr(String(msg));
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    reload();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [scenarioId]);

  /* =========================
     Form open/close
     ========================= */
  function openCreate() {
    setEditing(emptyRow(now.y, now.m));
    setShow(true);
  }
  function openEdit(row: TaxRule) {
    setEditing({ ...row });
    setShow(true);
  }
  function closeForm() {
    setShow(false);
    setEditing(null);
  }

  /* =========================
     Save / Delete / Toggle
     ========================= */
  async function saveForm() {
    if (!editing) return;
    const payload: TaxRule = {
      ...editing,
      rate_pct: Number(editing.rate_pct || 0),
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
      is_inclusive: !!editing.is_inclusive,
      is_active: !!editing.is_active,
    };

    try {
      if (editing.id) {
        try {
          await apiPut<TaxRule>(`${idBase}/${editing.id}`, payload);
        } catch {
          await apiPut<TaxRule>(`${fallbackIdBase}/${editing.id}`, payload);
        }
      } else {
        await apiPost<TaxRule>(`${listBase}`, payload);
      }
      closeForm();
      await reload();
    } catch (e: any) {
      const msg = isApiError(e) ? e.message : e?.response?.data?.detail || e?.message || "Failed to save tax rule.";
      setErr(String(msg));
    }
  }

  async function removeRow(id?: number) {
    if (!id) return;
    if (!confirm("Delete this tax rule?")) return;
    try {
      try {
        await apiDelete(`${idBase}/${id}`);
      } catch {
        await apiDelete(`${fallbackIdBase}/${id}`);
      }
      await reload();
    } catch (e: any) {
      const msg = isApiError(e) ? e.message : e?.response?.data?.detail || e?.message || "Failed to delete.";
      setErr(String(msg));
    }
  }

  async function toggleActive(row: TaxRule) {
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
      const msg = isApiError(e) ? e.message : e?.response?.data?.detail || e?.message || "Failed to update.";
      setErr(String(msg));
    }
  }

  /* =========================
     Resolve (backend list modeline göre)
     ========================= */
  async function resolveTax() {
    setResolvedItems(null);
    setErr(null);

    try {
      const q = new URLSearchParams({
        applies_to: toAppliesTo(resScope), // revenue|services|capex|all
        year: String(resYear),
        month: String(resMonth),
      }).toString();

      const data = await apiGet<ResolveResp>(`${listBase}/resolve?${q}`);
      const items = Array.isArray((data as any)?.items) ? ((data as any).items as TaxRule[]) : [];
      setResolvedItems(items);
    } catch (e: any) {
      const msg = isApiError(e) ? e.message : e?.response?.data?.detail || e?.message || "Resolve failed.";
      setErr(String(msg));
    }
  }

  // En uygun kayıt (backend zaten uygun sıralama döndürüyor)
  const best = useMemo(() => {
    if (!resolvedItems || resolvedItems.length === 0) return null;
    return resolvedItems[0];
  }, [resolvedItems]);

  async function markReady() {
    if (!confirm("Mark TAX as ready and move to SERVICES?")) return;
    try {
      await apiPost(`/scenarios/${scenarioId}/workflow/mark-tax-ready`, {});
      onMarkedReady?.();
    } catch (e: any) {
      alert(e?.response?.data?.detail || e?.message || "Cannot mark TAX as ready.");
    }
  }

  /* =========================
     Render
     ========================= */
  return (
    <div className="space-y-4">
      {/* Header */}
      <div className="flex items-center justify-between">
        <h3 className="text-xl font-semibold">Tax Rules</h3>
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
            + New Rule
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
                ? "Add at least one tax rule first"
                : "Mark TAX as ready and move to SERVICES"
            }
          >
            Mark TAX Ready →
          </button>
        </div>
      </div>

      {err && <div className="p-3 rounded-md border border-red-300 bg-red-50 text-red-700">{err}</div>}

      {/* Table */}
      <div className="overflow-auto border rounded-xl bg-white">
        <table className="min-w-full text-sm">
          <thead className="bg-gray-50 text-gray-700">
            <tr>
              <th className="p-2 text-left">Name</th>
              <th className="p-2 text-left">Type</th>
              <th className="p-2 text-left">Scope</th>
              <th className="p-2 text-right">Rate %</th>
              <th className="p-2 text-left">Start</th>
              <th className="p-2 text-left">End</th>
              <th className="p-2 text-center">Inclusive</th>
              <th className="p-2 text-center">Active</th>
              <th className="p-2 text-right">Actions</th>
            </tr>
          </thead>
          <tbody>
            {loading ? (
              <tr>
                <td className="p-3" colSpan={9}>
                  Loading…
                </td>
              </tr>
            ) : rows.length === 0 ? (
              <tr>
                <td className="p-4 text-gray-500" colSpan={9}>
                  No tax rules yet. Use <b>+ New Rule</b>.
                </td>
              </tr>
            ) : (
              rows.map((r) => (
                <tr key={r.id} className="border-t">
                  <td className="p-2">{r.name}</td>
                  <td className="p-2">{r.tax_type}</td>
                  <td className="p-2">{r.applies_to}</td>
                  <td className="p-2 text-right">{fmtPct(r.rate_pct)}</td>
                  <td className="p-2">
                    {fmt0.format(r.start_year)}/{String(r.start_month).padStart(2, "0")}
                  </td>
                  <td className="p-2">
                    {r.end_year != null && r.end_month != null
                      ? `${fmt0.format(r.end_year)}/${String(r.end_month).padStart(2, "0")}`
                      : "—"}
                  </td>
                  <td className="p-2 text-center">
                    <input type="checkbox" checked={!!r.is_inclusive} readOnly />
                  </td>
                  <td className="p-2 text-center">
                    <input type="checkbox" checked={!!r.is_active} onChange={() => toggleActive(r)} />
                  </td>
                  <td className="p-2 text-right">
                    <button className="px-2 py-1 rounded-md border mr-2 hover:bg-gray-50" onClick={() => openEdit(r)}>
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
        <div className="grid grid-cols-1 md:grid-cols-4 gap-3 items-end">
          <div>
            <div className="text-xs text-gray-600">Scope</div>
            <select
              className="border rounded-md px-2 py-1 w-full"
              value={resScope}
              onChange={(e) => setResScope(e.target.value as ResolveScopeUi)}
            >
              {RESOLVE_SCOPES.map((a) => (
                <option key={a} value={a}>
                  {a}
                </option>
              ))}
            </select>
          </div>
          <div>
            <div className="text-xs text-gray-600">Year</div>
            <input
              type="number"
              lang="en-US"
              className="border rounded-md px-2 py-1 w-full"
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
              lang="en-US"
              className="border rounded-md px-2 py-1 w-full"
              value={resMonth}
              onChange={(e) => setResMonth(Number(e.target.value))}
            />
          </div>
          <div className="flex">
            <button className="ml-auto px-3 py-2 rounded-md border hover:bg-gray-50" onClick={resolveTax}>
              Resolve Tax
            </button>
          </div>
        </div>

        {best && (
          <div className="mt-3 text-sm">
            <div>
              <span className="text-gray-600 mr-1">Result:</span>
              <b>
                {best.applies_to} @ {fmt0.format(resYear)}/{String(resMonth).padStart(2, "0")} → {fmtPct(best.rate_pct)}
              </b>
            </div>
            <div className="text-gray-500">
              {best.name ? `name: ${best.name}` : ""}
              {` • type: ${best.tax_type}`}
              {` • inclusive: ${best.is_inclusive ? "yes" : "no"}`}
            </div>
          </div>
        )}

        {resolvedItems && resolvedItems.length > 1 && (
          <div className="mt-2 text-xs text-gray-500">
            {resolvedItems.length - 1} more matching rule(s) (ordered by most recent first)
          </div>
        )}
      </div>

      {/* Drawer / Form */}
      {show && editing && (
        <div className="fixed inset-0 bg-black/30 z-40 flex items-end sm:items-center justify-center">
          <div className="bg-white w-full sm:max-w-3xl rounded-t-2xl sm:rounded-2xl shadow-xl p-4 sm:p-6 space-y-4">
            <div className="flex items-center justify-between">
              <h4 className="text-lg font-semibold">{editing.id ? "Edit Tax Rule" : "New Tax Rule"}</h4>
              <button className="px-3 py-1 rounded-md border" onClick={closeForm}>
                Close
              </button>
            </div>

            <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
              <div>
                <label className="text-xs text-gray-600">Name *</label>
                <input
                  className="w-full border rounded-md px-2 py-1"
                  value={editing.name}
                  onChange={(e) => setEditing((s) => s && { ...s, name: e.target.value })}
                />
              </div>

              <div>
                <label className="text-xs text-gray-600">Type</label>
                <select
                  className="w-full border rounded-md px-2 py-1"
                  value={editing.tax_type}
                  onChange={(e) => setEditing((s) => s && { ...s, tax_type: e.target.value as TaxType })}
                >
                  {TAX_TYPES.map((t) => (
                    <option key={t} value={t}>
                      {t}
                    </option>
                  ))}
                </select>
              </div>

              <div>
                <label className="text-xs text-gray-600">Scope (applies_to)</label>
                <select
                  className="w-full border rounded-md px-2 py-1"
                  value={editing.applies_to}
                  onChange={(e) => setEditing((s) => s && { ...s, applies_to: e.target.value as AppliesTo })}
                >
                  {APPLIES.map((a) => (
                    <option key={a} value={a}>
                      {a}
                    </option>
                  ))}
                </select>
              </div>

              <div>
                <label className="text-xs text-gray-600">Rate %</label>
                <input
                  type="number"
                  step="0.01"
                  lang="en-US"
                  className="w-full border rounded-md px-2 py-1 text-right"
                  value={editing.rate_pct}
                  onChange={(e) => setEditing((s) => s && { ...s, rate_pct: Number(e.target.value) })}
                />
              </div>

              <div className="grid grid-cols-2 gap-2">
                <div>
                  <label className="text-xs text-gray-600">Start Year</label>
                  <input
                    type="number"
                    lang="en-US"
                    className="w-full border rounded-md px-2 py-1"
                    value={editing.start_year}
                    onChange={(e) => setEditing((s) => s && { ...s, start_year: Number(e.target.value) })}
                  />
                </div>
                <div>
                  <label className="text-xs text-gray-600">Start Month</label>
                  <input
                    type="number"
                    min={1}
                    max={12}
                    lang="en-US"
                    className="w-full border rounded-md px-2 py-1"
                    value={editing.start_month}
                    onChange={(e) => setEditing((s) => s && { ...s, start_month: Number(e.target.value) })}
                  />
                </div>
              </div>

              <div className="grid grid-cols-2 gap-2">
                <div>
                  <label className="text-xs text-gray-600">End Year (optional)</label>
                  <input
                    type="number"
                    lang="en-US"
                    className="w-full border rounded-md px-2 py-1"
                    value={editing.end_year ?? ""}
                    onChange={(e) =>
                      setEditing((s) => s && { ...s, end_year: e.target.value === "" ? null : Number(e.target.value) })
                    }
                  />
                </div>
                <div>
                  <label className="text-xs text-gray-600">End Month (optional)</label>
                  <input
                    type="number"
                    min={1}
                    max={12}
                    lang="en-US"
                    className="w-full border rounded-md px-2 py-1"
                    value={editing.end_month ?? ""}
                    onChange={(e) =>
                      setEditing((s) => s && { ...s, end_month: e.target.value === "" ? null : Number(e.target.value) })
                    }
                  />
                </div>
              </div>

              <div className="flex items-center gap-2">
                <input
                  id="inclTax"
                  type="checkbox"
                  checked={!!editing.is_inclusive}
                  onChange={(e) => setEditing((s) => s && { ...s, is_inclusive: e.target.checked })}
                />
                <label htmlFor="inclTax" className="text-sm">
                  Inclusive (price includes tax)
                </label>
              </div>

              <div className="sm:col-span-2">
                <label className="text-xs text-gray-600">Notes</label>
                <textarea
                  className="w-full border rounded-md px-2 py-1"
                  rows={3}
                  value={editing.notes ?? ""}
                  onChange={(e) => setEditing((s) => s && { ...s, notes: e.target.value })}
                />
              </div>

              <div className="flex items-center gap-2">
                <input
                  id="activeTax"
                  type="checkbox"
                  checked={!!editing.is_active}
                  onChange={(e) => setEditing((s) => s && { ...s, is_active: e.target.checked })}
                />
                <label htmlFor="activeTax" className="text-sm">
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
