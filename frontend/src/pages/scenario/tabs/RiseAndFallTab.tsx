// Rise & Fall tab — Hardened v1.0.10 compatible (FIXED HOOK ORDER)
// Single-file: selector (Service/BOQ) + formulation editor + preview (single chart) + Product Picker
// ErrorBoundary + ChartSafe + defensive API handling

import React, { useEffect, useMemo, useState } from "react";
import { apiGet, apiPost } from "../../../lib/api";
import {
  ResponsiveContainer,
  LineChart,
  Line,
  XAxis,
  YAxis,
  Tooltip,
  Legend,
  CartesianGrid,
} from "recharts";

/* ===================== Utilities ===================== */

function cls(...a: Array<string | false | undefined>) {
  return a.filter(Boolean).join(" ");
}
function pad2(n: number) { return String(n).padStart(2, "0"); }
function ymStr(y: number, m: number) { return `${y}-${pad2(m)}`; }
function fromYM(s: string): { y: number; m: number } {
  const [yy, mm] = (s || "").split("-").map((v) => Number(v));
  return { y: Number.isFinite(yy) ? yy : new Date().getFullYear(), m: Number.isFinite(mm) ? mm : 1 };
}
function addMonths(y: number, m: number, k: number): { y: number; m: number } {
  const dt = new Date(y, m - 1, 1);
  dt.setMonth(dt.getMonth() + k);
  return { y: dt.getFullYear(), m: dt.getMonth() + 1 };
}
type Frequency = "monthly" | "quarterly" | "annual";
function stepsForFrequency(freq: Frequency): number {
  return freq === "monthly" ? 1 : freq === "quarterly" ? 3 : 12;
}
const nullableNumber = (v: unknown): number | null => {
  if (v === null || v === undefined || v === "") return null;
  const n = Number(v);
  return Number.isFinite(n) ? n : null;
};
function toArraySafe(x: any): any[] {
  if (Array.isArray(x)) return x;
  if (x && Array.isArray(x.items)) return x.items;
  if (x && Array.isArray(x.data)) return x.data;
  return [];
}

/* ===================== Types ===================== */

type Props = { scenarioId: number };

type ServiceRow = {
  id: number;
  service_name?: string | null;
  unit_cost?: number | null;
  currency?: string | null;
  start_year?: number | null;
  start_month?: number | null;
  product_id?: number | null;
};

type BOQItem = {
  id: number;
  section?: string | null;
  unit_cogs?: number | null;
  start_year?: number | null;
  start_month?: number | null;
  product_id?: number | null;
};

type IndexSeries = {
  id: number;
  code: string;
  name: string;
  currency?: string | null;
};
type IndexPoint = { year: number; month: number; value: number };

type Compounding = "simple" | "compound";
type Scope = "service" | "boq";

interface FormulationComponent {
  index_series_id: number;
  weight_pct: number; // 0..100
  base_ref_ym?: string | null; // YYYY-MM
  lag_months?: number; // can be negative
  factor?: number; // multiplier
  cap_pct?: number | null;
  floor_pct?: number | null;
}

interface RiseFallForm {
  frequency: Frequency;
  compounding: Compounding;
  months: number;
  components: FormulationComponent[];
  base_price: number;
  start_ym?: string | null;
  product_id?: number | null;      // required only on save
  product_code?: string | null;
  product_name?: string | null;
}

type PreviewRow = { ym: string; price: number; idx: number };

type Product = {
  id: number;
  code: string;
  name: string;
  currency?: string | null;
  uom?: string | null;
  is_active?: boolean | null;
};

/* ===================== Error Boundary ===================== */

class ErrorBoundary extends React.Component<{ children: React.ReactNode }, { error: any }> {
  constructor(props: any) { super(props); this.state = { error: null }; }
  static getDerivedStateFromError(error: any) { return { error }; }
  render() {
    if (this.state.error) {
      return (
        <div className="border rounded-xl p-4 bg-red-50 text-red-700">
          <div className="font-semibold mb-1">Something went wrong in this section.</div>
          <div className="text-sm break-all">{String(this.state.error?.message || this.state.error)}</div>
        </div>
      );
    }
    return this.props.children as any;
  }
}

/* ===================== Sanitizers ===================== */

