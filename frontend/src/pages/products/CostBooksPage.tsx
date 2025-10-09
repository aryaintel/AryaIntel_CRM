// Path: src/pages/products/CostBooksPage.tsx

import React, { useEffect, useMemo, useRef, useState } from "react";
import { apiGet, apiPost, apiPut, apiDelete } from "../../lib/api";

/**
 * CostBooksPage — Salesforce-style UI (parallel to PriceBooksPage)
 * Books: code, name, currency, is_active, is_default
 * Entries: unit_cost, cost_term_id, valid_from/to, notes (per product)
 *
 * Flexible endpoints:
 * - Books:             /api/cost-books | /api/cost_books
 * - Entries (nested):  /api/cost-books/{id}/entries | /api/cost_books/{id}/entries
 * - Entries (flat):    /api/cost-book-entries?cost_book_id= | /api/cost_book_entries?cost_book_id=
 *   We detect which base worked when loading and POST to that first.
 */

// ---------- Types ----------
type CostBook = {
  id?: number;
  code: string;
  name: string;
  currency: string;
  is_active: boolean;
  is_default: boolean;
  created_at?: string | null;
  updated_at?: string | null;
};

type CostBookEntry = {
  id?: number;
  cost_book_id?: number;
  product_id: number;

  // Optional display helpers
  product_code?: string | null;
  product_name?: string | null;

  unit_cost: number;
  valid_from?: string | null;
  valid_to?: string | null;

  cost_term?: string | null;
  cost_term_id?: number | null;

  notes?: string | null;
};

type ProductLite = {
  id: number;
  code: string;
  name: string;
  currency?: string | null;
  product_family_id?: number | null;
};
type ProductFamily = { id: number; name: string };
type PriceTermOpt = { id: number; code: string; name?: string | null; is_active?: boolean | number };

// ---------- Utilities ----------
function toBool(x: any): boolean {
  if (typeof x === "boolean") return x;
  if (typeof x === "number") return x !== 0;
  if (typeof x === "string") return x === "1" || x.toLowerCase() === "true";
  return !!x;
}
function unwrapList<T = any>(res: any): T[] {
  if (Array.isArray(res)) return res as T[];
  if (res?.items && Array.isArray(res.items)) return res.items as T[];
  if (res?.data && Array.isArray(res.data)) return res.data as T[];
  if (res?.results && Array.isArray(res.results)) return res.results as T[];
  return [];
}
async function tryGet<T>(paths: string[]): Promise<{ base: string; items: T[] }> {
  let lastErr: unknown;
  for (const p of paths) {
    try {
      const res = await apiGet(p);
      const items = unwrapList<T>(res);
      if (!Array.isArray(res) && items.length === 0 && res) {
        return { base: p, items: [res as T] };
      }
      return { base: p, items };
    } catch (e) {
      lastErr = e;
    }
  }
  throw new Error(`No reachable endpoint from: ${paths.join(", ")}`);
}
async function tryPost<T>(candidates: { url: string; body: any }[]): Promise<T> {
  let lastErr: any = null;
  for (const c of candidates) {
    try {
      return await apiPost(c.url, c.body);
    } catch (e) {
      lastErr = e;
    }
  }
  throw lastErr ?? new Error("POST failed for all candidates");
}
async function tryPut<T>(candidates: { url: string; body: any }[]): Promise<T> {
  let lastErr: any = null;
  for (const c of candidates) {
    try {
      return await apiPut(c.url, c.body);
    } catch (e) {
      lastErr = e;
    }
  }
  throw lastErr ?? new Error("PUT failed for all candidates");
}
async function tryDelete(candidates: string[]): Promise<void> {
  let lastErr: any = null;
  for (const url of candidates) {
    try {
      await apiDelete(url);
      return;
    } catch (e) {
      lastErr = e;
    }
  }
  throw lastErr ?? new Error("DELETE failed for all candidates");
}

// ---- Endpoints (flexible like PriceBooksPage) ----
const BOOKS_CANDIDATES = ["/api/cost-books", "/api/cost_books"];
const ENTRIES_FLAT_BASES = ["/api/cost-book-entries", "/api/cost_book_entries"]; // list/get/update/delete with ?cost_book_id
const ENTRIES_NESTED_TEMPLATES = ["/api/cost-books/{id}/entries", "/api/cost_books/{id}/entries"]; // list/create/update/delete

// Reference endpoints (shared)
const FAMILIES_URL = "/api/product-families";
const PRODUCTS_URL = "/api/products";
const PRICE_TERMS_OPTS = ["/api/price-terms/options", "/api/price_terms/options"];

