// frontend/src/pages/scenario/components/BOQTable.tsx
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

  // NEW: link to product (nullable)
  product_id?: number | null;

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

type ProductFamily = { id: number; name: string; is_active?: number; description?: string | null };
type Product = {
  id: number;
  code: string;
  name: string;
  uom?: string | null;
  currency?: string | null;
  base_price?: number | null;
  product_family_id?: number | null;
};
type ProductsListResp = { items: Product[]; total: number; limit: number; offset: number };
type FamiliesListResp = { items: ProductFamily[] };
type BestPriceResp = {
  product_id: number;
  price_book_id: number;
  price_book_entry_id: number;
  unit_price: number;
  currency?: string | null;
  valid_from?: string | null;
  valid_to?: string | null;
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

/* ---------- Lightweight Product Picker (inline modal) ---------- */
function ProductPicker({
  open,
  onClose,
  onPick,
}: {
  open: boolean;
  onClose: () => void;
  onPick: (p: Product) => void;
}) {
  const [families, setFamilies] = useState<ProductFamily[]>([]);
  const [familyId, setFamilyId] = useState<number | "">("");
  const [q, setQ] = useState("");
  const [items, setItems] = useState<Product[]>([]);
  const [loading, setLoading] = useState(false);
  const [err, setErr] = useState<string | null>(null);

  useEffect(() => {
    if (!open) return;
    (async () => {
      try {
        const fam = await apiGet<FamiliesListResp>("/api/product-families");
        setFamilies(fam.items || []);
      } catch (e: any) {
        console.warn("families load failed", e?.message || e);
      }
    })();
  }, [open]);

  async function fetchProducts() {
    setLoading(true);
    setErr(null);
    try {
      const params = new URLSearchParams();
      params.set("limit", "1000");
      if (q) params.set("q", q);
      if (familyId) params.set("family_id", String(familyId));
      const resp = await apiGet<ProductsListResp>(`/api/products?${params.toString()}`);
      setItems(resp.items || []);
    } catch (e: any) {
      setErr(e?.response?.data?.detail || e?.message || "Failed to load products.");
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    if (open) fetchProducts();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [open]);

  return (
    <div
      className={cls("fixed inset-0 z-50", open ? "pointer-events-auto" : "pointer-events-none")}
      aria-hidden={!open}
    >
      <div
        className={cls(
          "absolute inset-0 bg-black/30 transition-opacity",
          open ? "opacity-100" : "opacity-0"
        )}
        onClick={onClose}
      />
      <div
        className={cls(
          "absolute left-1/2 top-12 -translate-x-1/2 w-[720px] max-w-[95vw] bg-white rounded-xl shadow-xl border",
          open ? "opacity-100" : "opacity-0"
        )}
      >
        <div className="px-4 py-3 border-b flex items-center gap-2">
          <div className="font-semibold">Pick Product</div>
          <div className="ml-auto flex gap-2">
            <select
              className="px-2 py-1 rounded border"
              value={familyId}
              onChange={(e) => setFamilyId(e.target.value ? Number(e.target.value) : "")}
              title="Product Family"
            >
              <option value="">All Families</option>
              {families.map((f) => (
                <option key={f.id} value={f.id}>
                  {f.name}
                </option>
              ))}
            </select>
            <input
              className="px-2 py-1 rounded border w-56"
              placeholder="Search code/name…"
              value={q}
              onChange={(e) => setQ(e.target.value)}
              onKeyDown={(e) => e.key === "Enter" && fetchProducts()}
            />
            <button className="px-3 py-1.5 rounded border" onClick={fetchProducts} disabled={loading}>
              Search
            </button>
            <button className="px-3 py-1.5 rounded border" onClick={onClose}>
              Close
            </button>
          </div>
        </div>
        {err && <div className="px-4 py-2 text-sm text-red-600">{err}</div>}
        <div className="max-h-[60vh] overflow-auto">
          <table className="min-w-full text-sm">
            <thead className="bg-gray-50">
              <tr>
                <th className="px-3 py-2 text-left">Code</th>
                <th className="px-3 py-2 text-left">Name</th>
                <th className="px-3 py-2 text-left">UOM</th>
                <th className="px-3 py-2 text-left">Family</th>
                <th className="px-3 py-2 w-28"></th>
              </tr>
            </thead>
            <tbody>
              {items.map((p) => (
                <tr key={p.id} className="odd:bg-white even:bg-gray-50">
                  <td className="px-3 py-2">{p.code}</td>
                  <td className="px-3 py-2">{p.name}</td>
                  <td className="px-3 py-2">{p.uom || ""}</td>
                  <td className="px-3 py-2">
                    {families.find((f) => f.id === (p.product_family_id || 0))?.name || ""}
                  </td>
                  <td className="px-3 py-2">
                    <button
                      className="px-2 py-1 rounded border hover:bg-gray-50 text-sm"
                      onClick={() => onPick(p)}
                    >
                      Select
                    </button>
                  </td>
                </tr>
              ))}
              {items.length === 0 && !loading && (
                <tr>
                  <td colSpan={5} className="px-3 py-4 text-center text-gray-500">
                    No products
                  </td>
                </tr>
              )}
            </tbody>
          </table>
        </div>
      </div>
    </div>
  );
}

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
        Note: <code>monthly</code> lines spread over the given <b>Duration</b>;
        <code> once</code>/<code>per_shipment</code>/<code>per_tonne</code> are single-shot.
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

  // product picker state
  // showPickerFor: null | "draft" | row.id
  const [showPickerFor, setShowPickerFor] = useState<null | "draft" | number>(null);

  // Product cache (id -> Product) for code/name display
  const [productCache, setProductCache] = useState<Record<number, Product>>({});

  async function load() {
    setLoading(true);
    setErr(null);
    try {
      const data = await apiGet<BOQItem[]>(`/scenarios/${scenarioId}/boq`);
      const list = Array.isArray(data) ? data : [];
      setRows(list);

      // cache'lenmemiş product'ları getir
      const ids = Array.from(
        new Set(list.map((r) => r.product_id).filter((v): v is number => typeof v === "number"))
      ).filter((id) => !(id in productCache));
      if (ids.length > 0) {
        const fetched: Record<number, Product> = {};
        await Promise.all(
          ids.map(async (id) => {
            try {
              const p = await apiGet<Product>(`/api/products/${id}`);
              fetched[id] = p;
            } catch {
              /* ignore individual failures */
            }
          })
        );
        if (Object.keys(fetched).length > 0) {
          setProductCache((prev) => ({ ...prev, ...fetched }));
        }
      }
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
      product_id: null,
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
      // product cache'e ekle
      if (created.product_id && !(created.product_id in productCache)) {
        try {
          const p = await apiGet<Product>(`/api/products/${created.product_id}`);
          setProductCache((prev) => ({ ...prev, [p.id]: p }));
        } catch {}
      }
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
      // product cache'e ekle
      if (upd.product_id && !(upd.product_id in productCache)) {
        try {
          const p = await apiGet<Product>(`/api/products/${upd.product_id}`);
          setProductCache((prev) => ({ ...prev, [p.id]: p }));
        } catch {}
      }
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

  /* ---------- product helpers ---------- */
  function productOf(id?: number | null): Product | undefined {
    if (!id || typeof id !== "number") return undefined;
    return productCache[id];
  }

  async function refreshBestPriceForRow(rowId: number) {
    const row = rows.find((x) => x.id === rowId);
    if (!row?.product_id) return;
    try {
      const price = await apiGet<BestPriceResp>(`/api/products/${row.product_id}/best-price`);
      const up = Number(price.unit_price);
      setRows((prev) => prev.map((x) => (x.id === rowId ? { ...x, unit_price: up } : x)));
    } catch (e: any) {
      alert(e?.response?.data?.detail || e?.message || "Best price not found.");
    }
  }

  /* ---------- product selection handlers ---------- */
  async function applyProductToDraft(p: Product) {
    if (!draft) return;
    let unitPrice = draft.unit_price ?? 0;
    try {
      const price = await apiGet<BestPriceResp>(`/api/products/${p.id}/best-price`);
      unitPrice = Number(price.unit_price);
    } catch {
      unitPrice = p.base_price != null ? Number(p.base_price) : 0;
    }
    setProductCache((prev) => ({ ...prev, [p.id]: p }));
    setDraft({
      ...draft,
      product_id: p.id,
      item_name: p.name,
      unit: p.uom || draft.unit,
      unit_price: unitPrice,
    });
    setShowPickerFor(null);
  }

  async function applyProductToRow(rowId: number, p: Product) {
    let unitPrice = 0;
    try {
      const price = await apiGet<BestPriceResp>(`/api/products/${p.id}/best-price`);
      unitPrice = Number(price.unit_price);
    } catch {
      unitPrice = p.base_price != null ? Number(p.base_price) : 0;
    }
    setProductCache((prev) => ({ ...prev, [p.id]: p }));
    setRows((prev) =>
      prev.map((x) =>
        x.id === rowId
          ? {
              ...x,
              product_id: p.id,
              item_name: p.name,
              unit: p.uom || x.unit,
              unit_price: unitPrice,
            }
          : x
      )
    );
    setShowPickerFor(null);
  }

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
            title="Monthly simulation (Revenue/COGS/GM)"
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
        <div className="text-sm text-red-600 bg-red-50 border border-red-200 p-2 rounded">{err}</div>
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
              <th className="px-3 py-2 w-48">Actions</th>
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
                  <div className="flex flex-col gap-1">
                    <div className="flex gap-2">
                      <input
                        className="w-full px-2 py-1 rounded border border-gray-300"
                        placeholder="Item"
                        value={draft.item_name}
                        onChange={(e) => setDraft({ ...draft, item_name: e.target.value })}
                      />
                      <button
                        className="px-2 py-1 rounded border hover:bg-gray-50 text-xs"
                        onClick={() => setShowPickerFor("draft")}
                        title="Pick Product"
                      >
                        Pick
                      </button>
                    </div>
                    {!!draft.product_id && (
                      <div className="text-xs text-gray-500">
                        Linked product:{" "}
                        <b>
                          {productOf(draft.product_id)?.code || `#${draft.product_id}`}
                        </b>{" "}
                        • {productOf(draft.product_id)?.name || ""}
                        <button
                          className="ml-2 px-2 py-0.5 border rounded text-[11px] hover:bg-gray-50"
                          onClick={async () => {
                            try {
                              const bp = await apiGet<BestPriceResp>(
                                `/api/products/${draft.product_id}/best-price`
                              );
                              setDraft((prev) =>
                                prev ? { ...prev, unit_price: Number(bp.unit_price) } : prev
                              );
                            } catch (e: any) {
                              alert(e?.message || "Best price not found.");
                            }
                          }}
                          title="Refresh best price"
                        >
                          Best price ↻
                        </button>
                      </div>
                    )}
                  </div>
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
              const linkedProd = productOf(r.product_id ?? undefined);

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
                    <div className="flex flex-col gap-1">
                      <div className="flex gap-2">
                        <input
                          className="w-full px-2 py-1 rounded border border-gray-300"
                          value={r.item_name}
                          onChange={(e) =>
                            setRows((p) =>
                              p.map((x) => (x.id === r.id ? { ...x, item_name: e.target.value } : x))
                            )
                          }
                        />
                        <button
                          className="px-2 py-1 rounded border hover:bg-gray-50 text-xs"
                          onClick={() => setShowPickerFor(r.id!)}
                          title="Pick Product"
                        >
                          Pick
                        </button>
                      </div>
                      {!!r.product_id && (
                        <div className="text-xs text-gray-500">
                          Linked product:{" "}
                          <b>{linkedProd?.code || `#${r.product_id}`}</b>{" "}
                          • {linkedProd?.name || ""}
                          <button
                            className="ml-2 px-2 py-0.5 border rounded text-[11px] hover:bg-gray-50"
                            onClick={() => refreshBestPriceForRow(r.id!)}
                            disabled={!r.product_id}
                            title="Refresh best price"
                          >
                            Best price ↻
                          </button>
                        </div>
                      )}
                    </div>
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
                    <div className="flex flex-wrap gap-2">
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
                      <button
                        onClick={() => refreshBestPriceForRow(r.id!)}
                        className="px-2 py-1 rounded border hover:bg-gray-50 text-sm disabled:opacity-50"
                        disabled={!r.product_id}
                        title="Refresh best price from price books"
                      >
                        Best price ↻
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

      {/* Product Picker modal (for draft or an existing row) */}
      <ProductPicker
        open={showPickerFor !== null}
        onClose={() => setShowPickerFor(null)}
        onPick={(p) => {
          if (showPickerFor === "draft") return applyProductToDraft(p);
          if (typeof showPickerFor === "number") return applyProductToRow(showPickerFor, p);
        }}
      />

      {showPreview && (
        <div className="mt-3 border rounded bg-white">
          <div className="px-3 py-2 border-b bg-gray-50 font-medium">
            Preview • Monthly schedule (active items)
          </div>
          <MonthlyPreviewPivot rows={schedule.rows} totals={schedule.totals} />
        </div>
      )}
    </div>
  );
}
