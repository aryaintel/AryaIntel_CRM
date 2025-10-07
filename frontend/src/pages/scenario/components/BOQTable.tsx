// frontend/src/pages/scenario/components/BOQTable.tsx
import React, { useEffect, useMemo, useRef, useState } from "react";
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
  category?: PriceTerm | null;

  product_id?: number | null;

  item_name: string;
  unit: string; // UOM

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
  price_term?: PriceTerm | null; // backend should return this
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

/* ---------- Reusable Inputs ---------- */
function NumberInput({
  value,
  onChange,
  className,
  min,
  step = "any",
  placeholder,
  title,
  width = "w-full",
}: {
  value: number | string | null | undefined;
  onChange: (n: number) => void;
  className?: string;
  min?: number;
  step?: number | "any";
  placeholder?: string;
  title?: string;
  width?: string;
}) {
  return (
    <input
      type="number"
      inputMode="decimal"
      step={step}
      min={min}
      value={value ?? ""}
      onChange={(e) => onChange(e.target.value === "" ? 0 : Number(e.target.value))}
      onWheel={(e) => (e.currentTarget as HTMLInputElement).blur()}
      className={cls(
        "px-2 py-1 rounded border border-gray-300 text-right font-mono tabular-nums",
        width,
        className
      )}
      placeholder={placeholder}
      title={title ?? String(value ?? "")}
    />
  );
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
        const v = e.target.value;
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
      title={str || ""}
    />
  );
}

/* ---------- Family ---------- */
function FamilySelect({
  value,
  families,
  onChange,
  className,
  placeholder = "Select family…",
  disabled = false,
}: {
  value: number | "" | undefined;
  families: ProductFamily[];
  onChange: (next: number | "") => void;
  className?: string;
  placeholder?: string;
  disabled?: boolean;
}) {
  return (
    <select
      value={value === "" ? "" : String(value ?? "")}
      onChange={(e) => onChange(e.target.value === "" ? "" : Number(e.target.value))}
      className={cls(
        "w-full px-2 py-1.5 rounded border border-gray-300 text-sm",
        disabled ? "bg-gray-100 text-gray-500 cursor-not-allowed" : "",
        className
      )}
      disabled={disabled}
      title="Product Family"
    >
      <option value="">{placeholder}</option>
      {families
        .filter((f) => f.is_active !== 0)
        .map((f) => (
          <option key={f.id} value={f.id}>
            {f.name}
          </option>
        ))}
    </select>
  );
}

const PRICE_TERMS_OPTIONS: Array<NonNullable<BOQItem["price_term"]>> = [
  "bulk_with_freight",
  "bulk_ex_freight",
  "freight",
];

/* ---------- Product Autocomplete ---------- */
function useDebounced<T>(value: T, delay = 250) {
  const [v, setV] = useState(value);
  useEffect(() => {
    const t = setTimeout(() => setV(value), delay);
    return () => clearTimeout(t);
  }, [value, delay]);
  return v;
}

