// [BEGIN FILE] src/components/ProductPicker.tsx
import React, { useEffect, useMemo, useRef, useState } from "react";
import { apiGet } from "../lib/api";

/**
 * Shared ProductPicker (modal)
 * - Fetches families from /api/product-families
 * - Searches products from /api/products?limit=&q=&family_id=
 * - Debounced search, keyboard navigation, compact mode
 */

export type ProductFamily = {
  id: number;
  name: string;
  is_active?: number;
  description?: string | null;
};

export type ProductLite = {
  id: number;
  code: string;
  name: string;
  uom?: string | null;
  currency?: string | null;
  base_price?: number | null;
  product_family_id?: number | null;
};

export type ProductsListResp = { items: ProductLite[]; total?: number; limit?: number; offset?: number };
export type FamiliesListResp = { items: ProductFamily[] };

function cls(...a: (string | false | undefined)[]) {
  return a.filter(Boolean).join(" ");
}

type Props = {
  /** open/close modal */
  open: boolean;
  /** called when user clicks outside or presses Close/Escape */
  onClose: () => void;
  /** return the selected product */
  onPick: (product: ProductLite) => void;

  /** currently selected family id (controlled) */
  selectedFamilyId?: number | "";

  /** notify parent when family changes (controlled) */
  onFamilyChange?: (id: number | "") => void;

  /** if true, user can search without a family preselected (default: false) */
  allowNoFamilySearch?: boolean;

  /** initial query text when opening */
  initialQuery?: string;

  /** if true, renders a smaller body and fewer columns */
  compact?: boolean;

  /** max rows to request from BE (default 200) */
  limit?: number;
};

