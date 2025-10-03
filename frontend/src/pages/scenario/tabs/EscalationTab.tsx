// frontend/src/pages/scenario/tabs/EscalationTab.tsx
import React, { useEffect, useMemo, useState } from "react";
import { apiGet, apiPost, apiPut, apiDelete } from "../../../lib/api";

type Props = { scenarioId: number };

/* ---------- Types (aktif swagger’a göre) ---------- */
type Scope = "services" | "capex" | "all";
type Frequency = "monthly" | "quarterly" | "annual";
type Compounding = "simple" | "compound";
type MethodView = "fixed" | "index" | "—";

type EscalationPolicy = {
  id: number;
  name: string;
  scope?: Scope | null;
  rate_pct?: number | null;
  index_series_id?: number | null;
  start_year: number;
  start_month: number;
  cap_pct?: number | null;
  floor_pct?: number | null;
  frequency?: Frequency | null;
  compounding?: Compounding | null;
};

type IndexSeries = {
  id: number;
  code?: string | null;
  name?: string | null;
};

/* Resolve yanıtı */
type ResolveResp = {
  year: number;
  month: number;
  items: Array<{
    name: string;
    scope: Scope;
    method: "fixed" | "index";
    effective_pct: number;
    source?: string | null;
    matched_policy_id?: number | null;
    factor?: number | null;
    details?: string | null;
  }>;
};

/* ---------- Helpers ---------- */
function cls(...a: (string | false | undefined)[]) {
  return a.filter(Boolean).join(" ");
}
const fmt2 = new Intl.NumberFormat("en-US", { minimumFractionDigits: 2, maximumFractionDigits: 2 });