// ---------- Component ----------
export default function CostBooksPage() {
  // ---- State ----
  const [err, setErr] = useState<string | null>(null);
  const [busy, setBusy] = useState<string | null>(null);

  // Books
  const [books, setBooks] = useState<CostBook[]>([]);
  const [booksBase, setBooksBase] = useState<string | null>(null);
  const [selectedId, setSelectedId] = useState<number | null>(null);

  // Entries
  const [entries, setEntries] = useState<CostBookEntry[]>([]);
  const [entriesBase, setEntriesBase] = useState<string | null>(null); // exact base used by GET (nested or flat)

  // Product cache to hydrate rows that come back with ids only
  const [productCache, setProductCache] = useState<Record<number, ProductLite>>({});

  // Drafts
  const [draftBook, setDraftBook] = useState<CostBook>({
    code: "",
    name: "",
    currency: "USD",
    is_active: true,
    is_default: false,
  });

  const [entryDraft, setEntryDraft] = useState<CostBookEntry>({
    product_id: 0,
    unit_cost: 0,
    valid_from: null,
    valid_to: null,
    cost_term_id: null,
    notes: "",
  });

  // Families & product search
  const [families, setFamilies] = useState<ProductFamily[]>([]);
  const [entryFamilyId, setEntryFamilyId] = useState<number | "">("");

  const [productQuery, setProductQuery] = useState<string>("");
  const [productOptions, setProductOptions] = useState<ProductLite[]>([]);
  const [prodBusy, setProdBusy] = useState<boolean>(false);

  const [priceTerms, setPriceTerms] = useState<PriceTermOpt[]>([]);

  // Product dropdown UX
  const [showProdDropdown, setShowProdDropdown] = useState<boolean>(false);
  const [prodFocused, setProdFocused] = useState<boolean>(false);
  const prodBoxRef = useRef<HTMLDivElement | null>(null);

  // Toggle to reveal the Add-entry form
  const [showAddEntry, setShowAddEntry] = useState<boolean>(false);

  // Close product dropdown on outside click
  useEffect(() => {
    function onDocMouseDown(e: MouseEvent) {
      if (!prodBoxRef.current) return;
      if (!prodBoxRef.current.contains(e.target as Node)) {
        setShowProdDropdown(false);
        setProdFocused(false);
      }
    }
    document.addEventListener("mousedown", onDocMouseDown);
    return () => document.removeEventListener("mousedown", onDocMouseDown);
  }, []);

  // ---- Load books + reference data ----
  async function reloadBooks() {
    setErr(null);
    const { base, items } = await tryGet<any>(BOOKS_CANDIDATES);
    setBooks(items.map(normalizeBook));
    setBooksBase(base);
    if (!selectedId && items.length) {
      setSelectedId(normalizeBook(items[0]).id || null);
    }
  }
  async function loadFamilies() {
    try {
      const res = await apiGet(FAMILIES_URL);
      setFamilies(unwrapList<ProductFamily>(res));
    } catch (e: any) {
      setErr(e?.message || String(e));
    }
  }
  async function loadPriceTerms() {
    for (const p of PRICE_TERMS_OPTS) {
      try {
        const res = await apiGet(p);
        setPriceTerms(unwrapList<PriceTermOpt>(res));
        return;
      } catch {}
    }
    setPriceTerms([]);
  }

  useEffect(() => {
    reloadBooks().catch((e) => setErr(e?.message || String(e)));
    loadFamilies();
    loadPriceTerms();
  }, []);

  // Reset add-entry form when switching books
  useEffect(() => {
    setShowAddEntry(false);
    setEntryFamilyId("");
    setEntryDraft((d) => ({ ...d, product_id: 0, cost_term_id: null }));
    setProductQuery("");
    setProductOptions([]);
    setShowProdDropdown(false);
    setProdFocused(false);
  }, [selectedId]);

  // ---- Load entries when selection changes ----
  useEffect(() => {
    if (!selectedId || !booksBase) return;
    loadEntries(selectedId).catch((e) => setErr(e?.message || String(e)));
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [selectedId, booksBase]);

  // ---- Normalizers ----
  function normalizeBook(b: any): CostBook {
    return {
      id: b.id,
      code: String(b.code ?? ""),
      name: b.name ?? "",
      currency: b.currency ?? "USD",
      is_active: toBool(b.is_active),
      is_default: toBool(b.is_default),
      created_at: b.created_at ?? null,
      updated_at: b.updated_at ?? null,
    };
  }
  function normalizeEntry(e: any): CostBookEntry {
    return {
      id: e.id,
      cost_book_id: e.cost_book_id ?? e.book_id ?? undefined,
      product_id: e.product_id,
      product_code: e.product_code ?? null,
      product_name: e.product_name ?? null,
      unit_cost: Number(e.unit_cost ?? 0),
      valid_from: e.valid_from ?? null,
      valid_to: e.valid_to ?? null,
      cost_term_id: e.cost_term_id ?? null,
      cost_term: e.cost_term ?? null,
      notes: e.notes ?? "",
    };
  }

  // ---- Load entries (tries NESTED first, then FLAT) ----
  async function loadEntries(bookId: number) {
    if (!bookId) return;
    setBusy("entries");
    setErr(null);
    try {
      const nested = ENTRIES_NESTED_TEMPLATES.map((t) => t.replace("{id}", String(bookId)));
      const params = new URLSearchParams();
      params.set("cost_book_id", String(bookId));
      const flat = ENTRIES_FLAT_BASES.map((p) => `${p}?${params.toString()}`);

      const candidates = [...nested, ...flat]; // prefer nested
      const found = await tryGet<CostBookEntry>(candidates);

      // Normalize base (remove query if present)
      let base = found.base;
      const qpos = base.indexOf("?");
      if (qpos >= 0) base = base.slice(0, qpos);

      const normalized = found.items.map(normalizeEntry);
      setEntries(normalized);
      setEntriesBase(base);

      // ensure labels for any rows that came without product_code/name
      const idsNeedingLabels = normalized
        .filter((r) => !r.product_name || !r.product_code)
        .map((r) => r.product_id);
      ensureProducts(idsNeedingLabels);
    } finally {
      setBusy(null);
    }
  }

  // Ensure product details exist for display (hydrate code/name & family)
  async function ensureProducts(ids: number[]) {
    const missing = ids.filter((id) => !productCache[id]);
    if (missing.length === 0) return;

    const nextCache = { ...productCache };
    for (const id of missing) {
      try {
        const p = await apiGet(`${PRODUCTS_URL}/${id}`);
        if (p && (p as any)?.id) nextCache[(p as any).id] = p as ProductLite;
      } catch {
        // ignore
      }
    }
    setProductCache(nextCache);

    // patch current rows with labels
    setEntries((prev) =>
      prev.map((r) => {
        if ((!r.product_name || !r.product_code) && nextCache[r.product_id]) {
          const p = nextCache[r.product_id]!;
          return { ...r, product_code: p.code, product_name: p.name };
        }
        return r;
      })
    );
  }

  // ---- Mutations: Books ----
  async function createBook() {
    if (!booksBase) return;
    setBusy("create-book");
    setErr(null);
    try {
      const body = {
        code: draftBook.code.trim(),
        name: draftBook.name.trim(),
        currency: draftBook.currency.trim() || "USD",
        is_active: draftBook.is_active ? 1 : 0,
        is_default: draftBook.is_default ? 1 : 0,
      };
      if (!body.code || !body.name) throw new Error("Code and Name are required.");
      await apiPost(booksBase, body);
      await reloadBooks();
      setDraftBook({ code: "", name: "", currency: "USD", is_active: true, is_default: false });
    } catch (e: any) {
      setErr(e?.message || String(e));
    } finally {
      setBusy(null);
    }
  }

  async function updateBook(b: CostBook) {
    if (!booksBase || !b.id) return;
    setBusy(`update-book-${b.id}`);
    setErr(null);
    try {
      const body = {
        code: String(b.code || "").trim(),
        name: String(b.name || "").trim(),
        currency: String(b.currency || "").trim() || "USD",
        is_active: b.is_active ? 1 : 0,
        is_default: b.is_default ? 1 : 0,
      };
      await apiPut(`${booksBase}/${b.id}`, body);
      await reloadBooks();
    } catch (e: any) {
      setErr(e?.message || String(e));
    } finally {
      setBusy(null);
    }
  }

  async function deleteBook(id: number) {
    if (!booksBase || !id) return;
    if (!confirm("Delete this cost book?")) return;
    setBusy(`delete-book-${id}`);
    setErr(null);
    try {
      await apiDelete(`${booksBase}/${id}`);
      await reloadBooks();
      setSelectedId(null);
    } catch (e: any) {
      setErr(e?.message || String(e));
    } finally {
      setBusy(null);
    }
  }

  // ---- Mutations: Entries ----
  async function createEntry() {
    const selected = books.find((b) => b.id === selectedId);
    if (!selected) return;
    if (!entryDraft.product_id) {
      setErr("Please select a product.");
      return;
    }
    setBusy("create-entry");
    setErr(null);
    try {
      // Body for nested create (server derives cost_book_id from path)
      const nestedBody = {
        product_id: entryDraft.product_id,
        unit_cost: Number(entryDraft.unit_cost || 0),
        valid_from: entryDraft.valid_from || null,
        valid_to: entryDraft.valid_to || null,
        cost_term_id: entryDraft.cost_term_id ?? null,
        notes: entryDraft.notes ?? "",
      };
      // Body for flat create (explicit cost_book_id)
      const flatBody = {
        ...nestedBody,
        cost_book_id: selected.id,
      };

      // 1) Prefer POST to the same base we used for GET (entriesBase)
      const preferredCandidates: { url: string; body: any }[] = [];
      if (entriesBase) {
        if (entriesBase.includes("/cost-books/") || entriesBase.includes("/cost_books/")) {
          preferredCandidates.push({ url: entriesBase, body: nestedBody });
        } else {
          preferredCandidates.push({ url: entriesBase, body: flatBody });
        }
      }

      // 2) Fallbacks — nested templates then flat bases
      const nestedFallbacks = ENTRIES_NESTED_TEMPLATES.map((t) => ({
        url: t.replace("{id}", String(selected.id)),
        body: nestedBody,
      }));
      const flatFallbacks = ENTRIES_FLAT_BASES.map((p) => ({ url: p, body: flatBody }));

      await tryPost([...preferredCandidates, ...nestedFallbacks, ...flatFallbacks]);

      await loadEntries(selected.id!);

      // keep panel open; reset fields
      setEntryDraft({
        product_id: 0,
        unit_cost: 0,
        valid_from: null,
        valid_to: null,
        cost_term_id: null,
        notes: "",
      });
      setProductQuery("");
      setProductOptions([]);
      setShowProdDropdown(false);
      setProdFocused(false);
    } catch (e: any) {
      setErr(e?.message || String(e));
    } finally {
      setBusy(null);
    }
  }

  async function updateEntry(row: CostBookEntry) {
    if (!selectedId || !row.id) return;
    setBusy(`update-entry-${row.id}`);
    setErr(null);
    try {
      const body = {
        product_id: row.product_id,
        unit_cost: Number(row.unit_cost || 0),
        valid_from: row.valid_from || null,
        valid_to: row.valid_to || null,
        cost_term_id: row.cost_term_id ?? null,
        notes: row.notes ?? "",
      };
      const candidates = [
        entriesBase ? `${entriesBase}/${row.id}` : "",
        `/api/cost-book-entries/${row.id}`,
        `/api/cost_book_entries/${row.id}`,
      ].filter(Boolean) as string[];
      await tryPut(candidates.map((url) => ({ url, body })));
      await loadEntries(selectedId);
    } catch (e: any) {
      setErr(e?.message || String(e));
    } finally {
      setBusy(null);
    }
  }

  async function deleteEntry(row: CostBookEntry) {
    if (!row?.id) return;
    if (!confirm("Delete this cost entry?")) return;
    setBusy(`delete-entry-${row.id}`);
    setErr(null);
    try {
      const candidates = [
        entriesBase ? `${entriesBase}/${row.id}` : "",
        `/api/cost-book-entries/${row.id}`,
        `/api/cost_book_entries/${row.id}`,
      ].filter(Boolean) as string[];
      await tryDelete(candidates);
      await loadEntries(selectedId!);
    } catch (e: any) {
      setErr(e?.message || String(e));
    } finally {
      setBusy(null);
    }
  }

  // ---- Product search (family + query) ----
  async function searchProducts(query: string, familyId?: number | "") {
    setProdBusy(true);
    try {
      const params = new URLSearchParams();
      if (query) params.set("q", query);
      if (familyId) params.set("family_id", String(familyId));
      const url = `${PRODUCTS_URL}?${params.toString()}`;
      const res = await apiGet(url);
      setProductOptions(unwrapList<ProductLite>(res));
      if (prodFocused && entryFamilyId) setShowProdDropdown(true);
    } finally {
      setProdBusy(false);
    }
  }

  useEffect(() => {
    if (!entryFamilyId || !prodFocused) {
      setProductOptions([]);
      setShowProdDropdown(false);
      return;
    }
    const t = setTimeout(() => searchProducts(productQuery, entryFamilyId), 250);
    return () => clearTimeout(t);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [productQuery, entryFamilyId, prodFocused]);

  const selected = useMemo(() => books.find((b) => b.id === selectedId) || null, [books, selectedId]);

  // Helpers to show family name on rows
  const familyNameOf = (productId: number): string | undefined => {
    const p = productCache[productId];
    if (!p?.product_family_id) return undefined;
    const fam = families.find((f) => f.id === p.product_family_id);
    return fam?.name;
  };

  // ---- Render ----
  return (
    <div className="space-y-4">
      {/* Page header */}
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-semibold text-gray-900">Cost Books</h1>
          <p className="text-sm text-gray-600">Manage cost books and product unit costs for margin calculations.</p>
        </div>
        <div className="text-sm text-gray-600">
          {busy ? (
            <span className="px-2 py-1 rounded bg-amber-50 text-amber-700 border border-amber-200">Working: {busy}</span>
          ) : null}
        </div>
      </div>

      {/* Error banner */}
      {err ? (
        <div className="p-3 rounded-lg bg-rose-50 text-rose-700 border border-rose-200 text-sm">{err}</div>
      ) : null}

      {/* Two-column: Create/List (left) + Details (right) */}
      <div className="grid grid-cols-1 lg:grid-cols-3 gap-4">
        {/* Left column — Create + List */}
        <div className="space-y-4">
          {/* Create Card */}
          <div className="bg-white border rounded-2xl shadow-sm">
            <div className="px-4 py-3 border-b">
              <h2 className="font-medium">Create Cost Book</h2>
            </div>
            <div className="p-4 space-y-3">
              <div className="grid grid-cols-1 md:grid-cols-3 gap-3">
                <div>
                  <label className="block text-xs text-gray-600 mb-1">Code</label>
                  <input
                    className="w-full rounded-lg border px-3 py-2 text-sm"
                    value={draftBook.code}
                    onChange={(e) => setDraftBook({ ...draftBook, code: e.target.value })}
                    placeholder="e.g. CB-2025-01"
                  />
                </div>
                <div className="md:col-span-2">
                  <label className="block text-xs text-gray-600 mb-1">Name</label>
                  <input
                    className="w-full rounded-lg border px-3 py-2 text-sm"
                    value={draftBook.name}
                    onChange={(e) => setDraftBook({ ...draftBook, name: e.target.value })}
                    placeholder="e.g. 2025 Default Cost Book"
                  />
                </div>
                <div>
                  <label className="block text-xs text-gray-600 mb-1">Currency</label>
                  <input
                    className="w-full rounded-lg border px-3 py-2 text-sm"
                    value={draftBook.currency}
                    onChange={(e) => setDraftBook({ ...draftBook, currency: e.target.value })}
                    placeholder="USD"
                  />
                </div>
                <div className="flex items-end gap-4">
                  <label className="inline-flex items-center gap-2 text-sm">
                    <input
                      type="checkbox"
                      checked={draftBook.is_active}
                      onChange={(e) => setDraftBook({ ...draftBook, is_active: e.target.checked })}
                    />
                    Active
                  </label>
                  <label className="inline-flex items-center gap-2 text-sm">
                    <input
                      type="checkbox"
                      checked={draftBook.is_default}
                      onChange={(e) => setDraftBook({ ...draftBook, is_default: e.target.checked })}
                    />
                    Default
                  </label>
                </div>
              </div>

              <div className="flex justify-end">
                <button
                  onClick={createBook}
                  disabled={busy === "create-book"}
                  className="inline-flex items-center rounded-lg bg-indigo-600 text-white text-sm px-3 py-2 hover:bg-indigo-700 disabled:opacity-50"
                >
                  {busy === "create-book" ? "Creating…" : "Add Cost Book"}
                </button>
              </div>
            </div>
          </div>

          {/* List Card */}
          <div className="bg-white border rounded-2xl shadow-sm">
            <div className="px-4 py-3 border-b">
              <h2 className="font-medium">Cost Books</h2>
            </div>
            <div>
              {books.length === 0 ? (
                <div className="p-4 text-sm text-gray-600">No cost books yet.</div>
              ) : (
                <ul className="divide-y">
                  {books.map((b) => {
                    const active = selectedId === b.id;
                    return (
                      <li
                        key={b.id}
                        className={`p-4 cursor-pointer ${active ? "bg-indigo-50" : "bg-white"}`}
                        onClick={() => setSelectedId(b.id!)}
                      >
                        <div className="flex items-center justify-between">
                          <div>
                            <div className="font-medium">{b.name}</div>
                            <div className="text-xs text-gray-600">
                              {b.code} · {b.currency} · {b.is_active ? "Active" : "Inactive"}
                              {b.is_default ? " · Default" : ""}
                            </div>
                          </div>
                          <div className="flex items-center gap-2">
                            <button
                              onClick={(e) => {
                                e.stopPropagation();
                                updateBook({ ...b, is_active: !b.is_active });
                              }}
                              className="px-2 py-1 text-xs rounded border hover:bg-gray-50"
                            >
                              {b.is_active ? "Deactivate" : "Activate"}
                            </button>
                            <button
                              onClick={(e) => {
                                e.stopPropagation();
                                updateBook({ ...b, is_default: !b.is_default });
                              }}
                              className="px-2 py-1 text-xs rounded border hover:bg-gray-50"
                            >
                              {b.is_default ? "Unset Default" : "Set Default"}
                            </button>
                            <button
                              onClick={(e) => {
                                e.stopPropagation();
                                const code = prompt("Edit cost book code", b.code) ?? b.code;
                                const name = prompt("Rename cost book", b.name) ?? b.name;
                                updateBook({ ...b, code: code.trim(), name: name.trim() });
                              }}
                              className="px-2 py-1 text-xs rounded border hover:bg-gray-50"
                            >
                              Edit
                            </button>
                            <button
                              onClick={(e) => {
                                e.stopPropagation();
                                deleteBook(b.id!);
                              }}
                              className="px-2 py-1 text-xs rounded border text-rose-600 hover:bg-rose-50"
                            >
                              Delete
                            </button>
                          </div>
                        </div>
                      </li>
                    );
                  })}
                </ul>
              )}
            </div>
          </div>
        </div>

        {/* Right column — Details only */}
        <div className="lg:col-span-2 space-y-4">
          <div className="bg-white border rounded-2xl shadow-sm">
            <div className="px-4 py-3 border-b flex items-center justify-between">
              <h2 className="font-medium">Details</h2>
              {selected && (
                <div className="flex items-center gap-2">
                  <span
                    className={`text-xs px-2 py-1 rounded-full border ${
                      selected.is_active
                        ? "bg-emerald-50 text-emerald-700 border-emerald-200"
                        : "bg-gray-50 text-gray-600 border-gray-200"
                    }`}
                  >
                    Active
                  </span>
                  <span
                    className={`text-xs px-2 py-1 rounded-full border ${
                      selected.is_default
                        ? "bg-indigo-50 text-indigo-700 border-indigo-200"
                        : "bg-gray-50 text-gray-600 border-gray-200"
                    }`}
                  >
                    Default
                  </span>
                </div>
              )}
            </div>

            {selected ? (
              <>
                <div className="p-4 space-y-4">
                  <div className="grid grid-cols-1 md:grid-cols-4 gap-3">
                    <div>
                      <label className="block text-xs text-gray-600 mb-1">Code</label>
                      <input
                        className="w-full rounded-lg border px-3 py-2 text-sm"
                        value={selected.code}
                        onChange={(e) =>
                          setBooks((prev) => prev.map((b) => (b.id === selected.id ? { ...b, code: e.target.value } : b)))
                        }
                      />
                    </div>
                    <div className="md:col-span-2">
                      <label className="block text-xs text-gray-600 mb-1">Name</label>
                      <input
                        className="w-full rounded-lg border px-3 py-2 text-sm"
                        value={selected.name}
                        onChange={(e) =>
                          setBooks((prev) => prev.map((b) => (b.id === selected.id ? { ...b, name: e.target.value } : b)))
                        }
                      />
                    </div>
                    <div>
                      <label className="block text-xs text-gray-600 mb-1">Currency</label>
                      <input
                        className="w-full rounded-lg border px-3 py-2 text-sm"
                        value={selected.currency ?? ""}
                        onChange={(e) =>
                          setBooks((prev) =>
                            prev.map((b) => (b.id === selected.id ? { ...b, currency: e.target.value } : b))
                          )
                        }
                      />
                    </div>
                  </div>

                  <div className="flex items-center gap-4">
                    <label className="inline-flex items-center gap-2 text-sm">
                      <input
                        type="checkbox"
                        checked={selected.is_active}
                        onChange={(e) =>
                          setBooks((prev) =>
                            prev.map((b) => (b.id === selected.id ? { ...b, is_active: e.target.checked } : b))
                          )
                        }
                      />
                      Active
                    </label>
                    <label className="inline-flex items-center gap-2 text-sm">
                      <input
                        type="checkbox"
                        checked={selected.is_default}
                        onChange={(e) =>
                          setBooks((prev) =>
                            prev.map((b) => (b.id === selected.id ? { ...b, is_default: e.target.checked } : b))
                          )
                        }
                      />
                      Default
                    </label>
                  </div>
                </div>

                {/* Card footer actions (matches Price Books placement) */}
                <div className="px-4 pb-4 pt-2 flex items-center justify-end gap-2">
                  <button
                    onClick={() => {
                      setShowAddEntry((v) => !v);
                      setShowProdDropdown(false);
                      setProdFocused(false);
                    }}
                    disabled={!selected?.id}
                    className="inline-flex items-center rounded-lg border text-sm px-3 py-2 hover:bg-gray-50"
                  >
                    {showAddEntry ? "Cancel" : "Add Cost"}
                  </button>

                  <button
                    onClick={() => updateBook(selected)}
                    disabled={busy?.startsWith("update-book-")}
                    className="inline-flex items-center rounded-lg bg-indigo-600 text-white text-sm px-3 py-2 hover:bg-indigo-700 disabled:opacity-50"
                  >
                    {busy?.startsWith("update-book-") ? "Saving…" : "Save changes"}
                  </button>
                </div>
              </>
            ) : (
              <div className="p-6 text-sm text-gray-600">Select a cost book to manage entries.</div>
            )}
          </div>
        </div>
      </div>

      {/* Full-width Entries card (below the two-column section) */}
      <div className="bg-white border rounded-2xl shadow-sm">
        <div className="px-4 py-3 border-b">
          <h2 className="font-medium">Entries (Product costs)</h2>
        </div>

        {selected ? (
          <div className="p-4 space-y-4">
            {/* New entry row — shown when Add Cost is toggled */}
            {showAddEntry && (
              <div className="rounded-xl border border-dashed p-4 bg-gray-50">
                <div className="grid grid-cols-1 md:grid-cols-12 gap-3 items-end">
                  {/* Family */}
                  <div className="md:col-span-2">
                    <label className="block text-xs text-gray-600 mb-1">Family</label>
                    <select
                      className="w-full rounded-lg border px-3 py-2 text-sm"
                      value={entryFamilyId}
                      onChange={(e) => {
                        const v = e.target.value ? Number(e.target.value) : "";
                        setEntryFamilyId(v);
                        setEntryDraft((d) => ({ ...d, product_id: 0 }));
                        setProductQuery("");
                        setProductOptions([]);
                        setShowProdDropdown(false);
                        setProdFocused(false);
                      }}
                    >
                      <option value="">Select family…</option>
                      {families.map((f) => (
                        <option key={f.id} value={f.id}>
                          {f.name}
                        </option>
                      ))}
                    </select>
                  </div>

                  {/* Product (search-as-you-type) */}
                  <div className="md:col-span-4 relative" ref={prodBoxRef}>
                    <label className="block text-xs text-gray-600 mb-1">Product</label>
                    <input
                      className="w-full rounded-lg border px-3 py-2 text-sm"
                      placeholder={entryFamilyId ? "Search code or name…" : "Select a family first"}
                      value={productQuery}
                      onChange={(e) => setProductQuery(e.target.value)}
                      onFocus={() => {
                        setProdFocused(true);
                        if (entryFamilyId && productOptions.length) setShowProdDropdown(true);
                      }}
                      onBlur={() => {
                        setTimeout(() => {
                          setProdFocused(false);
                          if (!prodBoxRef.current?.contains(document.activeElement)) {
                            setShowProdDropdown(false);
                          }
                        }, 0);
                      }}
                      disabled={!entryFamilyId}
                    />
                    {showProdDropdown && (
                      <div className="absolute z-10 mt-1 w-full max-h-64 overflow-auto bg-white border rounded-lg shadow">
                        {prodBusy ? (
                          <div className="p-3 text-sm text-gray-600">Loading…</div>
                        ) : productOptions.length ? (
                          productOptions.map((p) => (
                            <div
                              key={p.id}
                              className="px-3 py-2 hover:bg-gray-50 cursor-pointer"
                              onMouseDown={(e) => e.preventDefault()}
                              onClick={() => {
                                setEntryDraft((d) => ({ ...d, product_id: p.id }));
                                setProductQuery(`${p.code} — ${p.name}`);
                                setShowProdDropdown(false);
                                setProdFocused(false);
                              }}
                            >
                              <div className="font-medium text-sm">
                                {p.code} — {p.name}
                              </div>
                              <div className="text-xs text-gray-500">
                                {families.find((f) => f.id === p.product_family_id)?.name || "—"}
                              </div>
                            </div>
                          ))
                        ) : (
                          <div className="p-3 text-sm text-gray-600">No products found.</div>
                        )}
                      </div>
                    )}
                  </div>

                  {/* Unit Cost */}
                  <div className="md:col-span-2">
                    <label className="block text-xs text-gray-600 mb-1">
                      Unit Cost ({selected.currency})
                    </label>
                    <input
                      type="number"
                      className="w-full rounded-lg border px-3 py-2 text-sm"
                      value={entryDraft.unit_cost}
                      onChange={(e) =>
                        setEntryDraft({ ...entryDraft, unit_cost: Number(e.target.value || 0) })
                      }
                    />
                  </div>

                  {/* Cost Term */}
                  <div className="md:col-span-2">
                    <label className="block text-xs text-gray-600 mb-1">Cost Term</label>
                    <select
                      className="w-full rounded-lg border px-3 py-2 text-sm"
                      value={entryDraft.cost_term_id ?? ""}
                      onChange={(e) =>
                        setEntryDraft({
                          ...entryDraft,
                          cost_term_id: e.target.value ? Number(e.target.value) : null,
                        })
                      }
                    >
                      <option value="">— none —</option>
                      {priceTerms.map((t) => (
                        <option key={t.id} value={t.id}>
                          {t.code}
                          {t.name ? ` — ${t.name}` : ""}
                        </option>
                      ))}
                    </select>
                  </div>

                  {/* Valid From */}
                  <div className="md:col-span-1">
                    <label className="block text-xs text-gray-600 mb-1">Valid From</label>
                    <input
                      type="date"
                      className="w-full rounded-lg border px-3 py-2 text-sm"
                      value={entryDraft.valid_from ?? ""}
                      onChange={(e) => setEntryDraft({ ...entryDraft, valid_from: e.target.value || null })}
                    />
                  </div>

                  {/* Valid To */}
                  <div className="md:col-span-1">
                    <label className="block text-xs text-gray-600 mb-1">Valid To</label>
                    <input
                      type="date"
                      className="w-full rounded-lg border px-3 py-2 text-sm"
                      value={entryDraft.valid_to ?? ""}
                      onChange={(e) => setEntryDraft({ ...entryDraft, valid_to: e.target.value || null })}
                    />
                  </div>

                  {/* Notes */}
                  <div className="md:col-span-12">
                    <label className="block text-xs text-gray-600 mb-1">Notes</label>
                    <input
                      className="w-full rounded-lg border px-3 py-2 text-sm"
                      value={entryDraft.notes ?? ""}
                      onChange={(e) => setEntryDraft({ ...entryDraft, notes: e.target.value })}
                      placeholder="Optional internal note"
                    />
                  </div>

                  {/* Add */}
                  <div className="md:col-span-12 flex md:justify-end">
                    <button
                      onClick={createEntry}
                      disabled={busy === "create-entry" || !entryDraft.product_id}
                      className="inline-flex items-center rounded-lg bg-indigo-600 text-white text-sm px-3 py-2 hover:bg-indigo-700 disabled:opacity-50"
                    >
                      {busy === "create-entry" ? "Adding…" : "Add entry"}
                    </button>
                  </div>
                </div>
              </div>
            )}

            {/* Entries table */}
            <div className="overflow-auto">
              <table className="min-w-full">
                <thead>
                  <tr className="bg-gray-50 text-left text-xs text-gray-600">
                    <th className="px-3 py-2 font-medium">Product</th>
                    <th className="px-3 py-2 font-medium">Unit Cost ({selected.currency})</th>
                    <th className="px-3 py-2 font-medium">Cost Term</th>
                    <th className="px-3 py-2 font-medium">Valid From</th>
                    <th className="px-3 py-2 font-medium">Valid To</th>
                    <th className="px-3 py-2 font-medium">Notes</th>
                    <th className="px-3 py-2"></th>
                  </tr>
                </thead>
                <tbody className="divide-y">
                  {entries.length === 0 ? (
                    <tr>
                      <td className="px-3 py-3 text-gray-600" colSpan={7}>
                        No entries yet.
                      </td>
                    </tr>
                  ) : (
                    entries.map((row) => (
                      <EntryRow
                        key={row.id}
                        row={row}
                        priceTerms={priceTerms}
                        currency={selected.currency}
                        familyLabel={familyNameOf(row.product_id)}
                        onSave={updateEntry}
                        onDelete={deleteEntry}
                      />
                    ))
                  )}
                </tbody>
              </table>
            </div>
          </div>
        ) : (
          <div className="p-6 text-sm text-gray-600">Select a cost book to see entries.</div>
        )}
      </div>
    </div>
  );
}

// ---------- Row component ----------
function EntryRow({
  row,
  priceTerms,
  currency,
  familyLabel,
  onSave,
  onDelete,
}: {
  row: CostBookEntry;
  priceTerms: PriceTermOpt[];
  currency: string;
  familyLabel?: string;
  onSave: (row: CostBookEntry) => void;
  onDelete: (row: CostBookEntry) => void;
}) {
  const [edit, setEdit] = useState<CostBookEntry>({ ...row });

  useEffect(() => {
    setEdit({ ...row });
  }, [row?.id]);

  return (
    <tr>
      <td className="px-3 py-2">
        {!!familyLabel && <div className="text-xs text-gray-500">{familyLabel}</div>}
        <div className="text-sm font-medium">
          {row.product_code || "—"} {row.product_name ? "— " + row.product_name : ""}
        </div>
        <div className="text-xs text-gray-400">#{row.product_id}</div>
      </td>
      <td className="px-3 py-2">
        <div className="flex items-center gap-2">
          <input
            type="number"
            className="w-32 rounded-lg border px-3 py-2 text-sm"
            value={edit.unit_cost}
            onChange={(e) => setEdit({ ...edit, unit_cost: Number(e.target.value || 0) })}
          />
          <span className="text-xs text-gray-500">{currency}</span>
        </div>
      </td>
      <td className="px-3 py-2">
        <select
          className="w-44 rounded-lg border px-3 py-2 text-sm"
          value={edit.cost_term_id ?? ""}
          onChange={(e) => setEdit({ ...edit, cost_term_id: e.target.value ? Number(e.target.value) : null })}
        >
          <option value="">{row.cost_term ? `(${row.cost_term})` : "— none —"}</option>
          {priceTerms.map((t) => (
            <option key={t.id} value={t.id}>
              {t.code}
              {t.name ? ` — ${t.name}` : ""}
            </option>
          ))}
        </select>
      </td>
      <td className="px-3 py-2">
        <input
          type="date"
          className="w-40 rounded-lg border px-3 py-2 text-sm"
          value={edit.valid_from ?? ""}
          onChange={(e) => setEdit({ ...edit, valid_from: e.target.value || null })}
        />
      </td>
      <td className="px-3 py-2">
        <input
          type="date"
          className="w-40 rounded-lg border px-3 py-2 text-sm"
          value={edit.valid_to ?? ""}
          onChange={(e) => setEdit({ ...edit, valid_to: e.target.value || null })}
        />
      </td>
      <td className="px-3 py-2">
        <input
          className="w-64 rounded-lg border px-3 py-2 text-sm"
          value={edit.notes ?? ""}
          onChange={(e) => setEdit({ ...edit, notes: e.target.value })}
          placeholder="Optional"
        />
      </td>
      <td className="px-3 py-2 text-right whitespace-nowrap">
        <button
          onClick={() => onSave(edit)}
          className="mr-2 px-3 py-2 text-sm rounded-lg bg-indigo-600 text-white hover:bg-indigo-700"
        >
          Save
        </button>
        <button
          onClick={() => onDelete(row)}
          className="px-3 py-2 text-sm rounded-lg border text-rose-600 hover:bg-rose-50"
        >
          Delete
        </button>
      </td>
    </tr>
  );
}