function ProductAutocomplete({
  familyId,
  disabled,
  value,
  onChangeText,
  onPick,
  placeholder = "Search product…",
}: {
  familyId: number | "" | undefined;
  disabled?: boolean;
  value: string;
  onChangeText: (t: string) => void;
  onPick: (p: Product) => void;
  placeholder?: string;
}) {
  const [open, setOpen] = useState(false);
  const [items, setItems] = useState<Product[]>([]);
  const [loading, setLoading] = useState(false);
  const [err, setErr] = useState<string | null>(null);
  const [highlight, setHighlight] = useState(0);
  const debouncedQ = useDebounced(value, 250);
  const boxRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    function onDocClick(e: MouseEvent) {
      if (!boxRef.current) return;
      if (!boxRef.current.contains(e.target as Node)) setOpen(false);
    }
    document.addEventListener("mousedown", onDocClick);
    return () => document.removeEventListener("mousedown", onDocClick);
  }, []);

  useEffect(() => {
    async function run() {
      if (!open) return;
      if (!debouncedQ || debouncedQ.trim().length < 2) {
        setItems([]);
        return;
      }
      setLoading(true);
      setErr(null);
      try {
        const params = new URLSearchParams();
        params.set("limit", "20");
        params.set("q", debouncedQ.trim());
        if (familyId) params.set("family_id", String(familyId));
        const resp = await apiGet<ProductsListResp>(`/api/products?${params.toString()}`);
        setItems(resp.items || []);
        setHighlight(0);
      } catch (e: any) {
        setErr(e?.response?.data?.detail || e?.message || "Failed to load products.");
      } finally {
        setLoading(false);
      }
    }
    run();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [debouncedQ, open, familyId]);

  return (
    <div className="relative" ref={boxRef}>
      <input
        className={cls(
          "w-full px-2 py-1 rounded border border-gray-300",
          disabled && "bg-gray-100 text-gray-500"
        )}
        placeholder={disabled ? "Select a family first" : placeholder}
        value={value}
        onChange={(e) => onChangeText(e.target.value)}
        onFocus={() => setOpen(true)}
        disabled={disabled}
        onKeyDown={(e) => {
          if (!open) return;
          if (e.key === "ArrowDown") {
            e.preventDefault();
            setHighlight((h) => Math.min(h + 1, Math.max(0, items.length - 1)));
          } else if (e.key === "ArrowUp") {
            e.preventDefault();
            setHighlight((h) => Math.max(0, h - 1));
          } else if (e.key === "Enter") {
            if (items[highlight]) {
              onPick(items[highlight]);
              setOpen(false);
            }
          } else if (e.key === "Escape") {
            setOpen(false);
            (e.target as HTMLInputElement).blur();
          }
        }}
      />
      {open && (
        <div className="absolute z-20 mt-1 w-full rounded-md border bg-white shadow-lg max-h-64 overflow-auto">
          {err && <div className="px-3 py-2 text-sm text-red-600">{err}</div>}
          {loading && <div className="px-3 py-2 text-sm text-gray-500">Searching…</div>}
          {!loading && !err && items.length === 0 && debouncedQ.trim().length >= 2 && (
            <div className="px-3 py-2 text-sm text-gray-500">No results</div>
          )}
          {!loading &&
            items.map((p, i) => (
              <div
                key={p.id}
                className={cls(
                  "px-3 py-2 text-sm cursor-pointer flex items-center gap-2",
                  i === highlight ? "bg-indigo-50" : "hover:bg-gray-50"
                )}
                onMouseEnter={() => setHighlight(i)}
                onMouseDown={(e) => {
                  e.preventDefault();
                  onPick(p);
                  setOpen(false);
                }}
                title={p.name}
              >
                <div className="min-w-[84px] font-mono text-xs text-gray-600">{p.code}</div>
                <div className="flex-1">{p.name}</div>
                <div className="text-xs text-gray-500">{p.uom || ""}</div>
              </div>
            ))}
          {!loading && debouncedQ.trim().length < 2 && (
            <div className="px-3 py-2 text-sm text-gray-500">Type at least 2 characters…</div>
          )}
        </div>
      )}
    </div>
  );
}

/* ---------- Pivot Preview ---------- */
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

/* ====== Resizable columns ====== */
type ColKey =
  | "family"
  | "product"
  | "price_term"
  | "uom"
  | "qty"
  | "unit_price"
  | "unit_cogs"
  | "freq"
  | "start"
  | "duration"
  | "active"
  | "actions";

const DEFAULT_COL_WIDTHS: Record<ColKey, number> = {
  family: 220,
  product: 360,
  price_term: 160,
  uom: 110,
  qty: 110,
  unit_price: 150,
  unit_cogs: 150,
  freq: 120,
  start: 170,
  duration: 120,
  active: 80,
  actions: 200,
};

