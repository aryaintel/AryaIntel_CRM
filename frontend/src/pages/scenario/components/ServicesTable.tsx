// frontend/src/pages/scenario/components/ServicesTable.tsx
import React, { useEffect, useMemo, useState } from "react";
import { apiGet, apiPost, apiPut, apiDelete } from "../../../lib/api";

function cls(...a: (string | false | undefined)[]): string {
  return a.filter(Boolean).join(" ");
}

type PaymentTerm = "monthly" | "annual_prepaid" | "one_time";
type CashOutPolicy = "service_month" | "start_month" | "contract_anniversary";
type EscalationFreq = "annual" | "none";

export type ServiceRow = {
  id?: number;
  scenario_id?: number;

  // Basics
  service_name: string;
  category?: string | null;
  vendor?: string | null;
  unit?: string | null;

  // Price / quantity
  quantity: number | string;
  unit_cost: number | string;
  currency: string;

  // Timing
  start_year: number | string;
  start_month: number | string;
  duration_months?: number | null | string;
  end_year?: number | null | string;
  end_month?: number | null | string;

  // Payment / cash
  payment_term: PaymentTerm;
  cash_out_month_policy: CashOutPolicy;

  // Escalation
  escalation_pct: number | string;
  escalation_freq: EscalationFreq;

  // Tax
  tax_rate: number | string;
  expense_includes_tax: boolean;

  // Other
  notes?: string | null;
  is_active: boolean;
};

type Props = {
  scenarioId: number;
  onMarkedReady?: () => void;
  isReady?: boolean;
  token?: string; // optional — api helpers already read from storage
};

// ---------------------------------

const paymentTerms: PaymentTerm[] = ["monthly", "annual_prepaid", "one_time"];
const cashPolicies: CashOutPolicy[] = ["service_month", "start_month", "contract_anniversary"];
const escalationFreqs: EscalationFreq[] = ["annual", "none"];

// ortak gri buton stili
const BTN_BASE =
  "px-3 py-1.5 rounded-md border text-sm hover:bg-gray-50 disabled:opacity-60 disabled:cursor-not-allowed";
const BTN_PRIMARY =
  "px-3 py-1.5 rounded-md bg-indigo-600 text-white text-sm hover:bg-indigo-500 disabled:opacity-60 disabled:cursor-not-allowed";
const BTN_SMALL = "px-2 py-1 rounded border text-sm hover:bg-gray-50";

const emptyRow = (year: number, month: number): ServiceRow => ({
  service_name: "",
  category: "",
  vendor: "",
  unit: "",
  quantity: 1,
  unit_cost: 0,
  currency: "TRY",
  start_year: year,
  start_month: month,
  duration_months: null,
  end_year: null,
  end_month: null,
  payment_term: "monthly",
  cash_out_month_policy: "service_month",
  escalation_pct: 0,
  escalation_freq: "none",
  tax_rate: 0,
  expense_includes_tax: false,
  notes: "",
  is_active: true,
});

// "4,5" -> 4.5 güvenli dönüşüm
function toNum(v: any, fallback = 0): number {
  if (v === null || typeof v === "undefined") return fallback;
  const s = String(v).trim().replace(",", ".");
  const n = Number(s);
  return Number.isFinite(n) ? n : fallback;
}

