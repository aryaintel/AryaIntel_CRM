import React, { useEffect, useMemo, useState } from "react";

/**
 * BOQ Console
 * One-file React UI to exercise the new BOQ + Pricing endpoints shipped in v1.1.1.
 *
 * Drop-in usage (Vite + TS):
 *   - Save as src/pages/BoqConsole.tsx
 *   - Add a route <BoqConsole /> somewhere in your app
 *   - Ensure Tailwind is available (styles are minimal; plain classes also ok)
 *
 * What it covers
 *  1) List Scenarios  -> GET /api/boq/scenarios
 *  2) List BOQ for scenario -> GET /scenarios/:id/boq  (or legacy /business-cases/scenarios/:id/boq)
 *  3) Create/Update/Delete BOQ items -> POST/PUT/DELETE /scenarios/:id/boq...
 *  4) Mark Ready -> POST /scenarios/:id/boq/mark-ready
 *  5) Price preview (per BOQ row) -> GET /api/boq/:boqId/price-preview?ym=YYYY-MM
 *  6) Debug DB (compare orm vs pricing) -> GET /boq/_debug/db and GET /api/boq/_debug/db
 */

// -----------------------------
// tiny fetch client
// -----------------------------
const apiBase = import.meta.env.VITE_API_BASE || ""; // e.g. "http://127.0.0.1:8000"

async function http<T>(path: string, opts: RequestInit = {}, token?: string): Promise<T> {
  const headers: Record<string, string> = {
    "Content-Type": "application/json",
  };
  if (token) headers["Authorization"] = `Bearer ${token}`;
  const res = await fetch(`${apiBase}${path}`, { ...opts, headers: { ...headers, ...(opts.headers || {}) } });
  if (!res.ok) {
    const txt = await res.text();
    throw new Error(`${res.status} ${res.statusText}: ${txt}`);
  }
  const ct = res.headers.get("content-type") || "";
  return ct.includes("application/json") ? (await res.json()) as T : ((await res.text()) as unknown as T);
}

// -----------------------------
// types
// -----------------------------
interface ScenarioLite {
  id: number;
  name: string;
  months: number;
  start_date: string;
  is_boq_ready: boolean;
  workflow_state?: string;
}

interface BoqItem {
  id: number;
  scenario_id: number;
  section?: string | null;
  category?: string | null;
  item_name: string;
  unit?: string | null;
  quantity: string | number; // keep as string from API but allow editing
  unit_price: string | number;
  unit_cogs?: string | number | null;
  frequency: string;
  months?: number | null;
  start_year?: number | null;
  start_month?: number | null;
  formulation_id?: number | null;
  product_id?: number | null;
  is_active: boolean;
  notes?: string | null;
}

interface PricePreview {
  id: number;
  scenario_id: number;
  name: string;
  period: string; // YYYY-MM
  currency: string;
  unit_price: string;
  quantity: string;
  line_total: string;
  source: string; // "formulation" | "product_price_book" | "boq_unit_price"
}

// -----------------------------
// helper UI bits
// -----------------------------
function Label({ children }: { children: React.ReactNode }) { return <div className="text-xs uppercase text-slate-500">{children}</div>; }
function Section({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <div className="bg-white rounded-2xl shadow p-4 mb-4">
      <div className="text-lg font-semibold mb-3">{title}</div>
      {children}
    </div>
  );
}

function TextInput(props: React.InputHTMLAttributes<HTMLInputElement>) {
  return <input {...props} className={"border rounded px-2 py-1 w-full " + (props.className || "")} />;
}

function NumberCell({ v }: { v: any }) {
  const s = v === null || v === undefined || v === "" ? "-" : String(v);
  return <span className="tabular-nums">{s}</span>;
}