const COL_LABELS: Record<ColKey, string> = {
  family: "Family",
  product: "Product",
  price_term: "Price Term",
  uom: "UOM",
  qty: "Qty",
  unit_price: "Unit Price",
  unit_cogs: "Unit COGS",
  freq: "Freq",
  start: "Start (Y/M)",
  duration: "Duration",
  active: "Active",
  actions: "Actions",
};

const STORAGE_KEY = "boq_col_widths_v1";

/* ========================================================= */

export default function BOQTable({ scenarioId, onChanged, onMarkedReady, isReady }: Props) {
  const [rows, setRows] = useState<BOQItem[]>([]);
  const [draft, setDraft] = useState<BOQItem | null>(null);
  const [loading, setLoading] = useState(false);
  const [err, setErr] = useState<string | null>(null);
  const [showPreview, setShowPreview] = useState(false);

  // Families
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

  // UI family per row/draft
  const [draftFamilyId, setDraftFamilyId] = useState<number | "">("");
  const [rowFamilyId, setRowFamilyId] = useState<Record<number, number | "">>({});

  // Product cache for linked display
  const [productCache, setProductCache] = useState<Record<number, Product>>({});

  // Column widths (resizable, persisted)
  const [colWidths, setColWidths] = useState<Record<ColKey, number>>(() => {
    try {
      const raw = localStorage.getItem(STORAGE_KEY);
      if (raw) {
        const parsed = JSON.parse(raw);
        return { ...DEFAULT_COL_WIDTHS, ...parsed };
      }
    } catch {}
    return DEFAULT_COL_WIDTHS;
  });

  useEffect(() => {
    try {
      localStorage.setItem(STORAGE_KEY, JSON.stringify(colWidths));
    } catch {}
  }, [colWidths]);

  const startResizingRef = useRef<{ key: ColKey; startX: number; startW: number } | null>(null);
  useEffect(() => {
    function onMove(e: MouseEvent) {
      const st = startResizingRef.current;
      if (!st) return;
      const dx = e.clientX - st.startX;
      setColWidths((prev) => {
        const w = Math.max(80, st.startW + dx);
        return { ...prev, [st.key]: w };
      });
    }
    function onUp() {
      startResizingRef.current = null;
    }
    window.addEventListener("mousemove", onMove);
    window.addEventListener("mouseup", onUp);
    return () => {
      window.removeEventListener("mousemove", onMove);
      window.removeEventListener("mouseup", onUp);
    };
  }, []);

  function beginResize(key: ColKey, e: React.MouseEvent) {
    startResizingRef.current = { key, startX: e.clientX, startW: colWidths[key] };
    e.preventDefault();
    e.stopPropagation();
  }

  async function load() {
    setLoading(true);
    setErr(null);
    try {
      const data = await apiGet<BOQItem[]>(`/scenarios/${scenarioId}/boq`);
      const list = Array.isArray(data) ? data : [];
      const norm = list.map((r: any) => ({
        ...r,
        price_term: r.price_term ?? r.price_terms ?? null,
      })) as BOQItem[];
      setRows(norm);

      // backfill product cache + seed rowFamilyId only if not set
      const ids = Array.from(
        new Set(norm.map((r) => r.product_id).filter((v): v is number => typeof v === "number"))
      ).filter((id) => !(id in productCache));

      const fetched: Record<number, Product> = {};
      await Promise.all(
        ids.map(async (id) => {
          try {
            const p = await apiGet<Product>(`/api/products/${id}`);
            fetched[id] = p;
          } catch {}
        })
      );
      if (Object.keys(fetched).length > 0) {
        setProductCache((prev) => ({ ...prev, ...fetched }));
      }

      // seed family per row if empty (one-time default from product)
      setRowFamilyId((prev) => {
        const next = { ...prev };
        for (const r of norm) {
          if (r.id == null) continue;
          if (Object.prototype.hasOwnProperty.call(next, r.id)) continue;
          const prod =
            (r.product_id && (fetched[r.product_id] || productCache[r.product_id])) || undefined;
          const pf = prod?.product_family_id;
          if (pf) next[r.id] = pf;
        }
        return next;
      });
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

      if (r.frequency === "monthly") {
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

  function singleMonthWindow(r: { start_year?: number | null; start_month?: number | null }) {
    const startISO = toISODateYYYYMM01(r.start_year ?? null, r.start_month ?? null);
    if (!startISO) return { on: null as string | null };
    return { on: startISO };
  }

  // IMPORTANT: use 'on=YYYY-MM-01' to match backend contract
  async function fetchBestPrice(productId: number, onISO?: string | null) {
    const q = new URLSearchParams();
    if (onISO) q.set("on", onISO);
    return apiGet<BestPriceResp>(
      `/api/products/${productId}/best-price${q.toString() ? `?${q.toString()}` : ""}`
    );
  }

  async function refreshBestPriceForRow(rowId: number) {
    const row = rows.find((x) => x.id === rowId);
    if (!row?.product_id) return;
    try {
      const { on } = singleMonthWindow(row);
      const price = await fetchBestPrice(row.product_id, on);
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
      /* silent */
    }
  }

  /* ---------- selection helpers ---------- */
  async function applyProductToDraft(p: Product) {
    if (!draft) return;
    setProductCache((prev) => ({ ...prev, [p.id]: p }));

    const nextDraft: BOQItem = {
      ...draft,
      product_id: p.id,
      item_name: `${p.code} — ${p.name}`,
      unit: p.uom || draft.unit || "",
    };

    try {
      const { on } = singleMonthWindow(nextDraft);
      const price = await fetchBestPrice(p.id, on);
      nextDraft.unit_price = Number(price.unit_price);
      if (price.price_term) nextDraft.price_term = price.price_term;
    } catch {
      nextDraft.unit_price = p.base_price != null ? Number(p.base_price) : 0;
    }

    setDraft(nextDraft);
    // draft row’s family UI = product family (helps persistence after save)
    if (p.product_family_id && !draftFamilyId) setDraftFamilyId(p.product_family_id);
  }

  async function applyProductToRow(rowId: number, p: Product) {
    setProductCache((prev) => ({ ...prev, [p.id]: p }));

    // when product changes, adopt its family once
    if (p.product_family_id) {
      setRowFamilyId((prev) => ({ ...prev, [rowId]: p.product_family_id! }));
    }

    const current = rows.find((x) => x.id === rowId);
    if (!current) return;

    setRows((prev) =>
      prev.map((x) =>
        x.id === rowId
          ? {
              ...x,
              product_id: p.id,
              item_name: `${p.code} — ${p.name}`,
              unit: p.uom || x.unit || "",
            }
          : x
      )
    );

    try {
      const { on } = singleMonthWindow(current);
      const price = await fetchBestPrice(p.id, on);
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
      setRows((prev) =>
        prev.map((x) =>
          x.id === rowId ? { ...x, unit_price: p.base_price != null ? Number(p.base_price) : 0 } : x
        )
      );
    }
  }

  /* ========================================================= */

  const cols: ColKey[] = [
    "family",
    "product",
    "price_term",
    "uom",
    "qty",
    "unit_price",
    "unit_cogs",
    "freq",
    "start",
    "duration",
    "active",
    "actions",
  ];

  function Th({
    k,
    children,
    align = "left",
  }: {
    k: ColKey;
    children: React.ReactNode;
    align?: "left" | "right" | "center";
  }) {
    return (
      <th
        className={cls(
          "px-3 py-2 bg-gray-50 border-b relative select-none",
          align === "right" ? "text-right" : align === "center" ? "text-center" : "text-left"
        )}
        style={{ width: colWidths[k], minWidth: colWidths[k] }}
      >
        <div className="pr-2">{children}</div>
        <span
          onMouseDown={(e) => beginResize(k, e)}
          className="absolute right-0 top-0 h-full w-2 cursor-col-resize bg-transparent hover:bg-indigo-300/60 z-10"
          title="Drag to resize"
        />
      </th>
    );
  }

  // --- Family value precedence: manual (rowFamilyId) -> product.family -> ""
  function getFamilyValueForRow(r: BOQItem): number | "" {
    if (r.id != null && Object.prototype.hasOwnProperty.call(rowFamilyId, r.id)) {
      return rowFamilyId[r.id]!;
    }
    const pf = r.product_id ? productOf(r.product_id)?.product_family_id : undefined;
    return pf ?? "";
  }

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
            onClick={() =>
              setColWidths((_) => {
                const next = { ...DEFAULT_COL_WIDTHS };
                try {
                  localStorage.setItem(STORAGE_KEY, JSON.stringify(next));
                } catch {}
                return next;
              })
            }
            className="px-3 py-1.5 rounded-md border text-sm hover:bg-gray-50"
            title="Reset column widths"
          >
            Reset Columns
          </button>
          <button
            onClick={() =>
              setDraft({
                section: "",
                category: "bulk_with_freight",
                product_id: null,
                item_name: "",
                unit: "",
                price_term: null, // will fill when product picked
                quantity: 0,
                unit_price: 0,
                unit_cogs: 0,
                frequency: "once",
                months: null,
                start_year: null,
                start_month: null,
                is_active: true,
                notes: "",
              })
            }
            className="px-3 py-1.5 rounded-md bg-indigo-600 text-white text-sm hover:bg-indigo-500"
          >
            + Add BOQ Item
          </button>
          <button
            onClick={() => setShowPreview((v) => !v)}
            className="px-3 py-1.5 rounded-md border text-sm hover:bg-gray-50"
            title="Monthly simulation (Revenue/COGS/GM)"
          >
            {showPreview ? "Hide Preview" : "Show Preview"}
          </button>
          <button
            onClick={async () => {
              if (!confirm("Mark BOQ as ready and move to TWC?")) return;
              try {
                await apiPost(`/scenarios/${scenarioId}/boq/mark-ready`, {});
                onChanged?.();
                onMarkedReady?.();
              } catch (e: any) {
                alert(e?.response?.data?.detail || e?.message || "Cannot mark as ready.");
              }
            }}
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
        <table className="min-w-full text-sm" style={{ tableLayout: "fixed" }}>
          <colgroup>
            {cols.map((k) => (
              <col key={k} style={{ width: colWidths[k], minWidth: colWidths[k] }} />
            ))}
          </colgroup>

          <thead>
            <tr>
              <Th k="family">{COL_LABELS.family}</Th>
              <Th k="product">{COL_LABELS.product}</Th>
              <Th k="price_term">{COL_LABELS.price_term}</Th>
              <Th k="uom">{COL_LABELS.uom}</Th>
              <Th k="qty" align="right">
                {COL_LABELS.qty}
              </Th>
              <Th k="unit_price" align="right">
                {COL_LABELS.unit_price}
              </Th>
              <Th k="unit_cogs" align="right">
                {COL_LABELS.unit_cogs}
              </Th>
              <Th k="freq">{COL_LABELS.freq}</Th>
              <Th k="start">{COL_LABELS.start}</Th>
              <Th k="duration">{COL_LABELS.duration}</Th>
              <Th k="active" align="center">
                {COL_LABELS.active}
              </Th>
              <Th k="actions">{COL_LABELS.actions}</Th>
            </tr>
          </thead>

          <tbody>
            {/* ------ DRAFT ROW ------ */}
            {draft && (
              <tr className="bg-amber-50/40">
                <td className="px-3 py-2">
                  <FamilySelect
                    value={draftFamilyId}
                    families={families}
                    onChange={(nextId) => {
                      setDraftFamilyId(nextId);
                      setDraft((d) =>
                        d
                          ? {
                              ...d,
                              product_id: null,
                              item_name: "",
                              unit: "",
                              price_term: null, // clear and unfreeze
                            }
                          : d
                      );
                    }}
                  />
                </td>

                <td className="px-3 py-2">
                  <ProductAutocomplete
                    familyId={draftFamilyId}
                    disabled={!draftFamilyId}
                    value={draft.item_name}
                    onChangeText={(t) => setDraft({ ...draft, item_name: t })}
                    onPick={(p) => applyProductToDraft(p)}
                    placeholder="Search code or name…"
                  />
                </td>

                <td className="px-3 py-2">
                  <select
                    className={cls(
                      "w-full px-2 py-1 rounded border border-gray-300",
                      draft.product_id ? "bg-gray-100 text-gray-500 cursor-not-allowed" : ""
                    )}
                    value={draft.price_term ?? ""}
                    onChange={(e) =>
                      setDraft({
                        ...draft,
                        price_term: e.target.value
                          ? (e.target.value as BOQItem["price_term"])
                          : null,
                      })
                    }
                    disabled={!!draft.product_id} // FREEZE when product picked
                    title={
                      draft.product_id
                        ? "Derived from Price Book (change by editing Price Book)"
                        : "Select price term"
                    }
                  >
                    <option value="" disabled>
                      {draft.product_id ? "— derived —" : "Select…"}
                    </option>
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
                    title={draft.unit}
                  />
                </td>

                <td className="px-3 py-2">
                  <NumberInput
                    value={num(draft.quantity)}
                    onChange={(n) => setDraft({ ...draft, quantity: n })}
                    min={0}
                    placeholder="0"
                    title={String(draft.quantity ?? 0)}
                  />
                </td>

                <td className="px-3 py-2">
                  <NumberInput
                    value={num(draft.unit_price)}
                    onChange={(n) => setDraft({ ...draft, unit_price: n })}
                    min={0}
                    placeholder="0.00"
                    title={String(draft.unit_price ?? 0)}
                  />
                </td>

                <td className="px-3 py-2">
                  <NumberInput
                    value={num(draft.unit_cogs ?? 0)}
                    onChange={(n) => setDraft({ ...draft, unit_cogs: n })}
                    min={0}
                    placeholder="0.00"
                    title={String(draft.unit_cogs ?? 0)}
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
                      if (next.product_id) {
                        try {
                          const { on } = singleMonthWindow(next);
                          const price = await fetchBestPrice(next.product_id!, on);
                          next.unit_price = Number(price.unit_price);
                          if (price.price_term) next.price_term = price.price_term;
                        } catch {}
                      }
                      setDraft(next);
                    }}
                  />
                </td>

                <td className="px-3 py-2">
                  <NumberInput
                    value={draft.months ?? ""}
                    onChange={(n) => setDraft({ ...draft, months: Number.isFinite(n) ? n : null })}
                    min={0}
                    placeholder="months"
                    title={String(draft.months ?? "")}
                  />
                </td>

                <td className="px-3 py-2 text-center">
                  <input
                    type="checkbox"
                    checked={!!draft.is_active}
                    onChange={(e) => setDraft({ ...draft, is_active: e.target.checked })}
                  />
                </td>

                <td className="px-3 py-2">
                  <div className="flex gap-2">
                    <button
                      onClick={async () => {
                        try {
                          const created = await apiPost<BOQItem>(`/scenarios/${scenarioId}/boq`, {
                            ...draft,
                            quantity: num(draft.quantity),
                            unit_price: num(draft.unit_price),
                            unit_cogs: draft.unit_cogs == null ? null : num(draft.unit_cogs),
                            months: draft.months == null ? null : num(draft.months),
                          });
                          const createdNorm: BOQItem = {
                            ...created,
                            price_term:
                              (created as any).price_term ?? (created as any).price_terms ?? null,
                          };
                          setRows((p) => [...p, createdNorm]);

                          // hydrate product cache & persist family selection for the new row
                          if (created.product_id && !(created.product_id in productCache)) {
                            try {
                              const p = await apiGet<Product>(`/api/products/${created.product_id}`);
                              setProductCache((prev) => ({ ...prev, [p.id]: p }));
                              if (createdNorm.id != null) {
                                setRowFamilyId((prev) => ({
                                  ...prev,
                                  [createdNorm.id!]: p.product_family_id ?? draftFamilyId ?? "",
                                }));
                              }
                            } catch {
                              if (createdNorm.id != null && draftFamilyId !== "") {
                                setRowFamilyId((prev) => ({ ...prev, [createdNorm.id!]: draftFamilyId }));
                              }
                            }
                          } else if (createdNorm.id != null && draftFamilyId !== "") {
                            setRowFamilyId((prev) => ({ ...prev, [createdNorm.id!]: draftFamilyId }));
                          }

                          setDraft(null);
                          setDraftFamilyId("");
                          onChanged?.();
                        } catch (e: any) {
                          alert(e?.response?.data?.detail || e?.message || "Save failed.");
                        }
                      }}
                      className="px-2 py-1 rounded border hover:bg-gray-50 text-sm"
                    >
                      Save
                    </button>
                    <button
                      onClick={() => {
                        setDraft(null);
                        setDraftFamilyId("");
                      }}
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
              const linkedProd = productOf(r.product_id ?? undefined);
              const famValue = getFamilyValueForRow(r);

              return (
                <tr key={r.id} className="odd:bg-white even:bg-gray-50">
                  {/* Family */}
                  <td className="px-3 py-2">
                    <FamilySelect
                      value={famValue}
                      families={families}
                      onChange={(nextId) => {
                        if (r.id != null) {
                          setRowFamilyId((prev) => ({ ...prev, [r.id!]: nextId }));
                        }
                        // clear product & price term when family changes (unfreeze)
                        setRows((p) =>
                          p.map((x) =>
                            x.id === r.id
                              ? { ...x, product_id: null, item_name: "", unit: "", price_term: null }
                              : x
                          )
                        );
                      }}
                    />
                  </td>

                  {/* Product */}
                  <td className="px-3 py-2">
                    <ProductAutocomplete
                      familyId={famValue}
                      disabled={!famValue}
                      value={r.item_name}
                      onChangeText={(t) =>
                        setRows((p) => p.map((x) => (x.id === r.id ? { ...x, item_name: t } : x)))
                      }
                      onPick={(p) => applyProductToRow(r.id!, p)}
                      placeholder="Search code or name…"
                    />
                    {!!r.product_id && (
                      <div className="text-xs text-gray-500 mt-1">
                        linked:{" "}
                        <b title={linkedProd?.code || `#${r.product_id}`}>
                          {linkedProd?.code || `#${r.product_id}`}
                        </b>{" "}
                        • <span title={linkedProd?.name || ""}>{linkedProd?.name || ""}</span>
                      </div>
                    )}
                  </td>

                  {/* Price Term (FREEZE when product linked) */}
                  <td className="px-3 py-2">
                    <select
                      className={cls(
                        "w-full px-2 py-1 rounded border border-gray-300",
                        r.product_id ? "bg-gray-100 text-gray-500 cursor-not-allowed" : ""
                      )}
                      value={r.price_term ?? ""}
                      onChange={(e) =>
                        setRows((p) =>
                          p.map((x) =>
                            x.id === r.id
                              ? {
                                  ...x,
                                  price_term: e.target.value
                                    ? (e.target.value as BOQItem["price_term"])
                                    : null,
                                }
                              : x
                          )
                        )
                      }
                      disabled={!!r.product_id}
                      title={
                        r.product_id
                          ? "Derived from Price Book (change by editing Price Book)"
                          : "Select price term"
                      }
                    >
                      <option value="" disabled>
                        {r.product_id ? "— derived —" : "Select…"}
                      </option>
                      {PRICE_TERMS_OPTIONS.map((c) => (
                        <option key={c} value={c}>
                          {c}
                        </option>
                      ))}
                    </select>
                  </td>

                  {/* UOM */}
                  <td className="px-3 py-2">
                    <input
                      className="w-full px-2 py-1 rounded border border-gray-300"
                      value={r.unit}
                      onChange={() => {}}
                      readOnly
                      title={r.unit}
                    />
                  </td>

                  <td className="px-3 py-2">
                    <NumberInput
                      value={num(r.quantity)}
                      onChange={(n) =>
                        setRows((p) => p.map((x) => (x.id === r.id ? { ...x, quantity: n } : x)))
                      }
                      min={0}
                      placeholder="0"
                      title={String(r.quantity ?? 0)}
                    />
                  </td>

                  <td className="px-3 py-2">
                    <NumberInput
                      value={num(r.unit_price)}
                      onChange={(n) =>
                        setRows((p) => p.map((x) => (x.id === r.id ? { ...x, unit_price: n } : x)))
                      }
                      min={0}
                      placeholder="0.00"
                      title={String(r.unit_price ?? 0)}
                    />
                  </td>

                  <td className="px-3 py-2">
                    <NumberInput
                      value={num(r.unit_cogs ?? 0)}
                      onChange={(n) =>
                        setRows((p) => p.map((x) => (x.id === r.id ? { ...x, unit_cogs: n } : x)))
                      }
                      min={0}
                      placeholder="0.00"
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
                              ? { ...x, frequency: e.target.value as BOQItem["frequency"] }
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

                  {/* Start (Y/M) */}
                  <td className="px-3 py-2">
                    <MonthInput
                      value={{ year: r.start_year ?? null, month: r.start_month ?? null }}
                      onChange={async ({ year, month }) => {
                        setRows((p) =>
                          p.map((x) =>
                            x.id === r.id ? { ...x, start_year: year, start_month: month } : x
                          )
                        );
                        if (r.product_id) await refreshBestPriceForRow(r.id!);
                      }}
                    />
                  </td>

                  <td className="px-3 py-2">
                    <NumberInput
                      value={r.months ?? ""}
                      onChange={(n) =>
                        setRows((p) =>
                          p.map((x) =>
                            x.id === r.id ? { ...x, months: Number.isFinite(n) ? n : null } : x
                          )
                        )
                      }
                      min={0}
                      placeholder="months"
                      title={String(r.months ?? "")}
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

                  <td className="px-3 py-2">
                    <div className="flex flex-wrap gap-2">
                      <button
                        onClick={async () => {
                          if (!r.id) return;
                          try {
                            const upd = await apiPut<BOQItem>(`/scenarios/${scenarioId}/boq/${r.id}`, {
                              ...r,
                              quantity: num(r.quantity),
                              unit_price: num(r.unit_price),
                              unit_cogs: r.unit_cogs == null ? null : num(r.unit_cogs),
                              months: r.months == null ? null : num(r.months),
                            });
                            const updNorm: BOQItem = {
                              ...upd,
                              price_term:
                                (upd as any).price_term ?? (upd as any).price_terms ?? null,
                            };
                            setRows((p) => p.map((x) => (x.id === r.id ? updNorm : x)));

                            // keep existing rowFamilyId as-is (user choice persists)
                            onChanged?.();
                          } catch (e: any) {
                            alert(e?.response?.data?.detail || e?.message || "Update failed.");
                          }
                        }}
                        className="px-2 py-1 rounded border hover:bg-gray-50 text-sm"
                      >
                        Save
                      </button>
                      <button
                        onClick={async () => {
                          if (!r.id) return;
                          if (!confirm("Delete BOQ item?")) return;
                          try {
                            await apiDelete(`/scenarios/${scenarioId}/boq/${r.id}`);
                            setRows((p) => p.filter((x) => x.id !== r.id));
                            onChanged?.();
                          } catch (e: any) {
                            alert(e?.response?.data?.detail || e?.message || "Delete failed.");
                          }
                        }}
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
        </table>
      </div>

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