/* ========== Component ========== */
export default function EscalationTab({ scenarioId }: Props) {
  const [policies, setPolicies] = useState<EscalationPolicy[]>([]);
  const [loading, setLoading] = useState(false);
  const [err, setErr] = useState<string | null>(null);

  // Index series listesi
  const [series, setSeries] = useState<IndexSeries[]>([]);
  const [seriesLoading, setSeriesLoading] = useState(false);
  const [seriesErr, setSeriesErr] = useState<string | null>(null);

  // resolve panel state
  const now = useMemo(() => {
    const d = new Date();
    return { y: d.getFullYear(), m: d.getMonth() + 1 };
  }, []);
  const [year, setYear] = useState<number>(now.y);
  const [month, setMonth] = useState<number>(now.m);
  const [resolving, setResolving] = useState(false);
  const [resolved, setResolved] = useState<ResolveResp | null>(null);

  // CRUD modal state
  type Mode = "create" | "edit";
  const [modalOpen, setModalOpen] = useState(false);
  const [mode, setMode] = useState<Mode>("create");
  const [saving, setSaving] = useState(false);
  const [formErr, setFormErr] = useState<string | null>(null);
  const [editId, setEditId] = useState<number | null>(null);

  type Form = {
    name: string;
    scope: Scope;
    method: "fixed" | "index";
    rate_pct: string;
    index_series_id: string;
    start_year: string;
    start_month: string;
    frequency: Frequency;
    compounding: Compounding;
  };
  const emptyForm: Form = {
    name: "",
    scope: "all",
    method: "fixed",
    rate_pct: "",
    index_series_id: "",
    start_year: String(now.y),
    start_month: String(now.m),
    frequency: "annual",
    compounding: "compound",
  };
  const [form, setForm] = useState<Form>(emptyForm);

  // 🔴 GLOBAL policy CRUD
  const baseUrl = `/api/escalations/policies`;
  // ✅ Resolve endpoint
  const resolveUrl = `/scenarios/${scenarioId}/escalation/resolve`;

  async function reload() {
    setLoading(true);
    setErr(null);
    setResolved(null);
    try {
      const data = await apiGet<any>(baseUrl);
      const items: EscalationPolicy[] = Array.isArray(data) ? data : data.items ?? [];
      setPolicies(items);
    } catch (e: any) {
      setPolicies([]);
      setErr(e?.message || "Failed to load escalation policies.");
    } finally {
      setLoading(false);
    }
  }

  async function loadSeries() {
    setSeriesLoading(true);
    setSeriesErr(null);
    try {
      const data = await apiGet<any>("/api/index-series");
      const items: IndexSeries[] = Array.isArray(data) ? data : data.items ?? [];
      setSeries(items);
    } catch (e: any) {
      setSeries([]);
      setSeriesErr(e?.message || "Failed to load index series.");
    } finally {
      setSeriesLoading(false);
    }
  }

  useEffect(() => {
    reload();
    loadSeries();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [scenarioId]);

  async function resolvePolicies() {
    setResolving(true);
    setErr(null);
    setResolved(null);
    try {
      const q = new URLSearchParams({ year: String(year), month: String(month) }).toString();
      const data = await apiGet<ResolveResp>(`${resolveUrl}?${q}`);
      setResolved(data);
    } catch (e: any) {
      setErr(e?.message || "Resolve failed.");
    } finally {
      setResolving(false);
    }
  }

  /* ---------- CRUD handlers ---------- */
  function openCreate() {
    setMode("create");
    setFormErr(null);
    setForm(emptyForm);
    setEditId(null);
    setModalOpen(true);
  }

  function openEdit(p: EscalationPolicy) {
    setMode("edit");
    setEditId(p.id);
    setFormErr(null);
    const method: "fixed" | "index" = p.rate_pct != null ? "fixed" : "index";
    setForm({
      name: p.name,
      scope: (p.scope ?? "all") as Scope,
      method,
      rate_pct: p.rate_pct != null ? String(p.rate_pct) : "",
      index_series_id: p.index_series_id != null ? String(p.index_series_id) : "",
      start_year: String(p.start_year),
      start_month: String(p.start_month),
      frequency: (p.frequency ?? "annual") as Frequency,
      compounding: (p.compounding ?? "compound") as Compounding,
    });
    setModalOpen(true);
  }

  async function saveForm() {
    setSaving(true);
    setFormErr(null);
    try {
      if (!form.name.trim()) throw new Error("Name is required.");
      const sy = Number(form.start_year);
      const sm = Number(form.start_month);
      if (!Number.isFinite(sy)) throw new Error("Start year is invalid.");
      if (!Number.isFinite(sm) || sm < 1 || sm > 12) throw new Error("Start month must be 1..12.");

      const payload: any = {
        name: form.name.trim(),
        scope: form.scope,
        start_year: sy,
        start_month: sm,
        frequency: form.frequency,
        compounding: form.compounding,
      };

      if (form.method === "fixed") {
        const rp = Number(form.rate_pct);
        if (!Number.isFinite(rp)) throw new Error("Fixed % is required for fixed method.");
        payload.rate_pct = rp;
        payload.index_series_id = null;
      } else {
        // index method
        if (!form.index_series_id) throw new Error("Please select an Index Series.");
        const ix = Number(form.index_series_id);
        if (!Number.isFinite(ix) || ix <= 0) throw new Error("Index series id is invalid.");
        payload.index_series_id = ix;
        payload.rate_pct = null;
      }

      if (mode === "create") {
        await apiPost<{ id: number }>(baseUrl, payload);
      } else {
        await apiPut(`${baseUrl}/${editId}`, payload);
      }
      setModalOpen(false);
      await reload();
    } catch (e: any) {
      // 422 gelirse net göster
      const msg = e?.message || "Save failed.";
      setFormErr(msg);
    } finally {
      setSaving(false);
    }
  }

  async function deletePolicy(p: EscalationPolicy) {
    const ok = window.confirm(`Delete '${p.name}' policy?`);
    if (!ok) return;
    try {
      await apiDelete(`${baseUrl}/${p.id}`);
      await reload();
    } catch (e: any) {
      alert(e?.message || "Delete failed.");
    }
  }

  return (
    <div className="space-y-4">
      {/* Header */}
      <div className="flex items-center justify-between">
        <h3 className="text-xl font-semibold">Escalation (Preview)</h3>
        <div className="flex gap-2">
          <button onClick={openCreate} className="px-3 py-1.5 rounded-md border text-sm hover:bg-gray-50">
            Add Policy
          </button>
          <button
            onClick={reload}
            className={cls(
              "px-3 py-1.5 rounded-md border text-sm hover:bg-gray-50 disabled:opacity-60",
              loading && "cursor-progress"
            )}
            disabled={loading}
          >
            Refresh
          </button>
        </div>
      </div>

      {err && <div className="p-3 rounded-md border border-red-300 bg-red-50 text-red-700">{err}</div>}

      {/* Policies table */}
      <div className="overflow-auto border rounded-xl bg-white">
        <table className="min-w-full text-sm">
          <thead className="bg-gray-50 text-gray-700">
            <tr>
              <th className="p-2 text-left">Name</th>
              <th className="p-2 text-left">Scope</th>
              <th className="p-2 text-left">Method</th>
              <th className="p-2 text-right">Fixed %</th>
              <th className="p-2 text-left">Index Series</th>
              <th className="p-2 text-left">Base (Y/M)</th>
              <th className="p-2 text-left">Freq</th>
              <th className="p-2 text-left">Comp.</th>
              <th className="p-2 text-right">Actions</th>
            </tr>
          </thead>
          <tbody>
            {loading ? (
              <tr>
                <td className="p-3" colSpan={9}>Loading…</td>
              </tr>
            ) : policies.length === 0 ? (
              <tr>
                <td className="p-4 text-gray-500" colSpan={9}>No escalation policies yet.</td>
              </tr>
            ) : (
              policies.map((p) => {
                const method: MethodView =
                  p.rate_pct != null ? "fixed" : p.index_series_id != null ? "index" : "—";
                return (
                  <tr key={p.id} className="border-t">
                    <td className="p-2">{p.name}</td>
                    <td className="p-2">{p.scope ?? "all"}</td>
                    <td className="p-2">{method}</td>
                    <td className="p-2 text-right">
                      {p.rate_pct != null ? fmt2.format(Number(p.rate_pct)) : "—"}
                    </td>
                    <td className="p-2">{p.index_series_id != null ? `#${p.index_series_id}` : "—"}</td>
                    <td className="p-2">
                      {p.start_year && p.start_month
                        ? `${p.start_year}/${String(p.start_month).padStart(2, "0")}`
                        : "—"}
                    </td>
                    <td className="p-2">{p.frequency ?? "annual"}</td>
                    <td className="p-2">{p.compounding ?? "compound"}</td>
                    <td className="p-2 text-right">
                      <button className="px-2 py-1 rounded border mr-2 hover:bg-gray-50" onClick={() => openEdit(p)}>
                        Edit
                      </button>
                      <button
                        className="px-2 py-1 rounded border hover:bg-red-50 text-red-600 border-red-200"
                        onClick={() => deletePolicy(p)}
                      >
                        Delete
                      </button>
                    </td>
                  </tr>
                );
              })
            )}
          </tbody>
        </table>
      </div>

      {/* Resolve panel */}
      <div className="border rounded-xl p-3 sm:p-4 bg-white">
        <div className="grid grid-cols-1 md:grid-cols-4 gap-3 items-end">
          <div>
            <div className="text-xs text-gray-600">Year</div>
            <input
              type="number"
              className="border rounded-md px-2 py-1 w-full"
              value={year}
              onChange={(e) => setYear(Number(e.target.value))}
            />
          </div>
        </div>
        <div className="grid grid-cols-1 md:grid-cols-4 gap-3 items-end mt-3">
          <div>
            <div className="text-xs text-gray-600">Month</div>
            <input
              type="number"
              min={1}
              max={12}
              className="border rounded-md px-2 py-1 w-full"
              value={month}
              onChange={(e) => setMonth(Number(e.target.value))}
            />
          </div>
          <div className="flex">
            <button
              className={cls(
                "ml-auto px-3 py-2 rounded-md border hover:bg-gray-50",
                resolving && "opacity-60 cursor-progress"
              )}
              onClick={resolvePolicies}
              disabled={resolving}
            >
              Resolve Escalation
            </button>
          </div>
        </div>

        {resolved && (
          <div className="mt-4 overflow-auto">
            <table className="min-w-full text-sm">
              <thead className="bg-gray-50 text-gray-700">
                <tr>
                  <th className="p-2 text-left">Policy</th>
                  <th className="p-2 text-left">Scope</th>
                  <th className="p-2 text-left">Method</th>
                  <th className="p-2 text-right">Factor</th>
                  <th className="p-2 text-right">Effective %</th>
                  <th className="p-2 text-left">Details</th>
                </tr>
              </thead>
              <tbody>
                {resolved.items?.length ? (
                  resolved.items.map((it, idx) => (
                    <tr key={idx} className="border-t">
                      <td className="p-2">{it.name}</td>
                      <td className="p-2">{it.scope}</td>
                      <td className="p-2">{it.method}</td>
                      <td className="p-2 text-right">
                        {it.factor == null ? "—" : fmt2.format(it.factor)}
                      </td>
                      <td className="p-2 text-right">{fmt2.format(it.effective_pct)} %</td>
                      <td className="p-2">{it.source || it.details || "—"}</td>
                    </tr>
                  ))
                ) : (
                  <tr>
                    <td className="p-3 text-gray-500" colSpan={6}>
                      No matching policy for selected date.
                    </td>
                  </tr>
                )}
              </tbody>
            </table>
            <div className="mt-2 text-xs text-gray-500">
              Preview amaçlıdır; sonuçlar politika tanımlarına göre hesaplanır.
            </div>
          </div>
        )}
      </div>

      <div className="text-xs text-gray-500">
        Bu sekme yalnızca önizleme/çözümleme amaçlıdır. Servisler/CAPEX üzerinde otomatik değişiklik yapmaz.
      </div>

      {/* ---------- Minimal Modal ---------- */}
      {modalOpen && (
        <div className="fixed inset-0 z-40">
          <div className="absolute inset-0 bg-black/30" onClick={() => !saving && setModalOpen(false)} />
          <div className="absolute inset-0 grid place-items-center p-4">
            <div className="w-full max-w-xl bg-white rounded-xl border shadow-md p-4 sm:p-5 z-10">
              <div className="flex items-center justify-between">
                <h4 className="text-lg font-semibold">
                  {mode === "create" ? "Add Escalation Policy" : "Edit Escalation Policy"}
                </h4>
                <button className="px-2 py-1 rounded border hover:bg-gray-50" onClick={() => !saving && setModalOpen(false)}>
                  Close
                </button>
              </div>

              {formErr && (
                <div className="mt-3 p-2 rounded border border-red-300 bg-red-50 text-red-700 text-sm">{formErr}</div>
              )}
              {seriesErr && (
                <div className="mt-3 p-2 rounded border border-yellow-300 bg-yellow-50 text-yellow-700 text-sm">{seriesErr}</div>
              )}

              <div className="mt-3 grid grid-cols-1 sm:grid-cols-2 gap-3">
                <div>
                  <div className="text-xs text-gray-600">Name</div>
                  <input
                    className="border rounded-md px-2 py-1 w-full"
                    value={form.name}
                    onChange={(e) => setForm({ ...form, name: e.target.value })}
                  />
                </div>

                <div>
                  <div className="text-xs text-gray-600">Scope</div>
                  <select
                    className="border rounded-md px-2 py-1 w-full"
                    value={form.scope}
                    onChange={(e) => setForm({ ...form, scope: e.target.value as Scope })}
                  >
                    <option value="all">all</option>
                    <option value="services">services</option>
                    <option value="capex">capex</option>
                  </select>
                </div>

                <div>
                  <div className="text-xs text-gray-600">Method</div>
                  <select
                    className="border rounded-md px-2 py-1 w-full"
                    value={form.method}
                    onChange={(e) => {
                      const v = e.target.value as "fixed" | "index";
                      // method değişince karşı alanı temizle
                      setForm({
                        ...form,
                        method: v,
                        rate_pct: v === "fixed" ? form.rate_pct : "",
                        index_series_id: v === "index" ? form.index_series_id : "",
                      });
                    }}
                  >
                    <option value="fixed">fixed</option>
                    <option value="index">index</option>
                  </select>
                </div>

                {form.method === "fixed" ? (
                  <div>
                    <div className="text-xs text-gray-600">Fixed %</div>
                    <input
                      type="number"
                      step="0.000001"
                      className="border rounded-md px-2 py-1 w-full"
                      value={form.rate_pct}
                      onChange={(e) => setForm({ ...form, rate_pct: e.target.value })}
                    />
                  </div>
                ) : (
                  <div>
                    <div className="text-xs text-gray-600">Index Series</div>
                    <select
                      className="border rounded-md px-2 py-1 w-full"
                      value={form.index_series_id}
                      onChange={(e) => setForm({ ...form, index_series_id: e.target.value })}
                      disabled={seriesLoading}
                    >
                      <option value="">— select —</option>
                      {series.map((s) => (
                        <option key={s.id} value={String(s.id)}>
                          #{s.id} {s.code ?? ""} {s.name ?? ""}
                        </option>
                      ))}
                    </select>
                    <div className="text-[11px] text-gray-500 mt-1">
                      (Listede yoksa önce <b>Index Series</b> bölümünden oluşturun.)
                    </div>
                  </div>
                )}

                <div>
                  <div className="text-xs text-gray-600">Start Year</div>
                  <input
                    type="number"
                    className="border rounded-md px-2 py-1 w-full"
                    value={form.start_year}
                    onChange={(e) => setForm({ ...form, start_year: e.target.value })}
                  />
                </div>
                <div>
                  <div className="text-xs text-gray-600">Start Month</div>
                  <input
                    type="number"
                    min={1}
                    max={12}
                    className="border rounded-md px-2 py-1 w-full"
                    value={form.start_month}
                    onChange={(e) => setForm({ ...form, start_month: e.target.value })}
                  />
                </div>

                <div>
                  <div className="text-xs text-gray-600">Frequency</div>
                  <select
                    className="border rounded-md px-2 py-1 w-full"
                    value={form.frequency}
                    onChange={(e) => setForm({ ...form, frequency: e.target.value as Frequency })}
                  >
                    <option value="annual">annual</option>
                    <option value="quarterly">quarterly</option>
                    <option value="monthly">monthly</option>
                  </select>
                </div>

                <div>
                  <div className="text-xs text-gray-600">Compounding</div>
                  <select
                    className="border rounded-md px-2 py-1 w-full"
                    value={form.compounding}
                    onChange={(e) => setForm({ ...form, compounding: e.target.value as Compounding })}
                  >
                    <option value="compound">compound</option>
                    <option value="simple">simple</option>
                  </select>
                </div>
              </div>

              <div className="mt-4 flex justify-end gap-2">
                <button className="px-3 py-1.5 rounded-md border hover:bg-gray-50" onClick={() => !saving && setModalOpen(false)} disabled={saving}>
                  Cancel
                </button>
                <button
                  className={cls(
                    "px-3 py-1.5 rounded-md border bg-indigo-600 text-white hover:bg-indigo-700",
                    saving && "opacity-70 cursor-progress"
                  )}
                  onClick={saveForm}
                  disabled={saving}
                >
                  {mode === "create" ? "Create" : "Save"}
                </button>
              </div>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