function sanitizeComponent(c: FormulationComponent) {
  const out: any = {
    index_series_id: Number(c.index_series_id),
    weight_pct: Number(c.weight_pct),
  };
  if (c.base_ref_ym && /^\d{4}-\d{2}$/.test(c.base_ref_ym)) out.base_ref_ym = c.base_ref_ym;
  const lag = nullableNumber(c.lag_months as any);
  if (lag !== null) out.lag_months = lag;
  const fac = nullableNumber(c.factor as any);
  if (fac !== null) out.factor = fac;
  out.cap_pct = nullableNumber(c.cap_pct as any);
  out.floor_pct = nullableNumber(c.floor_pct as any);
  return out;
}

function sanitizeFormulationPayload(raw: {
  product_id?: number | null;
  name?: string | null;
  code?: string | null;
  base_price?: number | null;
  frequency?: Frequency | null;
  compounding?: Compounding | null;
  start_ym?: string | null;
  components: FormulationComponent[];
}) {
  const payload: any = {
    name: raw.name ?? null,
    base_price: nullableNumber(raw.base_price as any),
    frequency: (raw.frequency ?? "annual") as Frequency,
    compounding: (raw.compounding ?? "simple") as Compounding,
    start_ym: raw.start_ym && /^\d{4}-\d{2}$/.test(raw.start_ym) ? raw.start_ym : null,
    components: (raw.components || []).map(sanitizeComponent),
  };
  if (raw.product_id == null) throw new Error("product_id is required.");
  payload.product_id = Number(raw.product_id);
  if (raw.code) payload.code = String(raw.code);
  return payload;
}

/* ===================== Preview engine ===================== */

function buildPreview(
  form: RiseFallForm,
  seriesPointsMap: Map<number, Map<string, number>>,
  startY: number,
  startM: number
): PreviewRow[] {
  const horizon = Math.max(1, Number(form.months || 24));
  const step = stepsForFrequency(form.frequency);
  const out: PreviewRow[] = [];
  const basePrice = Number(form.base_price || 0);
  if (!Number.isFinite(basePrice) || basePrice <= 0 || form.components.length === 0) return out;

  function compositeAt(ym: string) {
    let total = 0;
    for (const c of form.components) {
      const mp = seriesPointsMap.get(c.index_series_id);
      if (!mp) continue;
      const val = mp.get(ym);
      if (val == null) continue;
      const w = (Number(c.weight_pct) || 0) / 100.0;
      const f = Number.isFinite(Number(c.factor)) ? Number(c.factor) : 1;
      total += val * w * f;
    }
    return total;
  }

  const baseRefs = form.components.map((c) => c.base_ref_ym).filter(Boolean) as string[];
  const fallbackBase = ymStr(startY, startM);
  const baseYM = baseRefs[0] || fallbackBase;
  const baseIndex = compositeAt(baseYM) || 100;

  let currentPrice = basePrice;
  for (let k = 0; k < horizon; k += step) {
    const { y, m } = addMonths(startY, startM, k);
    const ym = ymStr(y, m);

    let compVal = 0;
    for (const c of form.components) {
      const mp = seriesPointsMap.get(c.index_series_id);
      if (!mp) continue;
      const lag = Number(c.lag_months ?? 0);
      const target = addMonths(y, m, lag);
      const tYM = ymStr(target.y, target.m);
      const val = mp.get(tYM);
      if (val == null) continue;
      const w = (Number(c.weight_pct) || 0) / 100.0;
      const f = Number.isFinite(Number(c.factor)) ? Number(c.factor) : 1;
      compVal += val * w * f;
    }

    const baseDeltaPct = baseIndex ? (compVal - baseIndex) / baseIndex : 0;

    const netCap = Math.min(...form.components.map((c) => (c.cap_pct ?? Infinity)), Infinity);
    const netFloor = Math.max(...form.components.map((c) => (c.floor_pct ?? -Infinity)), -Infinity);
    const boundedDeltaPct = Math.min(Math.max(baseDeltaPct * 100, netFloor), netCap);
    const deltaRatio = 1 + boundedDeltaPct / 100;

    const priceForPoint =
      form.compounding === "simple" ? basePrice * deltaRatio : currentPrice * deltaRatio;

    out.push({ ym, price: Number(priceForPoint.toFixed(4)), idx: Number(compVal.toFixed(4)) });
    currentPrice = priceForPoint;
  }
  return out;
}

/* ===================== Safe chart wrapper ===================== */

