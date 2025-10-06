// src/components/BOQTable.tsx
import { useEffect, useMemo, useRef, useState } from "react";
import {
  ScenarioDetail,
  ScenarioBOQItem,
  BOQFrequency,
  BOQCategory,
  BOQ_CATEGORIES,
  BOQ_CATEGORY_LABELS,
} from "../types/scenario";
import { Card } from "./ui";
import { fmt } from "../utils/format";
import { apiPost, apiPatch, apiDelete, ApiError, apiGet } from "../lib/api";

/* ------------------------ Small UI helpers ------------------------ */
function pad2(n: number) {
  return String(n).padStart(2, "0");
}
function nowYM() {
  const d = new Date();
  return `${d.getFullYear()}-${pad2(d.getMonth() + 1)}`;
}
function toISODateYYYYMM01(y?: string, m?: string) {
  if (!y || !m) return null;
  const yi = Number(y),
    mi = Number(m);
  if (!Number.isFinite(yi) || !Number.isFinite(mi) || mi < 1 || mi > 12) return null;
  return `${yi}-${pad2(mi)}-01`;
}

function MonthInput({
  value,
  onChange,
  className,
}: {
  value?: string | null; // "YYYY-MM"
  onChange: (next: string | null) => void;
  className?: string;
}) {
  return (
    <input
      type="month"
      value={value ?? ""}
      onChange={(e) => onChange(e.target.value || null)}
      className={`px-3 py-2 rounded-lg border w-40 ${className ?? ""}`}
    />
  );
}

/* ----------------------------- Types ----------------------------- */
type RowDraft = {
  id?: number;
  section?: string | null;
  category?: BOQCategory | null;
  /** Link to Products table (optional) */
  product_id?: number | null;
  item_name: string;
  unit: string;
  quantity: string;
  unit_price: string;
  unit_cogs: string;
  frequency: BOQFrequency;
  months?: string;
  start_year?: string;
  start_month?: string;
  is_active: boolean;
  notes?: string;
};

type ProductFamily = { id: number; name: string };
type ProductLite = { id: number; name: string; uom?: string | null };

type BestPriceResp = {
  product_id: number;
  price_book_id: number;
  price_book_entry_id: number;
  unit_price: number;
  currency?: string | null;
  valid_from?: string | null;
  valid_to?: string | null;
  price_terms?: "bulk_with_freight" | "bulk_ex_freight" | "freight" | null;
};

type PricePreviewResp = {
  id: number;
  scenario_id: number;
  name: string;
  period: string; // "YYYY-MM"
  currency: string;
  unit_price: string;
  quantity: string;
  line_total: string;
  source: "formulation" | "product_price_book" | "boq_unit_price";
  // only present for formulation
  base_price?: string;
  factor?: string;
};

/* ----------------------- Transform helpers ----------------------- */
function toDraft(it?: ScenarioBOQItem): RowDraft {
  return {
    id: it?.id,
    section: it?.section ?? "",
    category: (it?.category as BOQCategory | undefined) ?? "bulk_ex_freight",
    product_id: (it as any)?.product_id ?? null,
    item_name: it?.item_name ?? "",
    unit: it?.unit ?? "",
    quantity: String(it?.quantity ?? 0),
    unit_price: String(it?.unit_price ?? 0),
    unit_cogs: String(it?.unit_cogs ?? 0),
    frequency: (it?.frequency ?? "once") as BOQFrequency,
    months: it?.months ? String(it.months) : "",
    start_year: it?.start_year ? String(it.start_year) : "",
    start_month: it?.start_month ? String(it.start_month) : "",
    is_active: it?.is_active ?? true,
    notes: it?.notes ?? "",
  };
}

function toPayload(d: RowDraft): Omit<ScenarioBOQItem, "id"> & { product_id?: number | null } {
  const unitCogs = d.unit_cogs === "" || d.unit_cogs == null ? null : Number(d.unit_cogs || 0);
  return {
    section: d.section || null,
    category: d.category ?? "bulk_ex_freight",
    item_name: d.item_name.trim(),
    unit: d.unit.trim(),
    quantity: Number(d.quantity || 0),
    unit_price: Number(d.unit_price || 0),
    unit_cogs: unitCogs as any,
    frequency: d.frequency,
    months: d.months ? Number(d.months) : undefined,
    start_year: d.start_year ? Number(d.start_year) : undefined,
    start_month: d.start_month ? Number(d.start_month) : undefined,
    is_active: !!d.is_active,
    notes: d.notes || null,
    product_id: d.product_id ?? null,
  };
}

function lineTotals(it: ScenarioBOQItem) {
  const mult = it.frequency === "monthly" && it.months ? it.months : 1;
  const revenue = (it.quantity ?? 0) * (it.unit_price ?? 0) * mult;
  const cogs = (it.quantity ?? 0) * (it.unit_cogs ?? 0) * mult;
  return { revenue, cogs, gm: revenue - cogs };
}

