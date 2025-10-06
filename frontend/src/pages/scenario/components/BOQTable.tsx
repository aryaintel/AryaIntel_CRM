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

type PriceTerm = "bulk_with_freight" | "bulk_ex_freight" | "freight";

type BOQItem = {
  id?: number;
  scenario_id?: number;

  section?: string | null;

  // Legacy commercial category (kept for compatibility – hidden on UI redesign)
  category?: PriceTerm | null;

  // Persisted product link
  product_id?: number | null;

  // Display fields
  item_name: string;
  unit: string; // UOM

  // Price term snapshot/override stored on BOQ row (BE field is singular)
  price_term?: PriceTerm | null;

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

type ProductFamily = {
  id: number;
  name: string;
  is_active?: number;
  description?: string | null;
};
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
  // optional; if BE doesn't send, ignore
  price_term?: PriceTerm | null;
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
  const d0 = new Date(y, (m || 1) - 1, 1);
  const d1 = new Date(d0.getFullYear(), d0.getMonth() + k, 1);
  return { year: d1.getFullYear(), month: d1.getMonth() + 1 };
}
function ymKey(y: number, m: number) {
  return `${y}-${pad2(m)}`;
}
function toISODateYYYYMM01(y: number | null | undefined, m: number | null | undefined) {
  if (!y || !m) return null;
  return `${y}-${pad2(m)}-01`;
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

const PRICE_TERMS_OPTIONS: Array<NonNullable<BOQItem["price_term"]>> = [
  "bulk_with_freight",
  "bulk_ex_freight",
  "freight",
];

/* ---------- Lightweight Product Picker (inline modal) ---------- */
function ProductPicker({
  open,
  onClose,
  onPick,
  familyId,
}: {
  open: boolean;
  onClose: () => void;
  onPick: (p: Product) => void;
  familyId?: number | "";
}) {
  const [families, setFamilies] = useState<ProductFamily[]>([]);
  const [familyFilter, setFamilyFilter] = useState<number | "">("");
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

  useEffect(() => {
    if (open) setFamilyFilter(familyId ?? "");
  }, [open, familyId]);

  async function fetchProducts() {
    setLoading(true);
    setErr(null);
    try {
      const params = new URLSearchParams();
      params.set("limit", "1000");
      if (q) params.set("q", q);
      if (familyFilter) params.set("family_id", String(familyFilter));
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
          <div className="font-semibold">Select Product</div>
          <div className="ml-auto flex gap-2">
            <select
              className="px-2 py-1 rounded border"
              value={familyFilter}
              onChange={(e) => setFamilyFilter(e.target.value ? Number(e.target.value) : "")}
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
                <th className="px-3 py-2 w-28"></th>
              </tr>
            </thead>
            <tbody>
              {items.length > 0 ? (
                items.map((p) => (
                  <tr key={p.id} className="odd:bg-white even:bg-gray-50">
                    <td className="px-3 py-2">{p.code}</td>
                    <td className="px-3 py-2">{p.name}</td>
                    <td className="px-3 py-2">{p.uom || ""}</td>
                    <td className="px-3 py-2">
                      <button
                        className="px-2 py-1 rounded border hover:bg-gray-50 text-sm"
                        onClick={() => onPick(p)}
                      >
                        Select
                      </button>
                    </td>
                  </tr>
                ))
              ) : !loading ? (
                <tr>
                  <td colSpan={4} className="px-3 py-4 text-center text-gray-500">
                    No products
                  </td>
                </tr>
              ) : null}
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
        Note: <code>monthly</code> lines spread over the given <b>Duration</b>;{" "}
        <code>once</code>/<code>per_shipment</code>/<code>per_tonne</code> are single-shot.
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

  // Families (filter for product picker)
  const [families, setFamilies] = useState<ProductFamily[]>([]);
  useEffect(() => {
    (async () => {
      try {
        const fam = await apiGet<FamiliesListResp>("/api/product-families");
        setFamilies(fam.items || []);
      } catch {
        /* ignore */
      }
    })();
  }, []);

  // UI-only selected family per row/draft (not persisted)
  const [draftFamilyId, setDraftFamilyId] = useState<number | "">("");
  const [rowFamilyId, setRowFamilyId] = useState<Record<number, number | "">>({});

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
      // Normalize BE that might still send legacy `price_terms`
      const norm = list.map((r: any) => ({
        ...r,
        price_term: r.price_term ?? r.price_terms ?? null,
      })) as BOQItem[];
      setRows(norm);

      // backfill product cache
      const ids = Array.from(
        new Set(norm.map((r) => r.product_id).filter((v): v is number => typeof v === "number"))
      ).filter((id) => !(id in productCache));
      if (ids.length > 0) {
        const fetched: Record<number, Product> = {};
        await Promise.all(
          ids.map(async (id) => {
            try {
              const p = await apiGet<Product>(`/api/products/${id}`);
              fetched[id] = p;
            } catch {
              /* ignore */
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
      price_term: "bulk_with_freight",
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
    setDraftFamilyId("");
  }
  function cancelAdd() {
    setDraft(null);
    setDraftFamilyId("");
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
      // Normalize possible legacy echo
      const createdNorm: BOQItem = { ...created, price_term: (created as any).price_term ?? (created as any).price_terms ?? null };
      setRows((p) => [...p, createdNorm]);
      if (created.product_id && !(created.product_id in productCache)) {
        try {
          const p = await apiGet<Product>(`/api/products/${created.product_id}`);
          setProductCache((prev) => ({ ...prev, [p.id]: p }));
        } catch {}
      }
      setDraft(null);
      setDraftFamilyId("");
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
      const updNorm: BOQItem = { ...upd, price_term: (upd as any).price_term ?? (upd as any).price_terms ?? null };
      setRows((p) => p.map((x) => (x.id === r.id ? updNorm : x)));
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

  /* ======= Monthly Preview ======= */
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

  // Compute lookup window: single-month window based on Start (Y/M)
  function singleMonthWindow(r: { start_year?: number | null; start_month?: number | null }) {
    const startISO = toISODateYYYYMM01(r.start_year ?? null, r.start_month ?? null);
    if (!startISO) return { startISO: null as string | null, endISO: null as string | null };
    // same-month window – BE best-price works with a single date too
    return { startISO, endISO: startISO };
  }

  // Try BE `/best-price?start&end`, fallback to legacy `/best-price`
  async function fetchBestPrice(productId: number, startISO?: string | null, endISO?: string | null) {
    try {
      if (startISO && endISO) {
        const q = new URLSearchParams();
        q.set("start", startISO);
        q.set("end", endISO);
        const resp = await apiGet<BestPriceResp>(`/api/products/${productId}/best-price?${q.toString()}`);
        return resp;
      }
      const resp = await apiGet<BestPriceResp>(`/api/products/${productId}/best-price`);
      return resp;
    } catch (e) {
      throw e;
    }
  }

  // Auto-update price for a row after product or start date changes
  async function refreshBestPriceForRow(rowId: number) {
    const row = rows.find((x) => x.id === rowId);
    if (!row?.product_id) return;
    try {
      const { startISO, endISO } = singleMonthWindow(row);
      const price = await fetchBestPrice(row.product_id, startISO, endISO);
      setRows((prev) =>
        prev.map((x) =>
          x.id === rowId
            ? {
                ...x,
                unit_price: Number(price.unit_price),
                // sync price_term if BE provides it
                price_term: price.price_term ?? x.price_term ?? null,
              }
            : x
        )
      );
    } catch (e: any) {
      // silent; user can enter price manually
      console.warn("best-price failed", e?.message || e);
    }
  }

  /* ---------- product selection handlers ---------- */
  async function applyProductToDraft(p: Product) {
    if (!draft) return;
    setProductCache((prev) => ({ ...prev, [p.id]: p }));

    // UOM from product
    const nextDraft: BOQItem = {
      ...draft,
      product_id: p.id,
      item_name: p.name,
      unit: p.uom || draft.unit || "",
    };

    // If Start (Y/M) chosen, fetch price for that month
    let autoPrice: number | null = null;
    try {
      const { startISO, endISO } = singleMonthWindow(nextDraft);
      const price = await fetchBestPrice(p.id, startISO, endISO);
      autoPrice = Number(price.unit_price);
      nextDraft.unit_price = autoPrice;
      if (price.price_term) nextDraft.price_term = price.price_term;
    } catch {
      // fallback base_price
      autoPrice = p.base_price != null ? Number(p.base_price) : 0;
      nextDraft.unit_price = autoPrice;
    }

    setDraft(nextDraft);
    setShowPickerFor(null);
  }

  async function applyProductToRow(rowId: number, p: Product) {
    setProductCache((prev) => ({ ...prev, [p.id]: p }));

    const current = rows.find((x) => x.id === rowId);
    if (!current) return;

    // Update UI first: item_name, UOM
    setRows((prev) =>
      prev.map((x) =>
        x.id === rowId
          ? {
              ...x,
              product_id: p.id,
              item_name: p.name,
              unit: p.uom || x.unit || "",
            }
          : x
      )
    );

    // If Start (Y/M) exists, fetch price
    try {
      const { startISO, endISO } = singleMonthWindow(current);
      const price = await fetchBestPrice(p.id, startISO, endISO);
      setRows((prev) =>
        prev.map((x) =>
          x.id === rowId
            ? {
                ...x,
                unit_price: Number(price.unit_price),
                price_term: price.price_term ?? x.price_term ?? null,
              }
            : x
        )
      );
    } catch {
      // fallback base_price
      setRows((prev) =>
        prev.map((x) =>
          x.id === rowId ? { ...x, unit_price: p.base_price != null ? Number(p.base_price) : 0 } : x
        )
      );
    }

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
              <th className="px-3 py-2 text-left w-[220px]">Family</th>
              <th className="px-3 py-2 text-left w-[320px]">Product</th>
              <th className="px-3 py-2 text-left w-[160px]">Price Term</th>
              <th className="px-3 py-2 text-left w-[100px]">UOM</th>
              <th className="px-3 py-2 text-right w-[90px]">Qty</th>
              <th className="px-3 py-2 text-right w-[120px]">Unit Price</th>
              <th className="px-3 py-2 text-right w-[110px]">Unit COGS</th>
              <th className="px-3 py-2 text-left w-[110px]">Freq</th>
              <th className="px-3 py-2 text-left w-[140px]">Start (Y/M)</th>
              <th className="px-3 py-2 text-left w-[120px]">Duration</th>
              <th className="px-3 py-2 text-center w-[70px]">Active</th>
              <th className="px-3 py-2 text-right w-[110px]">Line Rev</th>
              <th className="px-3 py-2 text-right w-[110px]">Line COGS</th>
              <th className="px-3 py-2 text-right w-[110px]">Line GM</th>
              <th className="px-3 py-2 w-48">Actions</th>
            </tr>
          </thead>

          <tbody>
            {/* ------ DRAFT ROW ------ */}
            {draft && (
              <tr className="bg-amber-50/40">
                <td className="px-3 py-2">
                  <select
                    className="w-full px-2 py-1 rounded border border-gray-300"
                    value={draftFamilyId}
                    onChange={(e) => setDraftFamilyId(e.target.value ? Number(e.target.value) : "")}
                  >
                    <option value="">All</option>
                    {families.map((f) => (
                      <option key={f.id} value={f.id}>
                        {f.name}
                      </option>
                    ))}
                  </select>
                </td>

                <td className="px-3 py-2">
                  <div className="flex gap-2">
                    <input
                      className="w-full px-2 py-1 rounded border border-gray-300"
                      placeholder="Product"
                      value={draft.item_name}
                      onChange={(e) => setDraft({ ...draft, item_name: e.target.value })}
                    />
                    <button
                      className="px-2 py-1 rounded border hover:bg-gray-50 text-xs"
                      onClick={() => setShowPickerFor("draft")}
                      title="Select Product"
                    >
                      Select
                    </button>
                  </div>
                </td>

                <td className="px-3 py-2">
                  <select
                    className="w-full px-2 py-1 rounded border border-gray-300"
                    value={draft.price_term ?? "bulk_with_freight"}
                    onChange={(e) =>
                      setDraft({
                        ...draft,
                        price_term: e.target.value as BOQItem["price_term"],
                      })
                    }
                  >
                    {PRICE_TERMS_OPTIONS.map((c) => (
                      <option key={c} value={c}>
                        {c}
                      </option>
                    ))}
                  </select>
                </td>

                <td className="px-3 py-2">
                  <input
                    className="w-full px-2 py-1 rounded border border-gray-300"
                    placeholder="UOM"
                    value={draft.unit}
                    onChange={(e) => setDraft({ ...draft, unit: e.target.value })}
                    readOnly
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
                  <MonthInput
                    value={{
                      year: draft.start_year ?? null,
                      month: draft.start_month ?? null,
                    }}
                    onChange={async ({ year, month }) => {
                      const next = { ...draft, start_year: year, start_month: month };
                      // Update price if product chosen
                      if (next.product_id) {
                        try {
                          const { startISO, endISO } = singleMonthWindow(next);
                          const price = await fetchBestPrice(next.product_id!, startISO, endISO);
                          next.unit_price = Number(price.unit_price);
                          if (price.price_term) next.price_term = price.price_term;
                        } catch {
                          /* silent */
                        }
                      }
                      setDraft(next);
                    }}
                  />
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

            {/* ------ EXISTING ROWS ------ */}
            {rows.map((r) => {
              const lineRev = num(r.quantity) * num(r.unit_price);
              const lineCogs = num(r.quantity) * num(r.unit_cogs ?? 0);
              const lineGM = lineRev - lineCogs;
              const linkedProd = productOf(r.product_id ?? undefined);
              const famValue = rowFamilyId[r.id!] ?? "";

              return (
                <tr key={r.id} className="odd:bg-white even:bg-gray-50">
                  {/* Family (UI filter only) */}
                  <td className="px-3 py-2">
                    <select
                      className="w-full px-2 py-1 rounded border border-gray-300"
                      value={famValue}
                      onChange={(e) =>
                        setRowFamilyId((prev) => ({
                          ...prev,
                          [r.id!]: e.target.value ? Number(e.target.value) : "",
                        }))
                      }
                    >
                      <option value="">All</option>
                      {families.map((f) => (
                        <option key={f.id} value={f.id}>
                          {f.name}
                        </option>
                      ))}
                    </select>
                  </td>

                  {/* Product */}
                  <td className="px-3 py-2">
                    <div className="flex gap-2">
                      <input
                        className="w-full px-2 py-1 rounded border border-gray-300"
                        value={r.item_name}
                        onChange={(e) =>
                          setRows((p) => p.map((x) => (x.id === r.id ? { ...x, item_name: e.target.value } : x)))
                        }
                      />
                      <button
                        className="px-2 py-1 rounded border hover:bg-gray-50 text-xs"
                        onClick={() => setShowPickerFor(r.id!)}
                        title="Select Product"
                      >
                        Select
                      </button>
                    </div>
                    {!!r.product_id && (
                      <div className="text-xs text-gray-500">
                        linked: <b>{linkedProd?.code || `#${r.product_id}`}</b> • {linkedProd?.name || ""}
                      </div>
                    )}
                  </td>

                  {/* Price Term */}
                  <td className="px-3 py-2">
                    <select
                      className="w-full px-2 py-1 rounded border border-gray-300"
                      value={r.price_term ?? "bulk_with_freight"}
                      onChange={(e) =>
                        setRows((p) =>
                          p.map((x) =>
                            x.id === r.id
                              ? { ...x, price_term: e.target.value as BOQItem["price_term"] }
                              : x
                          )
                        )
                      }
                    >
                      {PRICE_TERMS_OPTIONS.map((c) => (
                        <option key={c} value={c}>
                          {c}
                        </option>
                      ))}
                    </select>
                  </td>

                  {/* UOM (read-only; from product) */}
                  <td className="px-3 py-2">
                    <input
                      className="w-full px-2 py-1 rounded border border-gray-300"
                      value={r.unit}
                      onChange={() => {}}
                      readOnly
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

                  {/* Start (Y/M) – update price when changed */}
                  <td className="px-3 py-2">
                    <MonthInput
                      value={{
                        year: r.start_year ?? null,
                        month: r.start_month ?? null,
                      }}
                      onChange={async ({ year, month }) => {
                        setRows((p) =>
                          p.map((x) =>
                            x.id === r.id ? { ...x, start_year: year, start_month: month } : x
                          )
                        );
                        if (r.product_id) {
                          await refreshBestPriceForRow(r.id!);
                        }
                      }}
                    />
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
                    </div>
                  </td>
                </tr>
              );
            })}
          </tbody>

          {showPreview && (
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
                  {(totals.rev - totals.cogs).toLocaleString(undefined, { maximumFractionDigits: 2 })}
                </td>
                <td />
              </tr>
            </tfoot>
          )}
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
        familyId={
          showPickerFor === "draft"
            ? draftFamilyId
            : typeof showPickerFor === "number"
            ? rowFamilyId[showPickerFor] ?? ""
            : ""
        }
      />

      {showPreview && (
        <div className="mt-3 border rounded bg-white">
          <div className="px-3 py-2 border-b bg-gray-50 font-medium">
            Preview • Monthly schedule (active items)
          </div>
          <MonthlyPreviewPivot
            rows={schedule.rows}
            totals={{ revenue: totals.rev, cogs: totals.cogs, gm: totals.rev - totals.cogs }}
          />
        </div>
      )}
    </div>
  );
}