// -----------------------------
// editor row component
// -----------------------------
function BoqRowEditor({ row, onSave, onCancel }: { row: Partial<BoqItem>; onSave: (p: Partial<BoqItem>) => void; onCancel: () => void }) {
  const [draft, setDraft] = useState<Partial<BoqItem>>({ ...row });
  return (
    <div className="grid grid-cols-12 gap-2">
      <div className="col-span-2"><TextInput placeholder="Section" value={draft.section ?? ""} onChange={e => setDraft({ ...draft, section: e.target.value })} /></div>
      <div className="col-span-3"><TextInput placeholder="Item name" value={draft.item_name ?? ""} onChange={e => setDraft({ ...draft, item_name: e.target.value })} /></div>
      <div className="col-span-1"><TextInput placeholder="Unit" value={draft.unit ?? ""} onChange={e => setDraft({ ...draft, unit: e.target.value })} /></div>
      <div className="col-span-1"><TextInput placeholder="Qty" value={draft.quantity as any ?? ""} onChange={e => setDraft({ ...draft, quantity: e.target.value })} /></div>
      <div className="col-span-1"><TextInput placeholder="Unit Price" value={draft.unit_price as any ?? ""} onChange={e => setDraft({ ...draft, unit_price: e.target.value })} /></div>
      <div className="col-span-1"><TextInput placeholder="Freq" value={draft.frequency ?? "once"} onChange={e => setDraft({ ...draft, frequency: e.target.value })} /></div>
      <div className="col-span-1"><TextInput placeholder="Start Y" value={draft.start_year ?? ""} onChange={e => setDraft({ ...draft, start_year: Number(e.target.value) || undefined })} /></div>
      <div className="col-span-1"><TextInput placeholder="Start M" value={draft.start_month ?? ""} onChange={e => setDraft({ ...draft, start_month: Number(e.target.value) || undefined })} /></div>
      <div className="col-span-12 flex gap-2 justify-end mt-2">
        <button className="px-3 py-1 rounded bg-slate-200" onClick={onCancel}>Cancel</button>
        <button className="px-3 py-1 rounded bg-emerald-600 text-white" onClick={() => onSave(draft)}>Save</button>
      </div>
    </div>
  );
}