/* -------------------------- API helpers -------------------------- */
async function fetchBestPrice(productId: number, startISO?: string | null, endISO?: string | null) {
  if (startISO && endISO) {
    const q = new URLSearchParams();
    q.set("start", startISO);
    q.set("end", endISO);
    return apiGet<BestPriceResp>(`/api/products/${productId}/best-price?${q.toString()}`);
  }
  return apiGet<BestPriceResp>(`/api/products/${productId}/best-price`);
}

/* ---------------- Product chooser (PriceBooks-like) --------------- */
function useDebounced<T extends (...args: any[]) => void>(fn: T, ms = 300) {
  const timer = useRef<number | null>(null);
  return (...args: Parameters<T>) => {
    if (timer.current) window.clearTimeout(timer.current);
    timer.current = window.setTimeout(() => fn(...args), ms);
  };
}

function ProductChooser({
  familyId,
  onFamilyChange,
  onPick,
}: {
  familyId: number | "" | undefined;
  onFamilyChange: (id: number | "") => void;
  onPick: (p: ProductLite) => void;
}) {
  const [families, setFamilies] = useState<ProductFamily[]>([]);
  const [q, setQ] = useState("");
  const [items, setItems] = useState<ProductLite[]>([]);
  const [open, setOpen] = useState(false);
  const [focused, setFocused] = useState(false);
  const [loading, setLoading] = useState(false);
  const [activeIdx, setActiveIdx] = useState<number>(-1);
  const inputRef = useRef<HTMLInputElement | null>(null);

  // Load families once
  useEffect(() => {
    (async () => {
      try {
        const res = await apiGet<any>(`/api/product-families`);
        const arr: any[] = Array.isArray((res as any)?.items) ? (res as any).items : Array.isArray(res) ? res : [];
        setFamilies(arr as ProductFamily[]);
      } catch {
        setFamilies([]);
      }
    })();
  }, []);

  const search = async (term: string) => {
    if (!familyId || !focused) {
      setItems([]);
      setOpen(false);
      return;
    }
    setLoading(true);
    try {
      const params = new URLSearchParams();
      params.set("limit", "10");
      params.set("q", term || "");
      params.set("family_id", String(familyId));
      const res = await apiGet<any>(`/api/products?${params.toString()}`);
      const list: any[] = Array.isArray((res as any)?.items) ? (res as any).items : Array.isArray(res) ? res : [];
      setItems(list as ProductLite[]);
      setOpen(true);
    } finally {
      setLoading(false);
    }
  };

  const debounced = useDebounced(search, 250);

  return (
    <div className="relative flex items-center gap-2">
      <select
        value={familyId === "" ? "" : String(familyId ?? "")}
        onChange={(e) => onFamilyChange(e.target.value === "" ? "" : Number(e.target.value))}
        className="min-w-[10rem] px-3 py-2 rounded-lg border text-sm"
      >
        <option value="">All</option>
        {families.map((f) => (
          <option key={f.id} value={f.id}>
            {f.name}
          </option>
        ))}
      </select>

      <input
        ref={inputRef}
        placeholder="Product"
        value={q}
        onChange={(e) => {
          const val = e.target.value;
          setQ(val);
          debounced(val);
        }}
        onFocus={() => {
          setFocused(true);
          debounced(q);
        }}
        onBlur={() => {
          // slight delay so click can register
          setTimeout(() => {
            setFocused(false);
            setOpen(false);
          }, 120);
        }}
        onKeyDown={(e) => {
          if (!open || items.length === 0) return;
          if (e.key === "ArrowDown") {
            e.preventDefault();
            setActiveIdx((i) => (i + 1) % items.length);
          } else if (e.key === "ArrowUp") {
            e.preventDefault();
            setActiveIdx((i) => (i - 1 + items.length) % items.length);
          } else if (e.key === "Enter") {
            e.preventDefault();
            const pick = items[activeIdx] ?? items[0];
            if (pick) onPick(pick);
            setOpen(false);
            setQ("");
          }
        }}
        className="min-w-[16rem] px-3 py-2 rounded-lg border"
      />

      <button
        type="button"
        title="Select"
        onMouseDown={(e) => e.preventDefault()}
        onClick={() => {
          // open list if not open and there's a family
          if (!open) {
            setFocused(true);
            debounced(q);
            inputRef.current?.focus();
          }
        }}
        className="px-2.5 py-1.5 rounded-lg border hover:bg-gray-50"
      >
        Select
      </button>

      {open && items.length > 0 && (
        <div className="absolute left-[10rem] top-full mt-1 w-[28rem] rounded-lg border bg-white shadow-lg z-20 text-sm">
          <div className="max-h-72 overflow-y-auto">
            {items.map((p, i) => (
              <button
                key={p.id}
                onMouseDown={(e) => e.preventDefault()}
                onClick={() => {
                  onPick(p);
                  setOpen(false);
                  setQ("");
                  setActiveIdx(-1);
                }}
                className={`w-full text-left px-3 py-2 hover:bg-gray-50 ${
                  i === activeIdx ? "bg-indigo-50" : ""
                }`}
              >
                <div className="font-medium">{p.name}</div>
                <div className="text-xs text-gray-500">#{p.id}{p.uom ? ` • ${p.uom}` : ""}</div>
              </button>
            ))}
          </div>
          {loading ? (
            <div className="px-3 py-2 text-xs text-amber-700 bg-amber-50 border-t">Loading…</div>
          ) : null}
        </div>
      )}
    </div>
  );
}