function ChartSafe({
  data,
  render,
}: {
  data: any[];
  render: (rows: any[]) => React.ReactNode;
}) {
  if (!Array.isArray(data) || data.length === 0) {
    return (
      <div className="h-40 flex items-center justify-center text-sm text-gray-500">
        No chart data.
      </div>
    );
  }
  try {
    return <>{render(data)}</>;
  } catch (e: any) {
    return (
      <div className="border rounded p-3 bg-red-50 text-red-700 text-sm">
        Chart error: {String(e?.message || e)}
      </div>
    );
  }
}

/* ===================== Component ===================== */

export default function RiseAndFallTab({ scenarioId }: Props) {
  // ---------- state ----------
  const [services, setServices] = useState<ServiceRow[]>([]);
  const [boqs, setBOQs] = useState<BOQItem[]>([]);
  const [series, setSeries] = useState<IndexSeries[]>([]);
  const [pointsBySeries, setPointsBySeries] = useState<Map<number, Map<string, number>>>(new Map());
  const [loading, setLoading] = useState(true);
  const [err, setErr] = useState<string | null>(null);
  const [saveMsg, setSaveMsg] = useState<{ ok?: string; err?: string } | null>(null);

  // Product picker
  const [productOpen, setProductOpen] = useState(false);
  const [productLoading, setProductLoading] = useState(false);
  const [productErr, setProductErr] = useState<string | null>(null);
  const [products, setProducts] = useState<Product[]>([]);
  const [productQ, setProductQ] = useState("");

  // selection
  const [scope, setScope] = useState<Scope>("service");
  const [selectedId, setSelectedId] = useState<number | null>(null);

  const [form, setForm] = useState<RiseFallForm>({
    frequency: "annual",
    compounding: "simple",
    months: 36,
    components: [],
    base_price: 0,
    start_ym: null,
    product_id: null,
    product_code: null,
    product_name: null,
  });

  const [showSeries, setShowSeries] = useState(false);

  // ---------- derived (ALWAYS before any return) ----------
  const startYM = useMemo(() => {
    const src =
      (scope === "service"
        ? services.find((s) => s.id === selectedId)
        : boqs.find((b) => b.id === selectedId)) || null;
    const y = src?.start_year || new Date().getFullYear();
    const m = src?.start_month || new Date().getMonth() + 1;
    return form.start_ym && /^\d{4}-\d{2}$/.test(form.start_ym) ? form.start_ym : ymStr(y, m);
  }, [scope, selectedId, services, boqs, form.start_ym]);

  const filteredProducts = useMemo(() => {
    const t = productQ.trim().toLowerCase();
    if (!t) return products;
    return products.filter(
      (p) =>
        (p.code || "").toLowerCase().includes(t) ||
        (p.name || "").toLowerCase().includes(t) ||
        (p.currency || "").toLowerCase().includes(t) ||
        (p.uom || "").toLowerCase().includes(t)
    );
  }, [products, productQ]);

  // ---------- effects ----------
  useEffect(() => {
    const s = scope === "service" ? services.find((v) => v.id === selectedId) : null;
    const b = scope === "boq" ? boqs.find((v) => v.id === selectedId) : null;

    const bp = scope === "service" ? Number(s?.unit_cost ?? 0) : Number(b?.unit_cogs ?? 0);
    const pid = scope === "service" ? (s?.product_id ?? null) : (b?.product_id ?? null);

    setForm((f) => ({
      ...f,
      base_price: Number.isFinite(bp) ? bp : 0,
      product_id: pid ?? f.product_id ?? null,
    }));
  }, [scope, selectedId, services, boqs]);

  useEffect(() => {
    const sid = Number(scenarioId);
    if (!sid || Number.isNaN(sid)) {
      setLoading(false);
      setErr("Invalid scenario id.");
      return;
    }
    let alive = true;
    (async () => {
      setLoading(true);
      setErr(null);
      try {
        const [svc, bq, ser] = await Promise.all([
          (async () => {
            try { return await apiGet<any>(`/scenarios/${sid}/services`); } catch {}
            try { return await apiGet<any>(`/business-cases/scenarios/${sid}/services`); } catch {}
            try { return await apiGet<any>(`/business-cases/scenarios/${sid}/service-items`); } catch {}
            return [];
          })(),
          (async () => {
            try { return await apiGet<any>(`/scenarios/${sid}/boq-items`); } catch {}
            try { return await apiGet<any>(`/scenarios/${sid}/boq`); } catch {}
            try { return await apiGet<any>(`/business-cases/scenarios/${sid}/boq-items`); } catch {}
            try { return await apiGet<any>(`/business-cases/scenarios/${sid}/boq`); } catch {}
            return [];
          })(),
          (async () => {
            try { return await apiGet<any>(`/api/index-series`); } catch { return []; }
          })(),
        ]);
        if (!alive) return;
        setServices(toArraySafe(svc));
        setBOQs(toArraySafe(bq));
        setSeries(toArraySafe(ser));
      } catch (e: any) {
        if (!alive) return;
        setErr(e?.message || "Failed to load data.");
      } finally {
        if (alive) setLoading(false);
      }
    })();
    return () => { alive = false; };
  }, [scenarioId]);

  useEffect(() => {
    const needed = new Set(form.components.map((c) => c.index_series_id).filter(Boolean));
    const missing = Array.from(needed).filter((sid) => !pointsBySeries.has(sid));
    if (missing.length === 0) return;
    let alive = true;
    (async () => {
      try {
        const next = new Map(pointsBySeries);
        for (const sid of missing) {
          const res = await apiGet<any>(`/api/index-series/${sid}/points?limit=10000&offset=0`);
          const items: IndexPoint[] = toArraySafe(res);
          const mp = new Map<string, number>();
          for (const p of items) {
            if (p && Number.isFinite(Number(p.year)) && Number.isFinite(Number(p.month))) {
              mp.set(`${p.year}-${pad2(Number(p.month))}`, Number(p.value ?? 0));
            }
          }
          next.set(sid, mp);
        }
        if (alive) setPointsBySeries(next);
      } catch {}
    })();
    return () => { alive = false; };
  }, [form.components, pointsBySeries]);

  useEffect(() => {
    if (form.product_id == null) return;
    let alive = true;
    (async () => {
      try {
        const res: any = await apiGet(`/api/products/${form.product_id}`);
        const p: Product = res?.data ?? res;
        if (alive && p?.id) {
          setForm((f) => ({ ...f, product_code: p.code || null, product_name: p.name || null }));
        }
      } catch {}
    })();
    return () => { alive = false; };
  }, [form.product_id]);

  // ---------- computed ----------
  const chartData: PreviewRow[] = useMemo(() => {
    try {
      const { y, m } = fromYM(startYM);
      return buildPreview(form, pointsBySeries, y, m);
    } catch {
      return [];
    }
  }, [form, pointsBySeries, startYM]);

  const overlayByYM = useMemo(() => {
    if (!showSeries || form.components.length === 0) return new Map<string, Record<string, number | null>>();
    const { y, m } = fromYM(startYM);
    const horizon = Math.max(1, Number(form.months || 24));
    const map = new Map<string, Record<string, number | null>>();
    for (let k = 0; k < horizon; k++) {
      const { y: yy, m: mm } = addMonths(y, m, k);
      const ym = ymStr(yy, mm);
      const row: Record<string, number | null> = {};
      for (const c of form.components) {
        const mp = pointsBySeries.get(c.index_series_id);
        const lag = Number(c.lag_months ?? 0);
        const t = addMonths(yy, mm, lag);
        const val = mp?.get(ymStr(t.y, t.m)) ?? null;
        row[`S#${c.index_series_id}`] = Number.isFinite(Number(val)) ? (val as number) : null;
      }
      map.set(ym, row);
    }
    return map;
  }, [showSeries, form.components, pointsBySeries, startYM, form.months]);

  const mergedChartData = useMemo(() => {
    if (!Array.isArray(chartData) || chartData.length === 0) return [];
    if (!showSeries) return chartData;
    return chartData.map((r) => ({ ...r, ...(overlayByYM.get(r.ym) ?? {}) }));
  }, [chartData, showSeries, overlayByYM]);

  // ---------- actions ----------
  async function save() {
    setSaveMsg(null);
    if (!selectedId) {
      setSaveMsg({ err: "Select a row first." });
      return;
    }
    const weightSum = form.components.reduce((s, c) => s + (Number(c.weight_pct) || 0), 0);
    if (!Number.isFinite(weightSum)) {
      setSaveMsg({ err: "Weights are invalid." });
      return;
    }
    if (Math.abs(weightSum - 100) > 0.001) {
      if (!confirm(`Weights sum to ${weightSum.toFixed(2)}%, not 100%. Continue?`)) return;
    }
    if (form.product_id == null) {
      setSaveMsg({ err: "Product ID required. Select Product or enter the ID." });
      return;
    }
    const normalizedStartYM = form.start_ym && /^\d{4}-\d{2}$/.test(form.start_ym) ? form.start_ym : startYM;

    try {
      const payload = sanitizeFormulationPayload({
        product_id: form.product_id,
        name: `RF-${scope}-${selectedId}`,
        code: `RF-${scope}-${selectedId}`,
        base_price: form.base_price,
        frequency: form.frequency,
        compounding: form.compounding,
        start_ym: normalizedStartYM,
        components: form.components,
      });

      const created: any = await apiPost("/api/formulations", payload);
      const formulation_id = created?.id || created?.data?.id || created?.formulation_id;
      if (!formulation_id) throw new Error("Formulation ID not returned");

      if (scope === "service") {
        await apiPost(`/api/services/${selectedId}/attach-formulation`, { formulation_id });
      } else {
        await apiPost(`/api/boq-items/${selectedId}/attach-formulation`, { formulation_id });
      }

      setSaveMsg({ ok: "Saved successfully." });
    } catch (e: any) {
      const msg = e?.response?.data?.detail || e?.message || "Save failed.";
      setSaveMsg({ err: String(msg) });
    }
  }

  async function openProductPicker() {
    setProductOpen(true);
    if (products.length > 0) return;
    await loadProducts();
  }
  async function loadProducts() {
    setProductLoading(true);
    setProductErr(null);
    try {
      const res: any = await apiGet("/api/products?limit=1000&offset=0");
      setProducts(toArraySafe(res));
    } catch (e: any) {
      setProductErr(e?.message || "Failed to load products.");
    } finally {
      setProductLoading(false);
    }
  }
  function selectProduct(p: Product) {
    setForm((f) => ({ ...f, product_id: p.id, product_code: p.code, product_name: p.name }));
    setProductOpen(false);
  }
  function addComponent() {
    const firstSeries = series[0]?.id ?? 0;
    setForm((f) => ({
      ...f,
      components: [
        ...f.components,
        { index_series_id: Number(firstSeries) || 0, weight_pct: 100, base_ref_ym: startYM, lag_months: 0, factor: 1, cap_pct: null, floor_pct: null },
      ],
    }));
  }
  function removeComponent(idx: number) {
    setForm((f) => ({ ...f, components: f.components.filter((_, i) => i !== idx) }));
  }

  /* ===================== UI (returns AFTER all hooks) ===================== */

  if (loading) return <div>Loading…</div>;
  if (err) return <div className="text-red-600">{err}</div>;

  const selectionList: Array<ServiceRow | BOQItem> = scope === "service" ? services : boqs;

  return (
    <ErrorBoundary>
      <div className="grid grid-cols-12 gap-4">
        {/* Left: selector */}
        <aside className="col-span-4 border rounded-xl p-3 bg-white">
          <div className="flex items-center justify-between mb-2">
            <div className="font-semibold">Rows</div>
          </div>
          <div className="flex gap-2 mb-2">
            <button
              className={cls("px-2 py-1 rounded text-sm border", scope === "service" ? "bg-indigo-600 text-white border-indigo-600" : "bg-gray-100")}
              onClick={() => setScope("service")}
            >
              Services
            </button>
            <button
              className={cls("px-2 py-1 rounded text-sm border", scope === "boq" ? "bg-indigo-600 text-white border-indigo-600" : "bg-gray-100")}
              onClick={() => setScope("boq")}
            >
              BOQ
            </button>
          </div>
          <div className="h-[420px] overflow-auto divide-y">
            {selectionList.map((r) => (
              <div
                key={r.id}
                onClick={() => setSelectedId(r.id)}
                className={cls("p-2 cursor-pointer text-sm", selectedId === r.id ? "bg-indigo-50" : "hover:bg-gray-50")}
              >
                <div className="font-medium truncate">
                  {scope === "service" ? (r as ServiceRow).service_name || `#${r.id}` : (r as BOQItem).section || `#${r.id}`}
                </div>
                <div className="text-gray-600">
                  Base: {scope === "service" ? (r as ServiceRow).unit_cost ?? "—" : (r as BOQItem).unit_cogs ?? "—"}
                </div>
              </div>
            ))}
            {selectionList.length === 0 && <div className="p-2 text-sm text-gray-500">No rows found for this scenario.</div>}
          </div>
        </aside>

        {/* Right: editor + preview */}
        <main className="col-span-8 space-y-4">
          {!selectedId ? (
            <div className="text-sm text-gray-600 border rounded-xl p-6 bg-white">Select a row on the left.</div>
          ) : (
            <div className="space-y-4">
              {/* Editor Card */}
              <ErrorBoundary>
                <div className="border rounded-xl p-4 bg-white">
                  <div className="flex items-center justify-between">
                    <h3 className="font-semibold">Formulation</h3>
                    <div className="flex items-center gap-2">
                      <label className="text-sm flex items-center gap-1">
                        <input type="checkbox" checked={showSeries} onChange={(e) => setShowSeries(e.target.checked)} />
                        Visualize Series
                      </label>
                      <button onClick={save} className="px-3 py-1.5 rounded-md border text-sm hover:bg-gray-50">Save</button>
                    </div>
                  </div>

                  {saveMsg && (
                    <div
                      className={cls(
                        "mt-2 text-sm px-2 py-1 rounded border",
                        saveMsg.ok ? "text-green-700 bg-green-50 border-green-300" : "text-red-700 bg-red-50 border-red-300"
                      )}
                    >
                      {saveMsg.ok || saveMsg.err}
                    </div>
                  )}

                  {/* Top row */}
                  <div className="mt-3 grid grid-cols-5 gap-3 text-sm">
                    <label className="flex flex-col">
                      <span className="text-gray-600">Frequency</span>
                      <select value={form.frequency} onChange={(e) => setForm({ ...form, frequency: e.target.value as Frequency })} className="border rounded px-2 py-1">
                        <option value="monthly">Monthly</option>
                        <option value="quarterly">Quarterly</option>
                        <option value="annual">Annual</option>
                      </select>
                    </label>
                    <label className="flex flex-col">
                      <span className="text-gray-600">Compounding</span>
                      <select value={form.compounding} onChange={(e) => setForm({ ...form, compounding: e.target.value as Compounding })} className="border rounded px-2 py-1">
                        <option value="simple">Simple</option>
                        <option value="compound">Compound</option>
                      </select>
                    </label>
                    <label className="flex flex-col">
                      <span className="text-gray-600">Preview Months</span>
                      <input
                        type="number"
                        min={1}
                        max={120}
                        value={form.months}
                        onChange={(e) => setForm({ ...form, months: Math.max(1, Math.min(120, Number(e.target.value || 0))) })}
                        className="border rounded px-2 py-1"
                      />
                    </label>
                    <label className="flex flex-col">
                      <span className="text-gray-600">Start (YYYY-MM)</span>
                      <input type="month" value={startYM} onChange={(e) => setForm({ ...form, start_ym: e.target.value })} className="border rounded px-2 py-1" />
                    </label>

                    {/* Product */}
                    <div className="flex flex-col">
                      <span className="text-gray-600">Product <span className="text-red-500">*</span></span>
                      <div className="flex gap-2">
                        <input
                          type="number"
                          value={form.product_id ?? ""}
                          onChange={(e) => setForm({ ...form, product_id: e.target.value === "" ? null : Number(e.target.value) })}
                          placeholder="ID"
                          className="border rounded px-2 py-1 w-24"
                        />
                        <button onClick={openProductPicker} className="px-2 py-1 rounded-md border text-sm hover:bg-gray-50">Select Product</button>
                      </div>
                      {(form.product_code || form.product_name) && (
                        <div className="text-xs text-gray-600 mt-1">
                          Selected: <span className="font-mono">{form.product_code}</span> — {form.product_name}
                        </div>
                      )}
                    </div>
                  </div>

                  <div className="mt-3 grid grid-cols-5 gap-3 text-sm">
                    <label className="flex flex-col">
                      <span className="text-gray-600">Base Price</span>
                      <input type="number" value={form.base_price} onChange={(e) => setForm({ ...form, base_price: Number(e.target.value || 0) })} className="border rounded px-2 py-1" />
                    </label>
                    <div className="flex items-end">
                      <button onClick={addComponent} className="px-3 py-1.5 rounded-md border text-sm hover:bg-gray-50">+ Add Component</button>
                    </div>
                  </div>

                  {/* Components table */}
                  <div className="mt-4 border rounded-lg overflow-hidden">
                    <table className="w-full text-sm">
                      <thead className="bg-gray-50">
                        <tr>
                          <th className="text-left p-2 w-48">Index Series</th>
                          <th className="text-left p-2 w-24">Weight %</th>
                          <th className="text-left p-2 w-32">Base Ref</th>
                          <th className="text-left p-2 w-24">Lag (m)</th>
                          <th className="text-left p-2 w-24">Factor</th>
                          <th className="text-left p-2 w-24">Cap %</th>
                          <th className="text-left p-2 w-24">Floor %</th>
                          <th className="p-2"></th>
                        </tr>
                      </thead>
                      <tbody>
                        {form.components.length === 0 && (
                          <tr><td colSpan={8} className="p-3 text-center text-gray-500">No components. Add one.</td></tr>
                        )}
                        {form.components.map((c, i) => (
                          <tr key={`${c.index_series_id}-${i}`} className="border-t">
                            <td className="p-2">
                              <select
                                value={c.index_series_id}
                                onChange={(e) => {
                                  const v = Number(e.target.value);
                                  setForm((f) => ({ ...f, components: f.components.map((cc, j) => (j === i ? { ...cc, index_series_id: v } : cc)) }));
                                }}
                                className="border rounded px-2 py-1 w-full"
                              >
                                {series.length === 0 ? (
                                  <option value={0}>No series</option>
                                ) : (
                                  series.map((s) => (
                                    <option key={s.id} value={s.id}>{s.code} — {s.name}</option>
                                  ))
                                )}
                              </select>
                            </td>
                            <td className="p-2">
                              <input
                                type="number" min={0} max={100} value={c.weight_pct}
                                onChange={(e) => {
                                  const v = Math.max(0, Math.min(100, Number(e.target.value || 0)));
                                  setForm((f) => ({ ...f, components: f.components.map((cc, j) => (j === i ? { ...cc, weight_pct: v } : cc)) }));
                                }}
                                className="border rounded px-2 py-1 w-full"
                              />
                            </td>
                            <td className="p-2">
                              <input
                                type="month" value={c.base_ref_ym || startYM}
                                onChange={(e) => {
                                  const v = e.target.value || null;
                                  setForm((f) => ({ ...f, components: f.components.map((cc, j) => (j === i ? { ...cc, base_ref_ym: v } : cc)) }));
                                }}
                                className="border rounded px-2 py-1 w-full"
                              />
                            </td>
                            <td className="p-2">
                              <input
                                type="number" value={c.lag_months ?? 0}
                                onChange={(e) => {
                                  const v = Number(e.target.value || 0);
                                  setForm((f) => ({ ...f, components: f.components.map((cc, j) => (j === i ? { ...cc, lag_months: v } : cc)) }));
                                }}
                                className="border rounded px-2 py-1 w-full"
                              />
                            </td>
                            <td className="p-2">
                              <input
                                type="number" step="0.01" value={c.factor ?? 1}
                                onChange={(e) => {
                                  const v = Number(e.target.value || 1);
                                  setForm((f) => ({ ...f, components: f.components.map((cc, j) => (j === i ? { ...cc, factor: v } : cc)) }));
                                }}
                                className="border rounded px-2 py-1 w-full"
                              />
                            </td>
                            <td className="p-2">
                              <input
                                type="number" step="0.01" value={c.cap_pct ?? ""}
                                onChange={(e) => {
                                  const v = e.target.value === "" ? null : Number(e.target.value);
                                  setForm((f) => ({ ...f, components: f.components.map((cc, j) => (j === i ? { ...cc, cap_pct: v } : cc)) }));
                                }}
                                placeholder="—"
                                className="border rounded px-2 py-1 w-full"
                              />
                            </td>
                            <td className="p-2">
                              <input
                                type="number" step="0.01" value={c.floor_pct ?? ""}
                                onChange={(e) => {
                                  const v = e.target.value === "" ? null : Number(e.target.value);
                                  setForm((f) => ({ ...f, components: f.components.map((cc, j) => (j === i ? { ...cc, floor_pct: v } : cc)) }));
                                }}
                                placeholder="—"
                                className="border rounded px-2 py-1 w-full"
                              />
                            </td>
                            <td className="p-2 text-right">
                              <button onClick={() => removeComponent(i)} className="px-2 py-1 rounded border text-xs hover:bg-gray-50">Remove</button>
                            </td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  </div>
                </div>
              </ErrorBoundary>

              {/* Preview Card */}
              <ErrorBoundary>
                <div className="border rounded-xl p-4 bg-white">
                  <div className="flex items-center justify-between mb-2">
                    <h3 className="font-semibold">Preview</h3>
                    <div className="text-sm text-gray-600">Start: {startYM} • Horizon: {form.months}m</div>
                  </div>

                  <ChartSafe
                    data={mergedChartData}
                    render={(rows) => (
                      <div className="h-80">
                        <ResponsiveContainer width="100%" height="100%">
                          <LineChart data={rows} margin={{ top: 10, right: 16, bottom: 8, left: 0 }}>
                            <CartesianGrid strokeDasharray="3 3" />
                            <XAxis dataKey="ym" tick={{ fontSize: 11 }} minTickGap={18} interval="preserveStartEnd" />
                            <YAxis yAxisId="left" tick={{ fontSize: 11 }} />
                            <YAxis yAxisId="right" orientation="right" tick={{ fontSize: 11 }} />
                            <Tooltip />
                            <Legend />
                            <Line yAxisId="left" type="monotone" dataKey="price" name="Price" dot={false} />
                            <Line yAxisId="right" type="monotone" dataKey="idx" name="Composite Index" dot={false} />
                            {showSeries &&
                              form.components.map((c, i) => (
                                <Line
                                  key={`overlay-${c.index_series_id}-${i}`}
                                  yAxisId="right"
                                  type="monotone"
                                  dataKey={`S#${c.index_series_id}`}
                                  name={`Series ${c.index_series_id}`}
                                  dot={false}
                                />
                              ))}
                          </LineChart>
                        </ResponsiveContainer>
                      </div>
                    )}
                  />
                </div>
              </ErrorBoundary>
            </div>
          )}
        </main>

        {/* Product Picker Modal */}
        {productOpen && (
          <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/30">
            <div className="bg-white rounded-xl shadow-xl w-[720px] max-h-[80vh] flex flex-col">
              <div className="flex items-center justify-between px-4 py-3 border-b">
                <div className="font-semibold">Select Product</div>
                <button onClick={() => setProductOpen(false)} className="px-2 py-1 rounded border text-xs hover:bg-gray-50">Close</button>
              </div>
              <div className="p-3 border-b">
                <div className="flex gap-2">
                  <input
                    value={productQ}
                    onChange={(e) => setProductQ(e.target.value)}
                    placeholder="Search code / name / currency / uom…"
                    className="border rounded px-2 py-1 text-sm flex-1"
                  />
                  <button onClick={loadProducts} className="px-2 py-1 rounded-md border text-sm hover:bg-gray-50">Refresh</button>
                </div>
                {productErr && <div className="text-sm text-red-600 mt-2">{productErr}</div>}
              </div>
              <div className="p-0 overflow-auto">
                {productLoading ? (
                  <div className="p-4 text-sm text-gray-600">Loading…</div>
                ) : (
                  <table className="w-full text-sm">
                    <thead className="bg-gray-50 sticky top-0">
                      <tr>
                        <th className="text-left p-2 w-24">ID</th>
                        <th className="text-left p-2 w-32">Code</th>
                        <th className="text-left p-2">Name</th>
                        <th className="text-left p-2 w-20">Currency</th>
                        <th className="text-left p-2 w-20">UoM</th>
                        <th className="text-right p-2 w-24"></th>
                      </tr>
                    </thead>
                    <tbody>
                      {filteredProducts.length === 0 && (
                        <tr><td colSpan={6} className="p-4 text-center text-gray-500">No products found.</td></tr>
                      )}
                      {filteredProducts.map((p) => (
                        <tr key={p.id} className="border-t hover:bg-gray-50">
                          <td className="p-2 font-mono">{p.id}</td>
                          <td className="p-2 font-mono">{p.code}</td>
                          <td className="p-2">{p.name}</td>
                          <td className="p-2">{p.currency || "—"}</td>
                          <td className="p-2">{p.uom || "—"}</td>
                          <td className="p-2 text-right">
                            <button className="px-2 py-1 rounded border text-xs hover:bg-gray-50" onClick={() => selectProduct(p)}>Select</button>
                          </td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                )}
              </div>
            </div>
          </div>
        )}
      </div>
    </ErrorBoundary>
  );
}
