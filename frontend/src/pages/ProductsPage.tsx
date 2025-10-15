
// frontend/src/pages/ProductsPage.tsx
import React, { useEffect, useMemo, useState, useCallback } from "react";
import { apiGet, apiPost, apiPut, apiDelete } from "../lib/api";
import {
  listProductFamilies,
  listPriceBooks,
  listPriceBookEntries,
  getBestPriceForProduct,
  type ProductFamily,
} from "../lib/apiProducts";
import { useNavigate } from "react-router-dom";

/* --------------------------------------------------------------------------
 * Engine Category Codes (UI options)
 * -------------------------------------------------------------------------- */
const ENGINE_CATEGORY_CODES = ["AN", "EM", "IE", "Services"] as const;
type EngineCategory = (typeof ENGINE_CATEGORY_CODES)[number];
const ENGINE_CATEGORY_LABEL: Record<EngineCategory, string> = {
  AN: "Ammonium Nitrate",
  EM: "Emulsion",
  IE: "Initiating Explosives",
  Services: "Services",
};

type Product = {
  id: number;
  code: string;
  name: string;
  description?: string | null;
  uom?: string | null;
  currency?: string | null;
  base_price?: number | null;
  tax_rate_pct?: number | null;
  barcode_gtin?: string | null;
  is_active: boolean;
  metadata?: string | null;
  product_family_id?: number | null;

  // backend additions
  category_code?: string | null; // resolved
  product_category_code?: string | null; // override
  family_category_code?: string | null; // default
};
type PriceBook = { id: number; name: string; currency?: string | null };
type PriceBookEntry = {
  id: number;
  price_book_id: number;
  product_id: number;
  unit_price: number;
  currency?: string | null;
};