/* ------------------------------- UI ------------------------------- */
export default function BOQTable({
  data,
  refresh,
}: {
  data: ScenarioDetail;
  refresh: () => void;
}) {
  const items: ScenarioBOQItem[] = data.boq_items ?? [];

  const [adding, setAdding] = useState(false);
  const [draft, setDraft] = useState<RowDraft | null>(null);
  const [editingId, setEditingId] = useState<number | null>(null);

  // Family seeds per-row (so chooser opens filtered like PriceBooks)
  const [draftFamilyId, setDraftFamilyId] = useState<number | "">("");
  const [rowFamilyId, setRowFamilyId] = useState<Record<number, number | "">>({});

  // Price preview popover state
  const [previewFor, setPreviewFor] = useState<number | null>(null);
  const [previewYM, setPreviewYM] = useState<string>(nowYM());
  const [previewBusy, setPreviewBusy] = useState<boolean>(false);
  const [previewErr, setPreviewErr] = useState<string | null>(null);
  const [previewData, setPreviewData] = useState<PricePreviewResp | null>(null);

  function ymFromRow(it: ScenarioBOQItem): string {
    if (it.start_year && it.start_month) return `${it.start_year}-${pad2(it.start_month)}`;
    return nowYM();
  }

  const totals = useMemo(() => {
    const t = { revenue: 0, cogs: 0, gm: 0 };
    for (const it of items) {
      const x = lineTotals(it);
      t.revenue += x.revenue;
      t.cogs += x.cogs;
      t.gm += x.gm;
    }
    return t;
  }, [items]);

  const beginAdd = () => {
    setDraft(
      toDraft({
        item_name: "",
        unit: "",
        quantity: 0,
        unit_price: 0,
        unit_cogs: 0,
        frequency: "once",
        is_active: true,
        category: "bulk_ex_freight",
      } as any)
    );
    setDraftFamilyId("");
    setAdding(true);
  };

  const beginEdit = (it: ScenarioBOQItem) => {
    setEditingId(it.id);
    setDraft(toDraft(it));
    setRowFamilyId((p) => ({ ...p, [it.id]: p[it.id] ?? "" }));
  };

  const cancelEdit = () => {
    setAdding(false);
    setEditingId(null);
    setDraft(null);
    setDraftFamilyId("");
    setPreviewFor(null);
    setPreviewData(null);
    setPreviewErr(null);
  };

  const saveAdd = async () => {
    if (!draft) return;
    const payload = toPayload(draft);
    if (!payload.item_name) {
      alert("Item name gerekli.");
      return;
    }
    try {
      await apiPost(`/business-cases/scenarios/${data.id}/boq-items`, payload);
      cancelEdit();
      await refresh();
    } catch (e: any) {
      alert(
        (e instanceof ApiError && e.message) ||
          e?.response?.data?.detail ||
          e?.message ||
          "Create failed"
      );
    }
  };

  const saveEdit = async () => {
    if (!draft || !editingId) return;
    const payload = toPayload(draft);
    if (!payload.item_name) {
      alert("Item name gerekli.");
      return;
    }
    try {
      await apiPatch(`/business-cases/scenarios/boq-items/${editingId}`, payload);
      cancelEdit();
      await refresh();
    } catch (e: any) {
      alert(
        (e instanceof ApiError && e.message) ||
          e?.response?.data?.detail ||
          e?.message ||
          "Update failed"
      );
    }
  };

  const onDelete = async (it: ScenarioBOQItem) => {
    if (!confirm(`Delete BOQ item "${it.item_name}"?`)) return;
    try {
      await apiDelete(`/business-cases/scenarios/boq-items/${it.id}`);
      await refresh();
    } catch (e: any) {
      alert(
        (e instanceof ApiError && e.message) ||
          e?.response?.data?.detail ||
          e?.message ||
          "Delete failed"
      );
    }
  };

  // When start (Y/M) changes and a product is linked, try auto-price
  async function maybeAutoPrice(next: RowDraft) {
    if (!next.product_id) return next;
    try {
      const iso = toISODateYYYYMM01(next.start_year, next.start_month);
      const price = await fetchBestPrice(next.product_id, iso, iso);
      return { ...next, unit_price: String(price.unit_price ?? Number(next.unit_price || 0)) };
    } catch {
      return next; // silent – user can type price manually
    }
  }

  /* ---------------------- Price Preview logic --------------------- */
  async function openPreviewFor(row: ScenarioBOQItem) {
    if (!row.id) return;
    const defYM = ymFromRow(row);
    setPreviewYM(defYM);
    setPreviewFor(row.id);
    setPreviewErr(null);
    setPreviewBusy(true);
    setPreviewData(null);
    try {
      const url = `/api/boq/scenarios/${data.id}/boq/${row.id}/price-preview?ym=${defYM}`;
      const resp = await apiGet<PricePreviewResp>(url);
      setPreviewData(resp);
    } catch (e: any) {
      setPreviewErr(e?.response?.data?.detail || e?.message || "Preview failed.");
    } finally {
      setPreviewBusy(false);
    }
  }

  async function reloadPreview(rowId: number, ym: string) {
    setPreviewBusy(true);
    setPreviewErr(null);
    try {
      const url = `/api/boq/scenarios/${data.id}/boq/${rowId}/price-preview?ym=${ym}`;
      const resp = await apiGet<PricePreviewResp>(url);
      setPreviewData(resp);
    } catch (e: any) {
      setPreviewErr(e?.response?.data?.detail || e?.message || "Preview failed.");
    } finally {
      setPreviewBusy(false);
    }
  }

  async function applyPreviewUnitPrice(row: ScenarioBOQItem) {
    if (!previewData) return;
    const newPrice = Number(previewData.unit_price);
    if (editingId === row.id && draft) {
      setDraft({ ...draft, unit_price: String(newPrice) });
      return;
    }
    try {
      await apiPatch(`/business-cases/scenarios/boq-items/${row.id}`, {
        unit_price: newPrice,
      } as any);
      await refresh();
    } catch (e: any) {
      alert(e?.response?.data?.detail || e?.message || "Failed to apply preview price.");
    }
  }

  // Close preview when items change (e.g., after refresh)
  useEffect(() => {
    if (previewFor && !items.find((x) => x.id === previewFor)) {
      setPreviewFor(null);
      setPreviewData(null);
      setPreviewErr(null);
    }
  }, [items, previewFor]);

  /* ----------------------------- Render ---------------------------- */
  return (
    <Card>
      <div className="flex items-center justify-between mb-3">
        <div className="text-sm font-medium">BOQ (Bill of Quantities)</div>
        <button className="px-3 py-1.5 rounded-md border text-sm hover:bg-gray-50" onClick={beginAdd}>
          + Add BOQ Item
        </button>
      </div>

      <div className="overflow-x-auto">
        <table className="min-w-full text-sm">
          <thead>
            <tr className="border-b bg-gray-50">
              <th className="py-2 px-3 text-left">Section</th>
              <th className="py-2 px-3 text-left">Category</th>
              <th className="py-2 px-3 text-left">Family / Product</th>
              <th className="py-2 px-3 text-left">Unit</th>
              <th className="py-2 px-3 text-right">Qty</th>
              <th className="py-2 px-3 text-right">Unit Price</th>
              <th className="py-2 px-3 text-right">Unit COGS</th>
              <th className="py-2 px-3 text-left">Freq</th>
              <th className="py-2 px-3 text-right">Months</th>
              <th className="py-2 px-3 text-right">Start (Y/M)</th>
              <th className="py-2 px-3 text-center">Active</th>
              <th className="py-2 px-3 text-right">Line Rev</th>
              <th className="py-2 px-3 text-right">Line COGS</th>
              <th className="py-2 px-3 text-right">Line GM</th>
              <th className="py-2 px-3 text-right w-60">Actions</th>
            </tr>
          </thead>

          <tbody>
            {/* ----------------------- DRAFT ROW ----------------------- */}
            {adding && draft && (
              <tr className="border-b bg-amber-50/30">
                <td className="py-2 px-3">
                  <input
                    value={draft.section ?? ""}
                    onChange={(e) => setDraft({ ...draft, section: e.target.value })}
                    className="w-40 px-3 py-2 rounded-lg border"
                  />
                </td>

                <td className="py-2 px-3">
                  <select
                    value={(draft.category ?? "bulk_ex_freight") as BOQCategory}
                    onChange={(e) => setDraft({ ...draft, category: e.target.value as BOQCategory })}
                    className="min-w-[12rem] px-3 py-2 rounded-lg border text-sm"
                  >
                    {BOQ_CATEGORIES.map((cat) => (
                      <option key={cat} value={cat}>
                        {BOQ_CATEGORY_LABELS[cat]}
                      </option>
                    ))}
                  </select>
                </td>

                <td className="py-2 px-3">
                  <div className="flex flex-col gap-1">
                    <ProductChooser
                      familyId={draftFamilyId}
                      onFamilyChange={setDraftFamilyId}
                      onPick={async (p) => {
                        let next: RowDraft = {
                          ...draft,
                          product_id: p.id,
                          item_name: p.name || draft.item_name,
                          unit: p.uom || draft.unit,
                        };
                        try {
                          const iso = toISODateYYYYMM01(next.start_year, next.start_month);
                          const price = await fetchBestPrice(p.id, iso, iso);
                          next.unit_price = String(price.unit_price ?? Number(next.unit_price || 0));
                        } catch {}
                        setDraft(next);
                      }}
                    />
                    {draft.product_id ? (
                      <div className="text-[11px] text-gray-500">linked product: #{draft.product_id}</div>
                    ) : null}
                  </div>
                </td>

                <td className="py-2 px-3">
                  <input
                    value={draft.unit}
                    onChange={(e) => setDraft({ ...draft, unit: e.target.value })}
                    className="w-28 px-3 py-2 rounded-lg border"
                    placeholder="UOM"
                  />
                </td>

                <td className="py-2 px-3 text-right">
                  <input
                    type="number"
                    step="any"
                    min="0"
                    value={draft.quantity}
                    onChange={(e) => setDraft({ ...draft, quantity: e.target.value })}
                    className="w-32 px-3 py-2 rounded-lg border text-right"
                    placeholder="0"
                  />
                </td>

                <td className="py-2 px-3 text-right">
                  <input
                    type="number"
                    step="any"
                    min="0"
                    value={draft.unit_price}
                    onChange={(e) => setDraft({ ...draft, unit_price: e.target.value })}
                    className="w-36 px-3 py-2 rounded-lg border text-right"
                    placeholder="0.00"
                  />
                </td>

                <td className="py-2 px-3 text-right">
                  <input
                    type="number"
                    step="any"
                    min="0"
                    value={draft.unit_cogs}
                    onChange={(e) => setDraft({ ...draft, unit_cogs: e.target.value })}
                    className="w-36 px-3 py-2 rounded-lg border text-right"
                    placeholder="0.00"
                  />
                </td>

                <td className="py-2 px-3">
                  <select
                    value={draft.frequency}
                    onChange={(e) => setDraft({ ...draft, frequency: e.target.value as BOQFrequency })}
                    className="px-3 py-2 rounded-lg border w-36"
                  >
                    <option value="once">once</option>
                    <option value="monthly">monthly</option>
                    <option value="per_shipment">per_shipment</option>
                    <option value="per_tonne">per_tonne</option>
                  </select>
                </td>

                <td className="py-2 px-3 text-right">
                  <input
                    type="number"
                    min="0"
                    value={draft.months ?? ""}
                    onChange={(e) => setDraft({ ...draft, months: e.target.value })}
                    className="w-28 px-3 py-2 rounded-lg border text-right"
                    placeholder="months"
                  />
                </td>

                <td className="py-2 px-3">
                  <div className="flex items-center gap-2 justify-end">
                    <input
                      placeholder="YYYY"
                      type="number"
                      value={draft.start_year ?? ""}
                      onChange={async (e) => {
                        const next = { ...draft, start_year: e.target.value };
                        setDraft(await maybeAutoPrice(next));
                      }}
                      className="w-28 px-3 py-2 rounded-lg border text-right"
                    />
                    <input
                      placeholder="MM"
                      type="number"
                      value={draft.start_month ?? ""}
                      onChange={async (e) => {
                        const next = { ...draft, start_month: e.target.value };
                        setDraft(await maybeAutoPrice(next));
                      }}
                      className="w-20 px-3 py-2 rounded-lg border text-right"
                    />
                  </div>
                </td>

                <td className="py-2 px-3 text-center">
                  <input
                    type="checkbox"
                    checked={draft.is_active}
                    onChange={(e) => setDraft({ ...draft, is_active: e.target.checked })}
                  />
                </td>

                <td className="py-2 px-3 text-right">
                  {fmt(
                    Number(draft.quantity || 0) *
                      Number(draft.unit_price || 0) *
                      (draft.frequency === "monthly" && Number(draft.months || 0) > 0 ? Number(draft.months) : 1)
                  )}
                </td>
                <td className="py-2 px-3 text-right">
                  {fmt(
                    Number(draft.quantity || 0) *
                      Number(draft.unit_cogs || 0) *
                      (draft.frequency === "monthly" && Number(draft.months || 0) > 0 ? Number(draft.months) : 1)
                  )}
                </td>
                <td className="py-2 px-3 text-right">
                  {fmt(
                    Number(draft.quantity || 0) *
                      (Number(draft.unit_price || 0) - Number(draft.unit_cogs || 0)) *
                      (draft.frequency === "monthly" && Number(draft.months || 0) > 0 ? Number(draft.months) : 1)
                  )}
                </td>

                <td className="py-2 px-3">
                  <div className="flex justify-end gap-2">
                    <button onClick={saveAdd} className="px-3 py-1.5 rounded border hover:bg-gray-50">
                      Save
                    </button>
                    <button onClick={cancelEdit} className="px-3 py-1.5 rounded border hover:bg-gray-50">
                      Cancel
                    </button>
                  </div>
                </td>
              </tr>
            )}

            {/* --------------------- EMPTY STATE ---------------------- */}
            {items.length === 0 && !adding && (
              <tr>
                <td colSpan={15} className="py-4 text-gray-500">
                  No BOQ items.
                </td>
              </tr>
            )}

            {/* --------------------- EXISTING ROWS -------------------- */}
            {items.map((it) => {
              const editing = Boolean(editingId === it.id && draft);
              const lt = lineTotals(it);

              if (editing) {
                const d = draft as RowDraft;
                return (
                  <tr key={it.id} className="border-b bg-amber-50/30 relative">
                    <td className="py-2 px-3">
                      <input
                        value={d.section ?? ""}
                        onChange={(e) => setDraft({ ...d, section: e.target.value })}
                        className="w-40 px-3 py-2 rounded-lg border"
                      />
                    </td>

                    <td className="py-2 px-3">
                      <select
                        value={(d.category ?? "bulk_ex_freight") as BOQCategory}
                        onChange={(e) => setDraft({ ...d, category: e.target.value as BOQCategory })}
                        className="min-w-[12rem] px-3 py-2 rounded-lg border text-sm"
                      >
                        {BOQ_CATEGORIES.map((cat) => (
                          <option key={cat} value={cat}>
                            {BOQ_CATEGORY_LABELS[cat]}
                          </option>
                        ))}
                      </select>
                    </td>

                    <td className="py-2 px-3">
                      <div className="flex flex-col gap-1">
                        <ProductChooser
                          familyId={rowFamilyId[it.id!] ?? ""}
                          onFamilyChange={(id) =>
                            setRowFamilyId((p) => ({
                              ...p,
                              [it.id!]: id,
                            }))
                          }
                          onPick={async (p) => {
                            let next: RowDraft = {
                              ...d,
                              product_id: p.id,
                              item_name: p.name || d.item_name,
                              unit: p.uom || d.unit,
                            };
                            try {
                              const iso = toISODateYYYYMM01(next.start_year, next.start_month);
                              const price = await fetchBestPrice(p.id, iso, iso);
                              next.unit_price = String(price.unit_price ?? Number(next.unit_price || 0));
                            } catch {}
                            setDraft(next);
                          }}
                        />
                        {d.product_id ? (
                          <div className="text-[11px] text-gray-500">linked: #{d.product_id}</div>
                        ) : null}
                      </div>
                    </td>

                    <td className="py-2 px-3">
                      <input
                        value={d.unit}
                        onChange={(e) => setDraft({ ...d, unit: e.target.value })}
                        className="w-28 px-3 py-2 rounded-lg border"
                        placeholder="UOM"
                      />
                    </td>

                    <td className="py-2 px-3 text-right">
                      <input
                        type="number"
                        step="any"
                        min="0"
                        value={d.quantity}
                        onChange={(e) => setDraft({ ...d, quantity: e.target.value })}
                        className="w-32 px-3 py-2 rounded-lg border text-right"
                        placeholder="0"
                      />
                    </td>

                    <td className="py-2 px-3 text-right">
                      <input
                        type="number"
                        step="any"
                        min="0"
                        value={d.unit_price}
                        onChange={(e) => setDraft({ ...d, unit_price: e.target.value })}
                        className="w-36 px-3 py-2 rounded-lg border text-right"
                        placeholder="0.00"
                      />
                    </td>

                    <td className="py-2 px-3 text-right">
                      <input
                        type="number"
                        step="any"
                        min="0"
                        value={d.unit_cogs}
                        onChange={(e) => setDraft({ ...d, unit_cogs: e.target.value })}
                        className="w-36 px-3 py-2 rounded-lg border text-right"
                        placeholder="0.00"
                      />
                    </td>

                    <td className="py-2 px-3">
                      <select
                        value={d.frequency}
                        onChange={(e) => setDraft({ ...d, frequency: e.target.value as BOQFrequency })}
                        className="px-3 py-2 rounded-lg border w-36"
                      >
                        <option value="once">once</option>
                        <option value="monthly">monthly</option>
                        <option value="per_shipment">per_shipment</option>
                        <option value="per_tonne">per_tonne</option>
                      </select>
                    </td>

                    <td className="py-2 px-3 text-right">
                      <input
                        type="number"
                        min="0"
                        value={d.months ?? ""}
                        onChange={(e) => setDraft({ ...d, months: e.target.value })}
                        className="w-28 px-3 py-2 rounded-lg border text-right"
                        placeholder="months"
                      />
                    </td>

                    <td className="py-2 px-3">
                      <div className="flex items-center gap-2 justify-end">
                        <input
                          placeholder="YYYY"
                          type="number"
                          value={d.start_year ?? ""}
                          onChange={async (e) => {
                            const next = { ...d, start_year: e.target.value };
                            setDraft(await maybeAutoPrice(next));
                          }}
                          className="w-28 px-3 py-2 rounded-lg border text-right"
                        />
                        <input
                          placeholder="MM"
                          type="number"
                          value={d.start_month ?? ""}
                          onChange={async (e) => {
                            const next = { ...d, start_month: e.target.value };
                            setDraft(await maybeAutoPrice(next));
                          }}
                          className="w-20 px-3 py-2 rounded-lg border text-right"
                        />
                      </div>
                    </td>

                    <td className="py-2 px-3 text-center">
                      <input
                        type="checkbox"
                        checked={d.is_active}
                        onChange={(e) => setDraft({ ...d, is_active: e.target.checked })}
                      />
                    </td>

                    <td className="py-2 px-3 text-right">
                      {fmt(
                        Number(d.quantity || 0) *
                          Number(d.unit_price || 0) *
                          (d.frequency === "monthly" && Number(d.months || 0) > 0 ? Number(d.months) : 1)
                      )}
                    </td>
                    <td className="py-2 px-3 text-right">
                      {fmt(
                        Number(d.quantity || 0) *
                          Number(d.unit_cogs || 0) *
                          (d.frequency === "monthly" && Number(d.months || 0) > 0 ? Number(d.months) : 1)
                      )}
                    </td>
                    <td className="py-2 px-3 text-right">
                      {fmt(
                        Number(d.quantity || 0) *
                          (Number(d.unit_price || 0) - Number(d.unit_cogs || 0)) *
                          (d.frequency === "monthly" && Number(d.months || 0) > 0 ? Number(d.months) : 1)
                      )}
                    </td>

                    <td className="py-2 px-3">
                      <div className="flex justify-end gap-2">
                        <button onClick={saveEdit} className="px-3 py-1.5 rounded border hover:bg-gray-50">
                          Save
                        </button>
                        <button onClick={cancelEdit} className="px-3 py-1.5 rounded border hover:bg-gray-50">
                          Cancel
                        </button>
                        <button
                          onClick={() => openPreviewFor(it)}
                          className="px-3 py-1.5 rounded border hover:bg-gray-50"
                          title="Preview price for this month"
                        >
                          Preview
                        </button>
                      </div>

                      {/* Popover - editing row */}
                      {previewFor === it.id && (
                        <div className="absolute right-2 top-full mt-2 w-[420px] rounded-lg border bg-white shadow-lg z-10 p-3 text-xs">
                          <div className="flex items-center justify-between mb-2">
                            <div className="font-medium">Price Preview</div>
                            <button
                              onClick={() => {
                                setPreviewFor(null);
                                setPreviewData(null);
                                setPreviewErr(null);
                              }}
                              className="text-gray-500 hover:text-gray-700"
                              title="Close"
                            >
                              ✕
                            </button>
                          </div>
                          <div className="flex items-center gap-2 mb-2">
                            <div>Period</div>
                            <MonthInput
                              value={previewYM}
                              onChange={(v) => {
                                const nextYM = v ?? nowYM();
                                setPreviewYM(nextYM);
                                reloadPreview(it.id!, nextYM);
                              }}
                            />
                            {previewBusy ? (
                              <span className="ml-auto text-amber-700 bg-amber-50 border border-amber-200 px-2 py-0.5 rounded">
                                Loading…
                              </span>
                            ) : null}
                          </div>

                          {previewErr ? (
                            <div className="text-rose-700 bg-rose-50 border border-rose-200 px-2 py-1 rounded">
                              {previewErr}
                            </div>
                          ) : previewData ? (
                            <div className="space-y-1">
                              <div className="flex justify-between">
                                <span>Source</span>
                                <b>{previewData.source}</b>
                              </div>
                              <div className="flex justify-between">
                                <span>Unit Price</span>
                                <b>
                                  {previewData.unit_price} {previewData.currency}
                                </b>
                              </div>
                              {previewData.base_price && previewData.factor ? (
                                <div className="flex justify-between text-gray-600">
                                  <span>Base × Factor</span>
                                  <span>
                                    {previewData.base_price} × {previewData.factor}
                                  </span>
                                </div>
                              ) : null}
                              <div className="flex justify-between">
                                <span>Quantity</span>
                                <span>{previewData.quantity}</span>
                              </div>
                              <div className="flex justify-between">
                                <span>Line Total</span>
                                <b>
                                  {previewData.line_total} {previewData.currency}
                                </b>
                              </div>

                              <div className="pt-2 flex justify-end gap-2">
                                <button
                                  onClick={() => applyPreviewUnitPrice(it)}
                                  className="px-2 py-1 rounded bg-indigo-600 text-white hover:bg-indigo-500"
                                >
                                  Apply unit price
                                </button>
                              </div>
                            </div>
                          ) : (
                            <div className="text-gray-500">No data.</div>
                          )}
                        </div>
                      )}
                    </td>
                  </tr>
                );
              }

              // ---- READ ROW ----
              return (
                <tr key={it.id} className="border-b relative">
                  <td className="py-2 px-3">{it.section}</td>
                  <td className="py-2 px-3">{BOQ_CATEGORY_LABELS[it.category as BOQCategory] ?? "—"}</td>
                  <td className="py-2 px-3">{it.item_name}</td>
                  <td className="py-2 px-3">{it.unit}</td>
                  <td className="py-2 px-3 text-right">{fmt(it.quantity)}</td>
                  <td className="py-2 px-3 text-right">{fmt(it.unit_price)}</td>
                  <td className="py-2 px-3 text-right">{fmt(it.unit_cogs ?? 0)}</td>
                  <td className="py-2 px-3">{it.frequency}</td>
                  <td className="py-2 px-3 text-right">{it.months ?? "-"}</td>
                  <td className="py-2 px-3 text-right">
                    {it.start_year ? `${it.start_year}/${pad2(it.start_month ?? 1)}` : "-"}
                  </td>
                  <td className="py-2 px-3 text-center">{it.is_active ? "✓" : "—"}</td>
                  <td className="py-2 px-3 text-right">{fmt(lt.revenue)}</td>
                  <td className="py-2 px-3 text-right">{fmt(lt.cogs)}</td>
                  <td className="py-2 px-3 text-right">{fmt(lt.gm)}</td>
                  <td className="py-2 px-3">
                    <div className="flex justify-end gap-2">
                      <button onClick={() => beginEdit(it)} className="px-3 py-1.5 rounded border hover:bg-gray-50">
                        Edit
                      </button>
                      <button onClick={() => onDelete(it)} className="px-3 py-1.5 rounded border hover:bg-gray-50">
                        Delete
                      </button>
                      <button
                        onClick={() => openPreviewFor(it)}
                        className="px-3 py-1.5 rounded border hover:bg-gray-50"
                        title="Preview price for this month"
                      >
                        Preview
                      </button>
                    </div>

                    {/* Popover - view row */}
                    {previewFor === it.id && (
                      <div className="absolute right-2 top-full mt-2 w-[420px] rounded-lg border bg-white shadow-lg z-10 p-3 text-xs">
                        <div className="flex items-center justify-between mb-2">
                          <div className="font-medium">Price Preview</div>
                          <button
                            onClick={() => {
                              setPreviewFor(null);
                              setPreviewData(null);
                              setPreviewErr(null);
                            }}
                            className="text-gray-500 hover:text-gray-700"
                            title="Close"
                          >
                            ✕
                          </button>
                        </div>
                        <div className="flex items-center gap-2 mb-2">
                          <div>Period</div>
                          <MonthInput
                            value={previewYM}
                            onChange={(v) => {
                              const nextYM = v ?? nowYM();
                              setPreviewYM(nextYM);
                              reloadPreview(it.id!, nextYM);
                            }}
                          />
                          {previewBusy ? (
                            <span className="ml-auto text-amber-700 bg-amber-50 border border-amber-200 px-2 py-0.5 rounded">
                              Loading…
                            </span>
                          ) : null}
                        </div>

                        {previewErr ? (
                          <div className="text-rose-700 bg-rose-50 border border-rose-200 px-2 py-1 rounded">
                            {previewErr}
                          </div>
                        ) : previewData ? (
                          <div className="space-y-1">
                            <div className="flex justify-between">
                              <span>Source</span>
                              <b>{previewData.source}</b>
                            </div>
                            <div className="flex justify-between">
                              <span>Unit Price</span>
                              <b>
                                {previewData.unit_price} {previewData.currency}
                              </b>
                            </div>
                            {previewData.base_price && previewData.factor ? (
                              <div className="flex justify-between text-gray-600">
                                <span>Base × Factor</span>
                                <span>
                                  {previewData.base_price} × {previewData.factor}
                                </span>
                              </div>
                            ) : null}
                            <div className="flex justify-between">
                              <span>Quantity</span>
                              <span>{previewData.quantity}</span>
                            </div>
                            <div className="flex justify-between">
                              <span>Line Total</span>
                              <b>
                                {previewData.line_total} {previewData.currency}
                              </b>
                            </div>

                            <div className="pt-2 flex justify-end gap-2">
                              <button
                                onClick={() => applyPreviewUnitPrice(it)}
                                className="px-2 py-1 rounded bg-indigo-600 text-white hover:bg-indigo-500"
                              >
                                Apply unit price
                              </button>
                            </div>
                          </div>
                        ) : (
                          <div className="text-gray-500">No data.</div>
                        )}
                      </div>
                    )}
                  </td>
                </tr>
              );
            })}
          </tbody>

          <tfoot>
            <tr className="border-t font-medium bg-gray-50">
              <td colSpan={11} className="py-2 px-3 text-right">
                Totals:
              </td>
              <td className="py-2 px-3 text-right">{fmt(totals.revenue)}</td>
              <td className="py-2 px-3 text-right">{fmt(totals.cogs)}</td>
              <td className="py-2 px-3 text-right">{fmt(totals.gm)}</td>
              <td />
            </tr>
          </tfoot>
        </table>
      </div>
    </Card>
  );
}