export default function ServicesTable({ scenarioId, onMarkedReady, isReady }: Props) {
  const [rows, setRows] = useState<ServiceRow[]>([]);
  const [loading, setLoading] = useState(false);
  const [err, setErr] = useState<string | null>(null);

  const [editing, setEditing] = useState<ServiceRow | null>(null);
  const [showForm, setShowForm] = useState(false);

  // default year/month (today) – if you prefer scenario start date, wire it in
  const now = useMemo(() => {
    const d = new Date();
    return { y: d.getFullYear(), m: d.getMonth() + 1 };
  }, []);

  const baseUrl = `/scenarios/${scenarioId}/services`;

  async function reload() {
    setLoading(true);
    setErr(null);
    try {
      const data = await apiGet<ServiceRow[]>(`${baseUrl}`);
      setRows(Array.isArray(data) ? data : []);
    } catch (e: any) {
      setErr(e?.response?.data?.detail || e?.message || "Failed to load services.");
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
    setShowForm(true);
  }
  function openEdit(row: ServiceRow) {
    setEditing({ ...row });
    setShowForm(true);
  }
  function closeForm() {
    setShowForm(false);
    setEditing(null);
  }

  async function saveForm() {
    if (!editing) return;
    const payload = {
      ...editing,
      service_name: (editing.service_name || "").trim(),
      currency: (editing.currency || "").toUpperCase().trim() || "TRY",
      quantity: toNum(editing.quantity, 0),
      unit_cost: toNum(editing.unit_cost, 0),
      escalation_pct: toNum(editing.escalation_pct, 0),
      tax_rate: toNum(editing.tax_rate, 0),
      start_year: toNum(editing.start_year, now.y),
      start_month: toNum(editing.start_month, now.m),
      duration_months:
        editing.duration_months === "" || editing.duration_months == null
          ? null
          : toNum(editing.duration_months, 0),
      end_year: editing.end_year === "" || editing.end_year == null ? null : toNum(editing.end_year, now.y),
      end_month: editing.end_month === "" || editing.end_month == null ? null : toNum(editing.end_month, now.m),
      escalation_freq: toNum(editing.escalation_pct, 0) > 0 ? "annual" : "none",
    };

    try {
      if (editing.id) {
        await apiPut<ServiceRow>(`${baseUrl}/${editing.id}`, payload);
      } else {
        await apiPost<ServiceRow>(`${baseUrl}`, payload);
      }
      closeForm();
      await reload();
    } catch (e: any) {
      setErr(e?.response?.data?.detail || e?.message || "Failed to save service.");
    }
  }

  async function removeRow(id?: number) {
    if (!id) return;
    if (!confirm("Delete this service?")) return;
    try {
      await apiDelete(`${baseUrl}/${id}`);
      await reload();
    } catch (e: any) {
      setErr(e?.response?.data?.detail || e?.message || "Failed to delete service.");
    }
  }

  async function toggleActive(row: ServiceRow) {
    if (!row.id) return;
    try {
      await apiPut<ServiceRow>(`${baseUrl}/${row.id}`, {
        ...row,
        is_active: !row.is_active,
      });
      await reload();
    } catch (e: any) {
      setErr(e?.response?.data?.detail || e?.message || "Failed to update service.");
    }
  }

  async function markReady() {
    if (!confirm("Mark SERVICES as ready and move to P&L?")) return;
    try {
      await apiPost(`/scenarios/${scenarioId}/workflow/mark-services-ready`, {});
      onMarkedReady?.();
    } catch (e: any) {
      alert(e?.response?.data?.detail || e?.message || "Cannot mark SERVICES as ready.");
    }
  }

  return (
    <div className="space-y-3">
      <div className="flex items-center justify-between">
        <h3 className="font-semibold text-lg">Services (OPEX)</h3>
        <div className="flex gap-2">
          <button onClick={reload} className={BTN_BASE} disabled={loading}>
            Refresh
          </button>
          <button onClick={openCreate} className={BTN_BASE}>
            + New Service
          </button>
          <button
            onClick={markReady}
            className={BTN_PRIMARY}
            disabled={isReady || rows.length === 0}
            title={
              isReady
                ? "Already marked ready"
                : rows.length === 0
                ? "Add at least one service first"
                : "Mark SERVICES as ready and move to P&L"
            }
          >
            Mark SERVICES Ready &rarr; P&L
          </button>
        </div>
      </div>

      {err && <div className="p-3 rounded-md border border-red-300 bg-red-50 text-red-700">{err}</div>}

      <div className="overflow-x-auto border rounded bg-white">
        <table className="min-w-full text-sm">
          <thead className="bg-gray-50 text-gray-700">
            <tr>
              <th className="px-3 py-2 text-left">Name</th>
              <th className="px-3 py-2 text-left">Category</th>
              <th className="px-3 py-2 text-left">Vendor</th>
              <th className="px-3 py-2 text-right">Qty</th>
              <th className="px-3 py-2 text-right">Unit Cost</th>
              <th className="px-3 py-2 text-left">Currency</th>
              <th className="px-3 py-2 text-left">Start (Y/M)</th>
              <th className="px-3 py-2 text-left">Duration (mo)</th>
              <th className="px-3 py-2 text-left">Payment</th>
              <th className="px-3 py-2 text-left">Esc.</th>
              <th className="px-3 py-2 text-right">Tax %</th>
              <th className="px-3 py-2 text-center">Active</th>
              <th className="px-3 py-2 text-right">Monthly total</th>
              <th className="px-3 py-2 text-right">Actions</th>
            </tr>
          </thead>
          <tbody>
            {loading ? (
              <tr>
                <td className="px-3 py-4 text-center text-gray-500" colSpan={14}>
                  Loading…
                </td>
              </tr>
            ) : rows.length === 0 ? (
              <tr>
                <td className="px-3 py-4 text-center text-gray-500" colSpan={14}>
                  No records yet. Use <b>+ New Service</b> to add.
                </td>
              </tr>
            ) : (
              rows.map((r) => {
                const monthly = toNum(r.quantity, 0) * toNum(r.unit_cost, 0);
                return (
                  <tr key={r.id} className="odd:bg-white even:bg-gray-50 border-t">
                    <td className="px-3 py-2">{r.service_name}</td>
                    <td className="px-3 py-2">{r.category}</td>
                    <td className="px-3 py-2">{r.vendor}</td>
                    <td className="px-3 py-2 text-right">{toNum(r.quantity, 0)}</td>
                    <td className="px-3 py-2 text-right">
                      {toNum(r.unit_cost, 0).toLocaleString(undefined, { maximumFractionDigits: 2 })}
                    </td>
                    <td className="px-3 py-2">{r.currency}</td>
                    <td className="px-3 py-2">
                      {toNum(r.start_year, now.y)}/{String(toNum(r.start_month, now.m)).padStart(2, "0")}
                    </td>
                    <td className="px-3 py-2">
                      {r.duration_months == null || r.duration_months === "" ? "—" : toNum(r.duration_months, 0)}
                    </td>
                    <td className="px-3 py-2">{r.payment_term}</td>
                    <td className="px-3 py-2">
                      {r.escalation_freq === "annual" ? `${toNum(r.escalation_pct, 0)}% (annual)` : "—"}
                    </td>
                    <td className="px-3 py-2 text-right">{toNum(r.tax_rate, 0)}</td>
                    <td className="px-3 py-2 text-center">
                      <input type="checkbox" checked={!!r.is_active} onChange={() => toggleActive(r)} />
                    </td>
                    <td className="px-3 py-2 text-right">
                      {monthly.toLocaleString(undefined, { maximumFractionDigits: 2 })}
                    </td>
                    <td className="px-3 py-2">
                      <div className="flex justify-end gap-2">
                        <button className={BTN_SMALL} onClick={() => openEdit(r)}>
                          Edit
                        </button>
                        <button className={BTN_SMALL} onClick={() => removeRow(r.id)}>
                          Delete
                        </button>
                      </div>
                    </td>
                  </tr>
                );
              })
            )}
          </tbody>
        </table>
      </div>

      {/* Drawer/Dialog */}
      {showForm && editing && (
        <div className="fixed inset-0 bg-black/30 z-40 flex items-end sm:items-center justify-center">
          <div className="bg-white w-full sm:max-w-3xl rounded-t-2xl sm:rounded-2xl shadow-xl p-4 sm:p-6 space-y-4">
            <div className="flex items-center justify-between">
              <h4 className="text-lg font-semibold">{editing.id ? "Edit Service" : "New Service"}</h4>
              <button className={BTN_SMALL} onClick={closeForm}>
                Close
              </button>
            </div>

            <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
              <div>
                <label className="text-xs text-gray-600">Name *</label>
                <input
                  className="w-full border rounded-md px-2 py-1"
                  value={editing.service_name}
                  onChange={(e) => setEditing((s) => s && { ...s, service_name: e.target.value })}
                />
              </div>

              <div>
                <label className="text-xs text-gray-600">Category</label>
                <input
                  className="w-full border rounded-md px-2 py-1"
                  value={editing.category ?? ""}
                  onChange={(e) => setEditing((s) => s && { ...s, category: e.target.value })}
                />
              </div>

              <div>
                <label className="text-xs text-gray-600">Vendor</label>
                <input
                  className="w-full border rounded-md px-2 py-1"
                  value={editing.vendor ?? ""}
                  onChange={(e) => setEditing((s) => s && { ...s, vendor: e.target.value })}
                />
              </div>

              <div>
                <label className="text-xs text-gray-600">Unit</label>
                <input
                  className="w-full border rounded-md px-2 py-1"
                  value={editing.unit ?? ""}
                  onChange={(e) => setEditing((s) => s && { ...s, unit: e.target.value })}
                />
              </div>

              <div>
                <label className="text-xs text-gray-600">Quantity</label>
                <input
                  inputMode="decimal"
                  className="w-full border rounded-md px-2 py-1 text-right"
                  value={String(editing.quantity ?? "")}
                  onChange={(e) => setEditing((s) => s && { ...s, quantity: e.target.value })}
                />
              </div>

              <div>
                <label className="text-xs text-gray-600">Unit Cost</label>
                <input
                  inputMode="decimal"
                  className="w-full border rounded-md px-2 py-1 text-right"
                  value={String(editing.unit_cost ?? "")}
                  onChange={(e) => setEditing((s) => s && { ...s, unit_cost: e.target.value })}
                />
              </div>

              <div>
                <label className="text-xs text-gray-600">Currency</label>
                <input
                  className="w-full border rounded-md px-2 py-1"
                  value={editing.currency}
                  onChange={(e) => setEditing((s) => s && { ...s, currency: e.target.value })}
                />
              </div>

              <div className="grid grid-cols-2 gap-2">
                <div>
                  <label className="text-xs text-gray-600">Start Year</label>
                  <input
                    inputMode="numeric"
                    className="w-full border rounded-md px-2 py-1"
                    value={String(editing.start_year)}
                    onChange={(e) => setEditing((s) => s && { ...s, start_year: e.target.value })}
                  />
                </div>
                <div>
                  <label className="text-xs text-gray-600">Start Month</label>
                  <input
                    inputMode="numeric"
                    min={1}
                    max={12}
                    className="w-full border rounded-md px-2 py-1"
                    value={String(editing.start_month)}
                    onChange={(e) => setEditing((s) => s && { ...s, start_month: e.target.value })}
                  />
                </div>
              </div>

              <div>
                <label className="text-xs text-gray-600">Duration (months, optional)</label>
                <input
                  inputMode="numeric"
                  className="w-full border rounded-md px-2 py-1"
                  value={editing.duration_months ?? ""}
                  onChange={(e) =>
                    setEditing((s) => s && ({ ...s, duration_months: e.target.value === "" ? null : e.target.value }))
                  }
                />
              </div>

              <div className="grid grid-cols-2 gap-2">
                <div>
                  <label className="text-xs text-gray-600">End Year (optional)</label>
                  <input
                    inputMode="numeric"
                    className="w-full border rounded-md px-2 py-1"
                    value={editing.end_year ?? ""}
                    onChange={(e) =>
                      setEditing((s) => s && ({ ...s, end_year: e.target.value === "" ? null : e.target.value }))
                    }
                  />
                </div>
                <div>
                  <label className="text-xs text-gray-600">End Month (optional)</label>
                  <input
                    inputMode="numeric"
                    min={1}
                    max={12}
                    className="w-full border rounded-md px-2 py-1"
                    value={editing.end_month ?? ""}
                    onChange={(e) =>
                      setEditing((s) => s && ({ ...s, end_month: e.target.value === "" ? null : e.target.value }))
                    }
                  />
                </div>
              </div>

              <div>
                <label className="text-xs text-gray-600">Payment Term</label>
                <select
                  className="w-full border rounded-md px-2 py-1"
                  value={editing.payment_term}
                  onChange={(e) =>
                    setEditing((s) => s && ({ ...s, payment_term: e.target.value as PaymentTerm }))
                  }
                >
                  {paymentTerms.map((x) => (
                    <option key={x} value={x}>
                      {x}
                    </option>
                  ))}
                </select>
              </div>

              <div>
                <label className="text-xs text-gray-600">Cash-out Policy</label>
                <select
                  className="w-full border rounded-md px-2 py-1"
                  value={editing.cash_out_month_policy}
                  onChange={(e) =>
                    setEditing((s) => s && ({ ...s, cash_out_month_policy: e.target.value as CashOutPolicy }))
                  }
                >
                  {cashPolicies.map((x) => (
                    <option key={x} value={x}>
                      {x}
                    </option>
                  ))}
                </select>
              </div>

              <div>
                <label className="text-xs text-gray-600">Escalation % (annual)</label>
                <input
                  inputMode="decimal"
                  className="w-full border rounded-md px-2 py-1"
                  value={String(editing.escalation_pct)}
                  onChange={(e) =>
                    setEditing((s) => s && ({
                      ...s,
                      escalation_pct: e.target.value,
                      escalation_freq: toNum(e.target.value, 0) > 0 ? "annual" : "none",
                    }))
                  }
                />
              </div>

              <div>
                <label className="text-xs text-gray-600">Tax rate %</label>
                <input
                  inputMode="decimal"
                  className="w-full border rounded-md px-2 py-1"
                  value={String(editing.tax_rate)}
                  onChange={(e) => setEditing((s) => s && { ...s, tax_rate: e.target.value })}
                />
              </div>

              <div className="flex items-center gap-2">
                <input
                  id="inclTax"
                  type="checkbox"
                  checked={!!editing.expense_includes_tax}
                  onChange={(e) => setEditing((s) => s && { ...s, expense_includes_tax: e.target.checked })}
                />
                <label htmlFor="inclTax" className="text-sm">
                  Expense includes tax
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
            </div>

            <div className="flex justify-end gap-2">
              <button className={BTN_BASE} onClick={closeForm}>
                Cancel
              </button>
              <button className={BTN_PRIMARY} onClick={saveForm}>
                Save
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