export default function ProductPicker({
  open,
  onClose,
  onPick,
  selectedFamilyId = "",
  onFamilyChange,
  allowNoFamilySearch = false,
  initialQuery = "",
  compact = false,
  limit = 200,
}: Props) {
  // families
  const [families, setFamilies] = useState<ProductFamily[]>([]);
  const [fam, setFam] = useState<number | "">(selectedFamilyId);
  // query + results
  const [q, setQ] = useState<string>(initialQuery);
  const [items, setItems] = useState<ProductLite[]>([]);
  // ui state
  const [loading, setLoading] = useState(false);
  const [err, setErr] = useState<string | null>(null);

  // keyboard navigation
  const [activeIdx, setActiveIdx] = useState<number>(-1);
  const listRef = useRef<HTMLDivElement | null>(null);
  const searchRef = useRef<HTMLInputElement | null>(null);

  // sync controlled family id from parent on open/prop change
  useEffect(() => {
    setFam(selectedFamilyId);
  }, [selectedFamilyId]);

  // focus search on open
  useEffect(() => {
    if (open) {
      // small timeout to ensure DOM is painted
      const t = setTimeout(() => searchRef.current?.focus(), 50);
      return () => clearTimeout(t);
    }
  }, [open]);

  // load families on first open
  useEffect(() => {
    if (!open) return;
    let cancelled = false;
    (async () => {
      try {
        const res = await apiGet<FamiliesListResp>("/api/product-families");
        if (!cancelled) setFamilies(res?.items ?? []);
      } catch {
        if (!cancelled) setFamilies([]);
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [open]);

  // debounced search
  useEffect(() => {
    if (!open) return;
    if (!allowNoFamilySearch && !fam) {
      setItems([]);
      setErr(null);
      setLoading(false);
      return;
    }

    setLoading(true);
    setErr(null);
    const t = setTimeout(async () => {
      try {
        const params = new URLSearchParams();
        params.set("limit", String(limit));
        if (q) params.set("q", q);
        if (fam) params.set("family_id", String(fam));
        const res = await apiGet<ProductsListResp>(`/api/products?${params.toString()}`);
        setItems(res?.items ?? []);
        setActiveIdx(res?.items?.length ? 0 : -1);
      } catch (e: any) {
        setErr(e?.response?.data?.detail || e?.message || "Failed to load products.");
        setItems([]);
      } finally {
        setLoading(false);
      }
    }, 250);

    return () => clearTimeout(t);
  }, [open, q, fam, allowNoFamilySearch, limit]);

  // Keep parent informed about family changes if controlled
  function changeFamily(next: number | "") {
    setFam(next);
    onFamilyChange?.(next);
  }

  function chooseAt(idx: number) {
    const it = items[idx];
    if (!it) return;
    onPick(it);
  }

  function onKeyDown(e: React.KeyboardEvent<HTMLInputElement>) {
    if (!items.length) return;
    if (e.key === "ArrowDown") {
      e.preventDefault();
      setActiveIdx((i) => Math.min(i + 1, items.length - 1));
      scrollIntoView(activeIdx + 1);
    } else if (e.key === "ArrowUp") {
      e.preventDefault();
      setActiveIdx((i) => Math.max(i - 1, 0));
      scrollIntoView(Math.max(activeIdx - 1, 0));
    } else if (e.key === "Enter") {
      e.preventDefault();
      if (activeIdx >= 0) chooseAt(activeIdx);
    } else if (e.key === "Escape") {
      e.preventDefault();
      onClose();
    }
  }

  function scrollIntoView(idx: number) {
    const container = listRef.current;
    if (!container) return;
    const el = container.querySelector<HTMLDivElement>(`[data-row="${idx}"]`);
    if (!el) return;
    const cTop = container.scrollTop;
    const cBottom = cTop + container.clientHeight;
    const eTop = el.offsetTop;
    const eBottom = eTop + el.offsetHeight;
    if (eTop < cTop) container.scrollTop = eTop;
    if (eBottom > cBottom) container.scrollTop = eBottom - container.clientHeight;
  }

  // reset content when closing
  useEffect(() => {
    if (!open) {
      setItems([]);
      setErr(null);
      setLoading(false);
      setActiveIdx(-1);
      // do not reset q/fam so re-open preserves context
    }
  }, [open]);

  const showUom = useMemo(() => !compact, [compact]);

  return (
    <div
      className={cls("fixed inset-0 z-50", open ? "pointer-events-auto" : "pointer-events-none")}
      aria-hidden={!open}
    >
      {/* Backdrop */}
      <div
        className={cls(
          "absolute inset-0 bg-black/30 transition-opacity",
          open ? "opacity-100" : "opacity-0"
        )}
        onClick={onClose}
      />

      {/* Dialog */}
      <div
        className={cls(
          "absolute left-1/2 top-12 -translate-x-1/2 w-[780px] max-w-[95vw] bg-white rounded-2xl shadow-xl border transition-opacity",
          open ? "opacity-100" : "opacity-0"
        )}
        role="dialog"
        aria-modal="true"
        aria-label="Select Product"
      >
        {/* Header */}
        <div className="px-4 py-3 border-b flex items-center gap-2">
          <div className="font-semibold">Select Product</div>
          <div className="ml-auto flex gap-2">
            <select
              className="px-2 py-1.5 rounded border text-sm"
              value={fam}
              onChange={(e) => changeFamily(e.target.value ? Number(e.target.value) : "")}
              title="Product Family"
            >
              <option value="">{allowNoFamilySearch ? "All Families" : "Select family…"}</option>
              {families.map((f) => (
                <option key={f.id} value={f.id}>
                  {f.name}
                </option>
              ))}
            </select>
            <input
              ref={searchRef}
              className="px-2 py-1.5 rounded border w-64 text-sm"
              placeholder={allowNoFamilySearch || fam ? "Search code/name…" : "Select a family first"}
              value={q}
              onChange={(e) => setQ(e.target.value)}
              onKeyDown={onKeyDown}
              disabled={!allowNoFamilySearch && !fam}
            />
            <button className="px-3 py-1.5 rounded border text-sm" onClick={onClose}>
              Close
            </button>
          </div>
        </div>

        {/* Error */}
        {err && <div className="px-4 py-2 text-sm text-rose-700 bg-rose-50 border-b border-rose-200">{err}</div>}

        {/* Results */}
        <div className="max-h-[64vh] overflow-auto" ref={listRef}>
          <table className="min-w-full text-sm">
            <thead className="bg-gray-50 sticky top-0 z-10">
              <tr>
                <th className="px-3 py-2 text-left w-36">Code</th>
                <th className="px-3 py-2 text-left">Name</th>
                {showUom && <th className="px-3 py-2 text-left w-24">UOM</th>}
                <th className="px-3 py-2 w-28"></th>
              </tr>
            </thead>
            <tbody>
              {loading ? (
                <tr>
                  <td colSpan={showUom ? 4 : 3} className="px-3 py-4 text-center text-gray-500">
                    Loading…
                  </td>
                </tr>
              ) : items.length > 0 ? (
                items.map((p, idx) => (
                  <tr
                    key={p.id}
                    data-row={idx}
                    className={cls(
                      "odd:bg-white even:bg-gray-50",
                      activeIdx === idx && "outline outline-2 outline-indigo-200"
                    )}
                    onMouseEnter={() => setActiveIdx(idx)}
                  >
                    <td className="px-3 py-2 font-mono text-xs">{p.code}</td>
                    <td className="px-3 py-2">{p.name}</td>
                    {showUom && <td className="px-3 py-2">{p.uom || ""}</td>}
                    <td className="px-3 py-2">
                      <button
                        className="px-2 py-1 rounded border hover:bg-gray-50 text-xs"
                        onClick={() => onPick(p)}
                      >
                        Select
                      </button>
                    </td>
                  </tr>
                ))
              ) : (
                <tr>
                  <td colSpan={showUom ? 4 : 3} className="px-3 py-4 text-center text-gray-500">
                    {fam || allowNoFamilySearch ? "No products" : "Select a family to begin"}
                  </td>
                </tr>
              )}
            </tbody>
          </table>
        </div>

        {/* Footer (optional info) */}
        <div className="px-4 py-2 text-[11px] text-gray-500 border-t">
          Tips: use ↑/↓ to navigate, Enter to select, Esc to close.
        </div>
      </div>
    </div>
  );
}
// [END FILE]