// -----------------------------
// main component
// -----------------------------
export default function BoqConsole() {
  const [token, setToken] = useState<string>(localStorage.getItem("authToken") || "");
  const [scenarios, setScenarios] = useState<ScenarioLite[]>([]);
  const [scenarioId, setScenarioId] = useState<number | null>(null);
  const [items, setItems] = useState<BoqItem[]>([]);
  const [editing, setEditing] = useState<BoqItem | null>(null);
  const [creating, setCreating] = useState<boolean>(false);
  const [ym, setYm] = useState<string>(new Date().toISOString().slice(0,7));
  const [pricePreview, setPricePreview] = useState<PricePreview | null>(null);
  const [dbgOrm, setDbgOrm] = useState<any | null>(null);
  const [dbgPricing, setDbgPricing] = useState<any | null>(null);

  useEffect(() => { localStorage.setItem("authToken", token); }, [token]);

  // load scenarios once
  useEffect(() => {
    (async () => {
      try {
        const rows = await http<ScenarioLite[]>(`/api/boq/scenarios`, {}, token);
        setScenarios(rows);
        if (!scenarioId && rows.length) setScenarioId(rows[0].id);
      } catch (e:any) { console.error(e); }
    })();
  }, [token]);

  // load items when scenario changes
  useEffect(() => {
    if (!scenarioId) return;
    (async () => {
      try {
        const rows = await http<BoqItem[]>(`/scenarios/${scenarioId}/boq`, {}, token);
        setItems(rows);
      } catch (e:any) { console.error(e); }
    })();
  }, [scenarioId, token]);

  const selectedScenario = useMemo(() => scenarios.find(s => s.id === scenarioId) || null, [scenarios, scenarioId]);

  async function refresh() {
    if (!scenarioId) return;
    const rows = await http<BoqItem[]>(`/scenarios/${scenarioId}/boq`, {}, token);
    setItems(rows);
  }

  // CRUD actions
  async function saveNew(draft: Partial<BoqItem>) {
    if (!scenarioId) return;
    await http(`/scenarios/${scenarioId}/boq`, { method: "POST", body: JSON.stringify(draft) }, token);
    setCreating(false);
    await refresh();
  }

  async function saveEdit(draft: Partial<BoqItem>) {
    if (!scenarioId || !editing) return;
    await http(`/scenarios/${scenarioId}/boq/${editing.id}`, { method: "PUT", body: JSON.stringify(draft) }, token);
    setEditing(null);
    await refresh();
  }

  async function doDelete(row: BoqItem) {
    if (!scenarioId) return;
    await http(`/scenarios/${scenarioId}/boq/${row.id}`, { method: "DELETE" }, token);
    await refresh();
  }

  async function doMarkReady() {
    if (!scenarioId) return;
    const res = await http(`/scenarios/${scenarioId}/boq/mark-ready`, { method: "POST" }, token);
    console.log(res);
    // refresh scenario flags
    const rows = await http<ScenarioLite[]>(`/api/boq/scenarios`, {}, token);
    setScenarios(rows);
  }

  async function previewPrice(row: BoqItem) {
    try {
      const p = await http<PricePreview>(`/api/boq/${row.id}/price-preview?ym=${encodeURIComponent(ym)}`, {}, token);
      setPricePreview(p);
    } catch (e:any) {
      setPricePreview(null);
      alert(e.message);
    }
  }

  async function loadDebug() {
    try { setDbgOrm(await http(`/boq/_debug/db`, {}, token)); } catch { setDbgOrm(null); }
    try { setDbgPricing(await http(`/api/boq/_debug/db`, {}, token)); } catch { setDbgPricing(null); }
  }

  return (
    <div className="p-4 max-w-screen-2xl mx-auto space-y-4">
      <div className="flex items-center gap-3">
        <Label>API Base</Label>
        <div className="px-2 py-1 bg-slate-100 rounded">{apiBase || "/"}</div>
        <Label>Token</Label>
        <input className="border rounded px-2 py-1 w-[28rem]" placeholder="paste Bearer token" value={token} onChange={e => setToken(e.target.value)} />
        <button className="ml-auto px-3 py-1 rounded bg-indigo-600 text-white" onClick={loadDebug}>Load Debug</button>
      </div>

      <Section title="Scenarios">
        <div className="flex items-center gap-3">
          <select className="border rounded px-2 py-1" value={scenarioId ?? ''} onChange={e => setScenarioId(Number(e.target.value))}>
            {scenarios.map(s => (
              <option key={s.id} value={s.id}>{s.id} – {s.name}</option>
            ))}
          </select>
          {selectedScenario && (
            <div className="text-sm text-slate-600">months: {selectedScenario.months} • start: {selectedScenario.start_date} • workflow: {selectedScenario.workflow_state || (selectedScenario.is_boq_ready ? "boq-ready" : "draft")}</div>
          )}
          <button className="ml-auto px-3 py-1 rounded bg-emerald-600 text-white" onClick={doMarkReady}>Mark BOQ Ready</button>
        </div>
      </Section>

      <Section title="BOQ Items">
        <div className="flex items-center gap-3 mb-3">
          <button className="px-3 py-1 rounded bg-slate-200" onClick={() => setCreating(v => !v)}>{creating ? "Close" : "New Item"}</button>
          <div className="ml-auto flex items-center gap-2">
            <Label>Price period</Label>
            <input type="month" className="border rounded px-2 py-1" value={ym} onChange={e => setYm(e.target.value)} />
          </div>
        </div>

        {creating && (
          <div className="mb-4 border rounded-2xl p-3">
            <BoqRowEditor row={{ item_name: "", frequency: "once", unit_price: 0, quantity: 0, is_active: true }} onSave={saveNew} onCancel={() => setCreating(false)} />
          </div>
        )}

        <div className="overflow-x-auto">
          <table className="min-w-full text-sm">
            <thead>
              <tr className="text-left border-b">
                <th className="py-2 pr-2">ID</th>
                <th className="py-2 pr-2">Section</th>
                <th className="py-2 pr-2">Item</th>
                <th className="py-2 pr-2">Unit</th>
                <th className="py-2 pr-2">Qty</th>
                <th className="py-2 pr-2">Unit Price</th>
                <th className="py-2 pr-2">Freq</th>
                <th className="py-2 pr-2">Start</th>
                <th className="py-2 pr-2">Cat</th>
                <th className="py-2 pr-2">Actions</th>
              </tr>
            </thead>
            <tbody>
              {items.map((r) => (
                <tr key={r.id} className="border-b hover:bg-slate-50">
                  <td className="py-2 pr-2">{r.id}</td>
                  <td className="py-2 pr-2">{r.section}</td>
                  <td className="py-2 pr-2">{r.item_name}</td>
                  <td className="py-2 pr-2">{r.unit}</td>
                  <td className="py-2 pr-2"><NumberCell v={r.quantity} /></td>
                  <td className="py-2 pr-2"><NumberCell v={r.unit_price} /></td>
                  <td className="py-2 pr-2">{r.frequency}</td>
                  <td className="py-2 pr-2">{r.start_year ? `${r.start_year}-${String(r.start_month||"01").toString().padStart(2,"0")}` : "-"}</td>
                  <td className="py-2 pr-2">{r.category || "-"}</td>
                  <td className="py-2 pr-2">
                    <div className="flex gap-2">
                      <button className="px-2 py-0.5 rounded bg-slate-200" onClick={() => { setEditing(r); setPricePreview(null); }}>Edit</button>
                      <button className="px-2 py-0.5 rounded bg-rose-600 text-white" onClick={() => doDelete(r)}>Delete</button>
                      <button className="px-2 py-0.5 rounded bg-indigo-600 text-white" onClick={() => previewPrice(r)}>Price {ym}</button>
                    </div>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>

        {editing && (
          <div className="mt-4 border rounded-2xl p-3">
            <div className="font-semibold mb-2">Edit #{editing.id}</div>
            <BoqRowEditor row={editing} onSave={saveEdit} onCancel={() => setEditing(null)} />
          </div>
        )}

        {pricePreview && (
          <div className="mt-4 p-3 rounded-2xl bg-slate-50 border">
            <div className="font-semibold mb-1">Price preview • {pricePreview.name}</div>
            <div className="text-sm">period {pricePreview.period} • {pricePreview.currency} {pricePreview.unit_price} × {pricePreview.quantity} = <b>{pricePreview.line_total}</b> • source: {pricePreview.source}</div>
          </div>
        )}
      </Section>

      <Section title="Debug – DB wiring (ORM vs Pricing)">
        <div className="grid md:grid-cols-2 gap-4">
          <pre className="bg-slate-900 text-slate-100 text-xs p-3 rounded-xl overflow-auto min-h-[160px]">
{JSON.stringify(dbgOrm, null, 2)}
          </pre>
          <pre className="bg-slate-900 text-slate-100 text-xs p-3 rounded-xl overflow-auto min-h-[160px]">
{JSON.stringify(dbgPricing, null, 2)}
          </pre>
        </div>
        <div className="text-xs text-slate-500 mt-2">Left: GET /boq/_debug/db • Right: GET /api/boq/_debug/db</div>
      </Section>

      <div className="text-xs text-slate-500">Tip: set VITE_API_BASE in .env (e.g. http://127.0.0.1:8000). This console expects the schema where BOQ rows live in <code>scenario_boq_items</code> with optional <code>product_id</code>/<code>formulation_id</code> for pricing integration.</div>
    </div>
  );
}