export default function ProductsPage() {
  const nav = useNavigate();

  const [rows, setRows] = useState<Product[]>([]);
  const [families, setFamilies] = useState<ProductFamily[]>([]);
  const [loading, setLoading] = useState(true);
  const [err, setErr] = useState<string | null>(null);
  const [q, setQ] = useState("");
  const [selected, setSelected] = useState<Product | null>(null);
  const [editing, setEditing] = useState<Partial<Product> & { category_code?: string } | null>(null);
  const [formError, setFormError] = useState<string | null>(null);
  const [tab, setTab] = useState<"overview" | "pricebooks" | "audit">("overview");
  const [books, setBooks] = useState<PriceBook[]>([]);
  const [bookEntries, setBookEntries] = useState<PriceBookEntry[]>([]);
  const [bestPrice, setBestPrice] = useState<
    | {
        unit_price: number;
        currency?: string | null;
        price_book_id: number;
        price_book_entry_id: number;
        valid_from?: string | null;
        valid_to?: string | null;
      }
    | null
  >(null);

  // ---------- Product Families ----------
  const loadFamilies = useCallback(async () => {
    try {
      const pf = await listProductFamilies({ active: true });
      const items = (pf.items ?? pf ?? []) as ProductFamily[];
      if (Array.isArray(items) && items.length) {
        setFamilies(sortFamilies(items));
        return;
      }
    } catch {}
    const candidates = ["/api/product-families?active=true", "/api/product_families?active=true", "/api/products/families?active=true"];
    for (const url of candidates) {
      try {
        const res: any = await apiGet(url);
        const items: ProductFamily[] = res?.items ?? res?.data ?? (Array.isArray(res) ? res : []);
        if (items?.length) {
          setFamilies(sortFamilies(items));
          return;
        }
      } catch {}
    }
    setFamilies([]);
  }, []);

  function sortFamilies(list: ProductFamily[]) {
    return [...list].sort((a, b) =>
      (a.name ?? "").localeCompare(b.name ?? "", undefined, { sensitivity: "base" })
    );
  }

  // products
  useEffect(() => {
    (async () => {
      setLoading(true);
      setErr(null);
      try {
        const res = await apiGet<any>("/api/products");
        setRows(res.items ?? res ?? []);
      } catch (e: any) {
        setErr(e?.message || "Failed to load products");
      } finally {
        setLoading(false);
      }
    })();
  }, []);

  useEffect(() => {
    loadFamilies();
  }, [loadFamilies]);

  useEffect(() => {
    (async () => {
      if (!selected) return;
      if (tab !== "pricebooks") {
        setBestPrice(null);
        return;
      }
      try {
        const bks = await listPriceBooks({ active: true });
        const list = bks.items ?? [];
        setBooks(list);

        const all: PriceBookEntry[] = [];
        for (const b of list) {
          const es = await listPriceBookEntries(b.id, selected.id);
          all.push(...(es.items ?? []));
        }
        setBookEntries(all);

        try {
          const bp = await getBestPriceForProduct(selected.id);
          setBestPrice({
            unit_price: bp.unit_price,
            currency: bp.currency,
            price_book_id: bp.price_book_id,
            price_book_entry_id: bp.price_book_entry_id,
            valid_from: bp.valid_from,
            valid_to: bp.valid_to,
          });
        } catch {
          setBestPrice(null);
        }
      } catch {}
    })();
  }, [selected, tab]);

  const filtered = useMemo(() => {
    const t = q.toLowerCase().trim();
    if (!t) return rows;
    return rows.filter(
      (r) => r.name.toLowerCase().includes(t) || r.code.toLowerCase().includes(t)
    );
  }, [rows, q]);

  const isDuplicateCode = useCallback((code: string, id?: number) => {
    const c = (code || "").trim().toLowerCase();
    if (!c) return false;
    return rows.some((r) => r.code.toLowerCase() === c && r.id !== id);
  }, [rows]);

  function friendlyApiError(e: any): string {
    const raw =
      e?.detail ||
      e?.message ||
      e?.error ||
      e?.response?.data?.detail ||
      e?.response?.data?.error ||
      e?.toString?.() ||
      "Unknown error";

    // sqlite unique constraint (backend returns 409)
    const is409 =
      (e?.status === 409) ||
      (e?.response?.status === 409) ||
      /UNIQUE constraint failed: products\.code/i.test(String(raw)) ||
      /duplicate/i.test(String(raw)) ||
      /already exists/i.test(String(raw));

    if (is409) {
      return "This product code already exists. Please choose a different code.";
    }
    return String(raw);
  }

  async function save() {
    if (!editing) return;
    setFormError(null);

    const duplicate = isDuplicateCode(editing.code || "", editing.id as any);
    if (duplicate) {
      setFormError("This product code already exists. Please choose a different code.");
      return;
    }

    const payload: any = {
      code: editing.code || "",
      name: editing.name || "",
      description: editing.description ?? null,
      uom: editing.uom ?? null,
      currency: editing.currency || "USD",
      base_price: Number(editing.base_price || 0),
      tax_rate_pct: editing.tax_rate_pct ?? null,
      barcode_gtin: editing.barcode_gtin ?? null,
      is_active: editing.is_active ?? true,
      product_family_id:
        editing.product_family_id === undefined ? null : editing.product_family_id,
      category_code: editing.category_code ?? "",
    };

    try {
      if (editing.id) {
        await apiPut(`/api/products/${editing.id}`, payload);
      } else {
        const created: any = await apiPost("/api/products", payload);
        const newId = created?.id ?? created?.data?.id;
        if (newId) {
          setSelected({ id: newId, ...payload } as any);
        }
      }

      const res = await apiGet<any>("/api/products");
      setRows(res.items ?? res ?? []);
      setEditing(null);
    } catch (e: any) {
      setFormError(friendlyApiError(e));
    }
  }

  async function remove(p: Product) {
    if (!confirm(`Delete ${p.name}?`)) return;
    await apiDelete(`/api/products/${p.id}`);
    const res = await apiGet<any>("/api/products");
    setRows(res.items ?? res ?? []);
    if (selected?.id === p.id) setSelected(null);
  }

  const familyName = (fid?: number | null) =>
    fid ? families.find((f) => (f as any).id === fid)?.name ?? `#${fid}` : "—";

  const categoryLabel = (code?: string | null) =>
    code && ENGINE_CATEGORY_CODES.includes(code as EngineCategory)
      ? `${code} — ${ENGINE_CATEGORY_LABEL[code as EngineCategory]}`
      : code || "—";

  const codeWarning =
    editing?.code && isDuplicateCode(editing.code, editing.id as any)
      ? "This code is already in use."
      : "";

  const saveDisabled =
    !editing?.code || !editing?.name || !!codeWarning;

  return (
    <div className="grid grid-cols-12 gap-4">
      <aside className="col-span-4 border rounded-xl p-3 bg-white">
        <div className="flex justify-between items-center mb-2">
          <input
            className="border rounded px-2 py-1 w-2/3"
            placeholder="Search code/name…"
            value={q}
            onChange={(e) => setQ(e.target.value)}
          />
          <div className="flex gap-2">
            <button
              className="px-3 py-1.5 border rounded"
              onClick={() =>
                setEditing({ currency: "USD", is_active: true, category_code: "" })
              }
            >
              + New
            </button>
            <button
              className="px-3 py-1.5 border rounded"
              onClick={() => nav("/products/price-books")}
              title="Open Price Books to define product prices"
            >
              Define Prices
            </button>
          </div>
        </div>
        {loading ? (
          <div>Loading…</div>
        ) : err ? (
          <div className="text-red-600">{err}</div>
        ) : (
          <div className="h-[520px] overflow-auto divide-y">
            {filtered.map((p) => (
              <div
                key={p.id}
                className={
                  "p-2 cursor-pointer text-sm " +
                  (selected?.id === p.id ? "bg-indigo-50" : "hover:bg-gray-50")
                }
                onClick={() => setSelected(p)}
              >
                <div className="font-medium">{p.name}</div>
                <div className="text-gray-600">
                  {p.code} • {p.currency ?? "USD"} {Number(p.base_price || 0).toFixed(2)}
                </div>
                <div className="text-xs text-gray-500">
                  Family: {familyName(p.product_family_id)}
                </div>
                <div className="text-xs text-gray-500">
                  Category: {p.category_code || "—"}
                </div>
              </div>
            ))}
          </div>
        )}
      </aside>

      <main className="col-span-8 space-y-4">
        {!selected && !editing ? (
          <div className="text-sm text-gray-600 border rounded-xl p-6 bg-white">
            Select a product or create a new one.
          </div>
        ) : editing ? (
          <div className="border rounded-xl p-4 bg-white space-y-3">
            <h3 className="font-semibold">
              {editing.id ? "Edit Product" : "New Product"}
            </h3>

            {formError && (
              <div className="p-3 rounded bg-red-50 border border-red-200 text-red-700 text-sm">
                {formError}
              </div>
            )}

            <div className="grid grid-cols-2 gap-3 text-sm">
              <label className="flex flex-col">
                <span>Code</span>
                <input
                  className={`border rounded px-2 py-1 ${codeWarning ? "border-red-400" : ""}`}
                  value={editing.code || ""}
                  onChange={(e) => {
                    setFormError(null);
                    setEditing({ ...editing, code: e.target.value });
                  }}
                />
                {codeWarning && (
                  <span className="text-xs text-red-600 mt-1">{codeWarning}</span>
                )}
              </label>
              <label className="flex flex-col">
                <span>Name</span>
                <input
                  className="border rounded px-2 py-1"
                  value={editing.name || ""}
                  onChange={(e) => {
                    setFormError(null);
                    setEditing({ ...editing, name: e.target.value });
                  }}
                />
              </label>

              <label className="flex flex-col">
                <span>UOM</span>
                <input
                  className="border rounded px-2 py-1"
                  value={editing.uom || ""}
                  onChange={(e) => setEditing({ ...editing, uom: e.target.value })}
                />
              </label>
              <label className="flex flex-col">
                <span>Currency</span>
                <input
                  className="border rounded px-2 py-1"
                  value={editing.currency || "USD"}
                  onChange={(e) =>
                    setEditing({ ...editing, currency: e.target.value })
                  }
                />
              </label>

              <label className="flex flex-col">
                <span>Base Price</span>
                <input
                  type="number"
                  className="border rounded px-2 py-1"
                  value={Number(editing.base_price || 0)}
                  onChange={(e) =>
                    setEditing({
                      ...editing,
                      base_price: Number(e.target.value || 0),
                    })
                  }
                />
              </label>
              <label className="flex flex-col">
                <span>Tax %</span>
                <input
                  type="number"
                  className="border rounded px-2 py-1"
                  value={Number(editing.tax_rate_pct || 0)}
                  onChange={(e) =>
                    setEditing({
                      ...editing,
                      tax_rate_pct: Number(e.target.value || 0),
                    })
                  }
                />
              </label>

              <label className="flex flex-col col-span-2">
                <span>Product Family</span>
                <select
                  className="border rounded px-2 py-1"
                  value={editing.product_family_id ?? ""}
                  onChange={(e) => {
                    const val = e.target.value === "" ? null : Number(e.target.value);
                    let nextCategory = editing.category_code ?? "";
                    if (!nextCategory) {
                      const f = families.find((x) => (x as any).id === val);
                      const famCat = (f as any)?.family_category_code;
                      if (famCat) nextCategory = "";
                    }
                    setEditing({
                      ...editing,
                      product_family_id: val,
                      category_code: nextCategory,
                    });
                  }}
                >
                  <option value="">— None —</option>
                  {families.map((f) => (
                    <option key={(f as any).id} value={(f as any).id}>
                      {(f as any).name}
                    </option>
                  ))}
                </select>
                {families.length === 0 && (
                  <span className="mt-1 text-xs text-gray-500">
                    No families found. You can still save without one.
                  </span>
                )}
              </label>

              {/* Engine Category Code (product override) */}
              <label className="flex flex-col col-span-2">
                <span>Engine Category Code</span>
                <select
                  className="border rounded px-2 py-1"
                  value={editing.category_code ?? ""}
                  onChange={(e) =>
                    setEditing({
                      ...editing,
                      category_code: e.target.value, // "" => inherit
                    })
                  }
                >
                  <option value="">— Inherit from family —</option>
                  {ENGINE_CATEGORY_CODES.map((code) => (
                    <option key={code} value={code}>
                      {code} — {ENGINE_CATEGORY_LABEL[code]}
                    </option>
                  ))}
                </select>
                <span className="mt-1 text-xs text-gray-500">
                  Leave blank to inherit the product family’s category. Selecting a value sets a product-level override.
                </span>
              </label>

              <label className="flex items-center gap-2">
                <input
                  type="checkbox"
                  checked={editing.is_active ?? true}
                  onChange={(e) =>
                    setEditing({ ...editing, is_active: e.target.checked })
                  }
                />
                Active
              </label>

              <label className="flex flex-col col-span-2">
                <span>Description</span>
                <textarea
                  className="border rounded px-2 py-1"
                  rows={3}
                  value={editing.description || ""}
                  onChange={(e) =>
                    setEditing({ ...editing, description: e.target.value })
                  }
                />
              </label>
            </div>
            <div className="flex gap-2">
              <button className="px-3 py-1.5 border rounded disabled:opacity-50" onClick={save} disabled={saveDisabled}>
                Save
              </button>
              <button
                className="px-3 py-1.5 border rounded"
                onClick={() => {
                  setFormError(null);
                  setEditing(null);
                }}
              >
                Cancel
              </button>
            </div>
          </div>
        ) : (
          <div className="border rounded-xl p-4 bg-white">
            <div className="flex justify-between items-center">
              <h3 className="font-semibold">{selected?.name}</h3>
              <div className="flex gap-2">
                <button
                  className="px-3 py-1.5 border rounded"
                  onClick={() => setEditing({ 
                    ...selected!, 
                    category_code: (selected as any).product_category_code ?? "" 
                  })}
                >
                  Edit
                </button>
                <button
                  className="px-3 py-1.5 border rounded"
                  onClick={() => remove(selected!)}
                >
                  Delete
                </button>
              </div>
            </div>

            <div className="mt-3 border-b flex gap-4 text-sm">
              {["overview", "pricebooks", "audit"].map((t) => (
                <button
                  key={t}
                  className={
                    "pb-2 " +
                    (tab === t
                      ? "border-b-2 border-indigo-600 font-medium"
                      : "text-gray-600")
                  }
                  onClick={() => setTab(t as any)}
                >
                  {t}
                </button>
              ))}
            </div>

            {tab === "overview" && (
              <div className="mt-3 text-sm grid grid-cols-2 gap-3">
                <div>
                  <span className="text-gray-500">Code:</span> {selected?.code}
                </div>
                <div>
                  <span className="text-gray-500">UOM:</span>{" "}
                  {selected?.uom || "-"}
                </div>
                <div>
                  <span className="text-gray-500">Currency:</span>{" "}
                  {selected?.currency || "USD"}
                </div>
                <div>
                  <span className="text-gray-500">Base Price:</span>{" "}
                  {Number(selected?.base_price || 0).toFixed(2)}
                </div>
                <div className="col-span-2">
                  <span className="text-gray-500">Family:</span>{" "}
                  {familyName(selected?.product_family_id)}
                </div>

                <div className="col-span-2">
                  <span className="text-gray-500">Category (resolved):</span>{" "}
                  {categoryLabel(selected?.category_code)}
                </div>
                <div>
                  <span className="text-gray-500">Product override:</span>{" "}
                  {categoryLabel((selected as any)?.product_category_code)}
                </div>
                <div>
                  <span className="text-gray-500">Family default:</span>{" "}
                  {categoryLabel((selected as any)?.family_category_code)}
                </div>

                <div className="col-span-2">
                  <span className="text-gray-500">Description:</span>{" "}
                  {selected?.description || "-"}
                </div>
              </div>
            )}

            {tab === "pricebooks" && (
              <div className="mt-3 text-sm space-y-4">
                <div className="p-3 rounded border bg-gray-50">
                  <div className="font-medium mb-1">Best price (today)</div>
                  {bestPrice ? (
                    <div className="flex flex-wrap gap-4">
                      <div>
                        {bestPrice.currency || selected?.currency || "USD"}{" "}
                        {Number(bestPrice.unit_price).toFixed(2)}
                      </div>
                      <div>Book #{bestPrice.price_book_id}</div>
                      <div>Entry #{bestPrice.price_book_entry_id}</div>
                      <div>
                        {bestPrice.valid_from || "—"} → {bestPrice.valid_to || "—"}
                      </div>
                    </div>
                  ) : (
                    <div className="text-gray-600">
                      No active price found for today.
                    </div>
                  )}
                </div>

                {bookEntries.length === 0 ? (
                  <div className="text-gray-500">
                    No price-book entries for this product.
                  </div>
                ) : (
                  <div className="divide-y">
                    {bookEntries.map((e) => (
                      <div key={e.id} className="py-2 flex justify-between">
                        <div>Book #{e.price_book_id}</div>
                        <div>
                          {e.currency || selected?.currency || "USD"}{" "}
                          {Number(e.unit_price).toFixed(2)}
                        </div>
                      </div>
                    ))}
                  </div>
                )}
              </div>
            )}

            {tab === "audit" && (
              <div className="mt-3 text-sm text-gray-600">
                Created: - · Updated: -
              </div>
            )}
          </div>
        )}
      </main>
    </div>
  );
}
