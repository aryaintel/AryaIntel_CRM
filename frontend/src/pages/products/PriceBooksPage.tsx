// [BEGIN FILE] src/pages/products/PriceBooksPage.tsx
import React, { useEffect, useMemo, useRef, useState } from "react";
import { apiGet, apiPost, apiPut, apiDelete } from "../../lib/api";

/**
 * PriceBooksPage — Salesforce-style UI
 */

// ---------- Types ----------
type PriceBook = {
  id?: number;
  name: string;
  currency?: string | null;
  is_active: boolean;
  is_default: boolean;
  valid_from?: string | null;
  valid_to?: string | null;
};

type PriceBookEntry = {
  id?: number;
  price_book_id?: number;
  product_id: number;
  unit_price: number;
  currency?: string | null;
  valid_from?: string | null;
  valid_to?: string | null;
  is_active: boolean;
  product_code?: string | null;
  product_name?: string | null;

  // NEW: price term fields
  price_term_id?: number | null;
  price_term?: string | null; // code (read-only for display)
};

type ProductLite = {
  id: number;
  code: string;
  name: string;
  currency?: string | null;
  product_family_id?: number | null;
};

type ProductFamily = { id: number; name: string };

// NEW: Price term option
type PriceTermOpt = { id: number; code: string; name?: string | null; is_active?: boolean | number };

// ---------- Small utils ----------
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
  for (const p of paths) {
    try {
      const res = await apiGet(p);
      const items = unwrapList<T>(res);
      if (!Array.isArray(res) && items.length === 0 && res) {
        return { base: p, items: [res as T] };
      }
      return { base: p, items };
    } catch {}
  }
  throw new Error(`No reachable endpoint from: ${paths.join(", ")}`);
}
async function tryPost<T>(candidates: { url: string; body: any }[]): Promise<T> {
  let lastErr: any = null;
  for (const c of candidates) {
    try { return await apiPost(c.url, c.body); } catch (e) { lastErr = e; }
  }
  throw lastErr ?? new Error("POST failed for all candidates");
}
async function tryPut<T>(candidates: { url: string; body: any }[]): Promise<T> {
  let lastErr: any = null;
  for (const c of candidates) {
    try { return await apiPut(c.url, c.body); } catch (e) { lastErr = e; }
  }
  throw lastErr ?? new Error("PUT failed for all candidates");
}
async function tryDelete(candidates: string[]): Promise<void> {
  let lastErr: any = null;
  for (const url of candidates) {
    try { await apiDelete(url); return; } catch (e) { lastErr = e; }
  }
  throw lastErr ?? new Error("DELETE failed for all candidates");
}

// ---------- Page ----------
export default function PriceBooksPage() {
  // Discovery
  const [booksBase, setBooksBase] = useState<string | null>(null);
  const [entriesFlatBase, setEntriesFlatBase] = useState<string | null>(null);
  const [entriesNestedOk, setEntriesNestedOk] = useState<boolean>(true);

  // Data
  const [books, setBooks] = useState<PriceBook[]>([]);
  const [selectedId, setSelectedId] = useState<number | null>(null);
  const selected = useMemo(() => books.find((b) => b.id === selectedId) || null, [books, selectedId]);

  const [entries, setEntries] = useState<PriceBookEntry[]>([]);
  const [busy, setBusy] = useState<string | null>(null);
  const [err, setErr] = useState<string | null>(null);

  // Drafts
  const [draftBook, setDraftBook] = useState<PriceBook>({
    name: "",
    currency: "USD",
    is_active: true,
    is_default: false,
    valid_from: null,
    valid_to: null,
  });
  const [entryDraft, setEntryDraft] = useState<PriceBookEntry>({
    product_id: 0,
    unit_price: 0,
    currency: "",
    valid_from: null,
    valid_to: null,
    is_active: true,
    price_term_id: null, // NEW
  });

  // Families & product search
  const [families, setFamilies] = useState<ProductFamily[]>([]);
  const [entryFamilyId, setEntryFamilyId] = useState<number | "">("");

  const [productQuery, setProductQuery] = useState<string>("");
  const [productOptions, setProductOptions] = useState<ProductLite[]>([]);
  const [prodBusy, setProdBusy] = useState<boolean>(false);

  // Price terms (reference)
  const [priceTerms, setPriceTerms] = useState<PriceTermOpt[]>([]);

  // dropdown/focus management for Product
  const [showProdDropdown, setShowProdDropdown] = useState<boolean>(false);
  const [prodFocused, setProdFocused] = useState<boolean>(false);
  const prodBoxRef = useRef<HTMLDivElement | null>(null);

  // NEW: Only show the "Add new entry" row when explicitly requested
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

  // ---- Initial load (discover endpoints + first list) ----
  useEffect(() => {
    (async () => {
      setBusy("discover");
      setErr(null);
      try {
        const booksCandidates = ["/api/price-books", "/api/price_books"];
        const { base, items } = await tryGet<PriceBook>(booksCandidates);
        setBooks(items.map(normalizeBook));
        setBooksBase(base);
        if (items.length > 0 && items[0].id) setSelectedId(items[0].id);
      } catch (e: any) {
        setErr(e?.message || String(e));
      } finally {
        setBusy(null);
      }
    })();
  }, []);

  // Load families (for Entries form)
  useEffect(() => {
    (async () => {
      try {
        const fam = await apiGet("/api/product-families");
        setFamilies(unwrapList<ProductFamily>(fam));
      } catch {
        setFamilies([]);
      }
    })();
  }, []);

  // Load price term options (active-only endpoint)
  useEffect(() => {
    (async () => {
      try {
        const res =
          (await apiGet("/api/price-terms/options")) ??
          (await apiGet("/api/price_terms/options"));
        setPriceTerms(unwrapList<PriceTermOpt>(res));
      } catch {
        setPriceTerms([]);
      }
    })();
  }, []);

  // Reset the "Add Price" form visibility when switching books
  useEffect(() => {
    setShowAddEntry(false);
    setEntryFamilyId("");
    setEntryDraft((d) => ({ ...d, product_id: 0, price_term_id: null }));
    setProductQuery("");
    setProductOptions([]);
    setShowProdDropdown(false);
    setProdFocused(false);
  }, [selectedId]);

  // ---- Load entries when selection changes ----
  useEffect(() => {
    if (!selectedId || !booksBase) return;
    loadEntries(selectedId, booksBase).catch((e) => setErr(e?.message || String(e)));
  }, [selectedId, booksBase]);

  // ---- Normalizers ----
  function normalizeBook(b: any): PriceBook {
    return {
      id: b.id,
      name: b.name ?? "",
      currency: b.currency ?? null,
      is_active: toBool(b.is_active),
      is_default: toBool(b.is_default),
      valid_from: b.valid_from ?? null,
      valid_to: b.valid_to ?? null,
    };
  }
  function normalizeEntry(e: any): PriceBookEntry {
    return {
      id: e.id,
      price_book_id: e.price_book_id ?? e.priceBookId ?? e.book_id ?? undefined,
      product_id: e.product_id ?? e.productId,
      unit_price: Number(e.unit_price ?? e.unitPrice ?? 0),
      currency: e.currency ?? null,
      valid_from: e.valid_from ?? null,
      valid_to: e.valid_to ?? null,
      is_active: toBool(e.is_active),
      product_code: e.product_code ?? e.productCode ?? null,
      product_name: e.product_name ?? e.productName ?? null,
      // NEW:
      price_term_id: e.price_term_id ?? e.priceTermId ?? null,
      price_term: e.price_term ?? e.priceTerm ?? null,
    };
  }

  // ---- Loaders ----
  async function reloadBooks() {
    if (!booksBase) return;
    const res = await apiGet(booksBase);
    const list = unwrapList<PriceBook>(res).map(normalizeBook);
    setBooks(list);
    if (list.length && !list.find((b) => b.id === selectedId)) setSelectedId(list[0].id!);
  }

  async function loadEntries(bookId: number, base: string) {
    setBusy("entries");
    try {
      const nestedUrl = `${base}/${bookId}/entries`;
      try {
        const resNested = await apiGet(nestedUrl);
        setEntries(unwrapList<PriceBookEntry>(resNested).map(normalizeEntry));
        setEntriesNestedOk(true);
        return;
      } catch {
        setEntriesNestedOk(false);
      }
      const flatBases = ["/api/price-book-entries", "/api/price_book_entries"];
      const { base: flatBase, items } = await tryGet<PriceBookEntry>(
        flatBases.map((p) => `${p}?price_book_id=${bookId}`)
      );
      setEntries(items.map(normalizeEntry));
      setEntriesFlatBase(flatBases.find((p) => flatBase.startsWith(p)) || flatBases[0]);
    } finally {
      setBusy(null);
    }
  }

  // ---- Mutations: Books ----
  async function createBook() {
    if (!booksBase) return;
    setBusy("create-book"); setErr(null);
    try {
      const body = { ...draftBook, is_active: draftBook.is_active ? 1 : 0, is_default: draftBook.is_default ? 1 : 0 };
      await apiPost(booksBase, body);
      await reloadBooks();
      // After creating a book, keep the entries form hidden
      setShowAddEntry(false);
      setDraftBook({ name: "", currency: "USD", is_active: true, is_default: false, valid_from: null, valid_to: null });
    } catch (e: any) {
      setErr(e?.message || String(e));
    } finally {
      setBusy(null);
    }
  }
  async function updateBook(b: PriceBook) {
    if (!booksBase || !b.id) return;
    setBusy(`update-book-${b.id}`); setErr(null);
    try {
      const body = { ...b, is_active: b.is_active ? 1 : 0, is_default: b.is_default ? 1 : 0 };
      await apiPut(`${booksBase}/${b.id}`, body);
      await reloadBooks();
    } catch (e: any) {
      setErr(e?.message || String(e));
    } finally {
      setBusy(null);
    }
  }
  async function deleteBook(id: number) {
    if (!booksBase) return;
    if (!confirm("Delete this price book? This action cannot be undone.")) return;
    setBusy(`delete-book-${id}`); setErr(null);
    try {
      await apiDelete(`${booksBase}/${id}`);
      await reloadBooks();
      if (selectedId === id) { setSelectedId(null); setEntries([]); }
    } catch (e: any) {
      setErr(e?.message || String(e));
    } finally { setBusy(null); }
  }

  // ---- Mutations: Entries ----
  async function createEntry() {
    if (!selected || !selected.id || !booksBase) return;
    if (!entryDraft.product_id) { alert("Please choose a product."); return; }
    setBusy("create-entry"); setErr(null);
    try {
      const body = {
        ...entryDraft,
        price_book_id: selected.id,
        is_active: entryDraft.is_active ? 1 : 0,
        // ensure only id is sent (code is derived on server)
        price_term: undefined,
      };
      const candidates = [
        { url: `${booksBase}/${selected.id}/entries`, body },
        { url: `/api/price-book-entries`, body },
        { url: `/api/price_book_entries`, body },
      ];
      await tryPost(candidates);
      await loadEntries(selected.id, booksBase);
      // Reset form but keep the panel open so user can add multiple
      setEntryDraft({
        product_id: 0,
        unit_price: 0,
        currency: selected.currency ?? "",
        valid_from: null,
        valid_to: null,
        is_active: true,
        price_term_id: null,
      });
      setProductQuery(""); setProductOptions([]); setShowProdDropdown(false); setProdFocused(false);
    } catch (e: any) {
      setErr(e?.message || String(e));
    } finally { setBusy(null); }
  }
  async function updateEntry(row: PriceBookEntry) {
    if (!selected || !selected.id || !booksBase || !row.id) return;
    setBusy(`update-entry-${row.id}`); setErr(null);
    try {
      const body = {
        ...row,
        is_active: row.is_active ? 1 : 0,
        price_book_id: selected.id,
        price_term: undefined, // do not send code on update
      };
      const candidates = [
        { url: `${booksBase}/${selected.id}/entries/${row.id}`, body },
        { url: `${entriesFlatBase ?? "/api/price-book-entries"}/${row.id}`, body },
      ];
      await tryPut(candidates);
      await loadEntries(selected.id, booksBase);
    } catch (e: any) {
      setErr(e?.message || String(e));
    } finally { setBusy(null); }
  }
  async function deleteEntry(row: PriceBookEntry) {
    if (!selected || !selected.id || !booksBase || !row.id) return;
    if (!confirm("Delete this entry?")) return;
    setBusy(`delete-entry-${row.id}`); setErr(null);
    try {
      const candidates = [
        `${booksBase}/${selected.id}/entries/${row.id}`,
        `${entriesFlatBase ?? "/api/price-book-entries"}/${row.id}`,
        `/api/price_book_entries/${row.id}`,
      ];
      await tryDelete(candidates);
      await loadEntries(selected.id, booksBase);
    } catch (e: any) {
      setErr(e?.message || String(e));
    } finally { setBusy(null); }
  }

  // ---- Product search (limited by Family) ----
  async function searchProducts(q: string, familyId: number | "" = entryFamilyId) {
    setProdBusy(true);
    try {
      const params = new URLSearchParams();
      params.set("limit", "50");
      if (q) params.set("q", q);
      if (familyId) params.set("family_id", String(familyId));
      const url = `/api/products?${params.toString()}`;
      const res = await apiGet(url);
      setProductOptions(unwrapList<ProductLite>(res));

      // Only open the dropdown if the input is actually focused
      setShowProdDropdown(!!prodFocused && !!entryFamilyId);
    } finally { setProdBusy(false); }
  }

  // Search only when: family is selected AND the input is focused
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

  // ---- Render ----
  return (
    <div className="space-y-4">
      {/* Page header */}
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-semibold text-gray-900">Price Books</h1>
        <p className="text-sm text-gray-600">Manage price books and product prices for quoting and BOQ.</p>
        </div>
        <div className="text-sm text-gray-600">
          {busy ? <span className="px-2 py-1 rounded bg-amber-50 text-amber-700 border border-amber-200">Working: {busy}</span> : null}
          {err ? <span className="ml-2 px-2 py-1 rounded bg-rose-50 text-rose-700 border border-rose-200">Error: {err}</span> : null}
        </div>
      </div>

      <div className="grid grid-cols-1 xl:grid-cols-3 gap-4">
        {/* LEFT: Create + List */}
        <div className="xl:col-span-1 space-y-4">
          {/* Create Card */}
          <div className="bg-white border rounded-2xl shadow-sm">
            <div className="px-4 py-3 border-b">
              <h2 className="font-medium">New Price Book</h2>
            </div>
            <div className="p-4 space-y-3">
              <div className="grid grid-cols-2 gap-3">
                <div className="col-span-2">
                  <label className="block text-xs text-gray-600 mb-1">Name</label>
                  <input
                    className="w-full rounded-lg border px-3 py-2 text-sm"
                    placeholder="e.g., 2025 Global List"
                    value={draftBook.name}
                    onChange={(e) => setDraftBook({ ...draftBook, name: e.target.value })}
                  />
                </div>
                <div>
                  <label className="block text-xs text-gray-600 mb-1">Currency</label>
                  <input
                    className="w-full rounded-lg border px-3 py-2 text-sm"
                    value={draftBook.currency ?? ""}
                    onChange={(e) => setDraftBook({ ...draftBook, currency: e.target.value })}
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
                <div>
                  <label className="block text-xs text-gray-600 mb-1">Valid From</label>
                  <input
                    type="date"
                    className="w-full rounded-lg border px-3 py-2 text-sm"
                    value={draftBook.valid_from ?? ""}
                    onChange={(e) => setDraftBook({ ...draftBook, valid_from: e.target.value || null })}
                  />
                </div>
                <div>
                  <label className="block text-xs text-gray-600 mb-1">Valid To</label>
                  <input
                    type="date"
                    className="w-full rounded-lg border px-3 py-2 text-sm"
                    value={draftBook.valid_to ?? ""}
                    onChange={(e) => setDraftBook({ ...draftBook, valid_to: e.target.value || null })}
                  />
                </div>
              </div>
              <button
                onClick={createBook}
                disabled={busy !== null || !draftBook.name.trim()}
                className="inline-flex items-center justify-center rounded-lg bg-indigo-600 text-white text-sm px-3 py-2 hover:bg-indigo-700 disabled:opacity-50"
              >
                Add Price Book
              </button>
            </div>
          </div>

          {/* List Card */}
          <div className="bg-white border rounded-2xl shadow-sm">
            <div className="px-4 py-3 border-b">
              <h2 className="font-medium">Price Books</h2>
            </div>
            <div>
              {books.length === 0 ? (
                <div className="p-4 text-sm text-gray-600">No price books yet.</div>
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
                              {b.currency ?? "-"} · {b.is_active ? "Active" : "Inactive"}
                              {b.is_default ? " · Default" : ""}
                            </div>
                            <div className="text-xs text-gray-500">
                              {b.valid_from ? `From ${b.valid_from}` : "From —"} • {b.valid_to ? `To ${b.valid_to}` : "To —"}
                            </div>
                          </div>
                          <div className="flex gap-2">
                            <button
                              onClick={(e) => { e.stopPropagation(); updateBook({ ...b, is_active: !b.is_active }); }}
                              className="px-2 py-1 text-xs rounded border hover:bg-gray-50"
                            >
                              {b.is_active ? "Deactivate" : "Activate"}
                            </button>
                            <button
                              onClick={(e) => { e.stopPropagation(); updateBook({ ...b, is_default: !b.is_default }); }}
                              className="px-2 py-1 text-xs rounded border hover:bg-gray-50"
                            >
                              {b.is_default ? "Unset Default" : "Set Default"}
                            </button>
                            <button
                              onClick={(e) => {
                                e.stopPropagation();
                                const name = prompt("Rename price book", b.name);
                                if (name && name.trim()) updateBook({ ...b, name: name.trim() });
                              }}
                              className="px-2 py-1 text-xs rounded border hover:bg-gray-50"
                            >
                              Rename
                            </button>
                            <button
                              onClick={(e) => { e.stopPropagation(); deleteBook(b.id!); }}
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

        {/* RIGHT: Details + Entries */}
        <div className="xl:col-span-2 space-y-4">
          {/* Details Card */}
          <div className="bg-white border rounded-2xl shadow-sm">
            <div className="px-4 py-3 border-b flex items-center justify-between">
              <h2 className="font-medium">Details</h2>
              {selected ? (
                <div className="flex items-center gap-3 text-xs">
                  <span className={`px-2 py-1 rounded-full border ${selected.is_active ? "bg-green-50 text-green-700 border-green-200" : "bg-gray-50 text-gray-700 border-gray-200"}`}>
                    {selected.is_active ? "Active" : "Inactive"}
                  </span>
                  {selected.is_default ? (
                    <span className="px-2 py-1 rounded-full border bg-indigo-50 text-indigo-700 border-indigo-200">Default</span>
                  ) : null}
                </div>
              ) : null}
            </div>
            {selected ? (
              <div className="p-4 space-y-4">
                <div className="grid grid-cols-1 md:grid-cols-4 gap-3">
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
                        setBooks((prev) => prev.map((b) => (b.id === selected.id ? { ...b, currency: e.target.value } : b)))
                      }
                    />
                  </div>
                  <div>
                    <label className="block text-xs text-gray-600 mb-1">Valid From</label>
                    <input
                      type="date"
                      className="w-full rounded-lg border px-3 py-2 text-sm"
                      value={selected.valid_from ?? ""}
                      onChange={(e) =>
                        setBooks((prev) => prev.map((b) => (b.id === selected.id ? { ...b, valid_from: e.target.value || null } : b)))
                      }
                    />
                  </div>
                  <div>
                    <label className="block text-xs text-gray-600 mb-1">Valid To</label>
                    <input
                      type="date"
                      className="w-full rounded-lg border px-3 py-2 text-sm"
                      value={selected.valid_to ?? ""}
                      onChange={(e) =>
                        setBooks((prev) => prev.map((b) => (b.id === selected.id ? { ...b, valid_to: e.target.value || null } : b)))
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
                        setBooks((prev) => prev.map((b) => (b.id === selected.id ? { ...b, is_active: e.target.checked } : b)))
                      }
                    />
                    Active
                  </label>
                  <label className="inline-flex items-center gap-2 text-sm">
                    <input
                      type="checkbox"
                      checked={selected.is_default}
                      onChange={(e) =>
                        setBooks((prev) => prev.map((b) => (b.id === selected.id ? { ...b, is_default: e.target.checked } : b)))
                      }
                    />
                    Default
                  </label>

                  <div className="ml-auto flex items-center gap-2">
                    {/* NEW: Add Price button lives in Details card */}
                    <button
                      onClick={() => {
                        setShowAddEntry((v) => !v);
                        // Reset dropdown/focus state when toggling panel
                        setShowProdDropdown(false);
                        setProdFocused(false);
                      }}
                      disabled={!selected?.id}
                      className={`inline-flex items-center rounded-lg text-sm px-3 py-2 border ${showAddEntry ? "bg-gray-50" : "bg-indigo-600 text-white hover:bg-indigo-700"} `}
                    >
                      {showAddEntry ? "Cancel" : "Add Price"}
                    </button>

                    <button
                      onClick={() => updateBook(selected)}
                      disabled={busy?.startsWith("update-book-")}
                      className="inline-flex items-center rounded-lg bg-indigo-600 text-white text-sm px-3 py-2 hover:bg-indigo-700 disabled:opacity-50"
                    >
                      {busy?.startsWith("update-book-") ? "Saving…" : "Save changes"}
                    </button>
                  </div>
                </div>
              </div>
            ) : (
              <div className="p-6 text-sm text-gray-600">Select a price book to manage entries.</div>
            )}
          </div>

          {/* Entries Card */}
          <div className="bg-white border rounded-2xl shadow-sm">
            <div className="px-4 py-3 border-b">
              <h2 className="font-medium">Entries (Product prices)</h2>
            </div>
            {selected ? (
              <div className="p-4 space-y-4">
                {/* New entry row — ONLY when user clicked Add Price */}
                {showAddEntry && (
                  <div className="rounded-xl border border-dashed p-4 bg-gray-50">
                    <div className="grid grid-cols-1 md:grid-cols-12 gap-3 items-end">
                      {/* Family (2) */}
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
                            <option key={f.id} value={f.id}>{f.name}</option>
                          ))}
                        </select>
                      </div>

                      {/* Product (4) */}
                      <div ref={prodBoxRef} className="relative md:col-span-4 min-w-0">
                        <label className="block text-xs text-gray-600 mb-1">Product</label>
                        <input
                          className="w-full rounded-lg border px-3 py-2 text-sm"
                          placeholder={entryFamilyId ? "Search product…" : "Select a family first"}
                          value={productQuery}
                          onChange={(e) => setProductQuery(e.target.value)}
                          onFocus={() => {
                            setProdFocused(true);
                            if (entryFamilyId && productOptions.length) setShowProdDropdown(true);
                          }}
                          onBlur={() => {
                            // keep handled by outside click, but close on blur when nothing is clicked
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
                                  onMouseDown={(e) => e.preventDefault()} // prevent input blur before we handle click
                                  onClick={() => {
                                    setEntryDraft((d) => ({ ...d, product_id: p.id, currency: p.currency ?? selected.currency ?? "" }));
                                    setProductQuery(`${p.code} — ${p.name}`);
                                    setShowProdDropdown(false);
                                    setProdFocused(false);
                                  }}
                                >
                                  <div className="text-sm font-medium">{p.code}</div>
                                  <div className="text-xs text-gray-600 truncate">{p.name}</div>
                                </div>
                              ))
                            ) : (
                              <div className="p-3 text-sm text-gray-600">No results.</div>
                            )}
                          </div>
                        )}
                      </div>

                      {/* Unit Price (1) */}
                      <div className="md:col-span-1">
                        <label className="block text-xs text-gray-600 mb-1">Unit Price</label>
                        <input
                          type="number"
                          className="w-full rounded-lg border px-3 py-2 text-sm"
                          value={entryDraft.unit_price}
                          onChange={(e) => setEntryDraft({ ...entryDraft, unit_price: Number(e.target.value || 0) })}
                        />
                      </div>

                      {/* Currency (1) */}
                      <div className="md:col-span-1">
                        <label className="block text-xs text-gray-600 mb-1">Currency</label>
                        <input
                          className="w-full rounded-lg border px-3 py-2 text-sm"
                          value={entryDraft.currency ?? ""}
                          onChange={(e) => setEntryDraft({ ...entryDraft, currency: e.target.value })}
                        />
                      </div>

                      {/* Price Term (2) NEW */}
                      <div className="md:col-span-2">
                        <label className="block text-xs text-gray-600 mb-1">Price Term</label>
                        <select
                          className="w-full rounded-lg border px-3 py-2 text-sm"
                          value={entryDraft.price_term_id ?? ""}
                          onChange={(e) =>
                            setEntryDraft({ ...entryDraft, price_term_id: e.target.value ? Number(e.target.value) : null })
                          }
                        >
                          <option value="">— none —</option>
                          {priceTerms.map((t) => (
                            <option key={t.id} value={t.id}>
                              {t.code}{t.name ? ` — ${t.name}` : ""}
                            </option>
                          ))}
                        </select>
                      </div>

                      {/* Valid From (1) */}
                      <div className="md:col-span-1">
                        <label className="block text-xs text-gray-600 mb-1">Valid From</label>
                        <input
                          type="date"
                          className="w-full rounded-lg border px-3 py-2 text-sm"
                          value={entryDraft.valid_from ?? ""}
                          onChange={(e) => setEntryDraft({ ...entryDraft, valid_from: e.target.value || null })}
                        />
                      </div>

                      {/* Valid To (1) */}
                      <div className="md:col-span-1">
                        <label className="block text-xs text-gray-600 mb-1">Valid To</label>
                        <input
                          type="date"
                          className="w-full rounded-lg border px-3 py-2 text-sm"
                          value={entryDraft.valid_to ?? ""}
                          onChange={(e) => setEntryDraft({ ...entryDraft, valid_to: e.target.value || null })}
                        />
                      </div>

                      {/* Active (1) */}
                      <div className="md:col-span-1 flex items-center justify-center">
                        <label className="inline-flex items-center gap-2 text-sm">
                          <input
                            type="checkbox"
                            checked={entryDraft.is_active}
                            onChange={(e) => setEntryDraft({ ...entryDraft, is_active: e.target.checked })}
                          />
                          <span className="hidden md:inline">Active</span>
                        </label>
                      </div>

                      {/* Add (1) */}
                      <div className="md:col-span-1 flex md:justify-end">
                        <button
                          onClick={createEntry}
                          disabled={busy === "create-entry" || !entryDraft.product_id}
                          className="inline-flex items-center justify-center rounded-lg bg-indigo-600 text-white text-sm px-3 py-2 hover:bg-indigo-700 disabled:opacity-50"
                        >
                          {busy === "create-entry" ? "Saving…" : "Add"}
                        </button>
                      </div>
                    </div>
                  </div>
                )}

                {/* Table */}
                <div className="overflow-auto rounded-xl border">
                  <table className="min-w-full text-sm">
                    <thead className="bg-gray-50">
                      <tr className="text-left">
                        <th className="px-3 py-2 font-medium">Product</th>
                        <th className="px-3 py-2 font-medium">Unit Price</th>
                        <th className="px-3 py-2 font-medium">Currency</th>
                        <th className="px-3 py-2 font-medium">Price Term</th>
                        <th className="px-3 py-2 font-medium">Valid From</th>
                        <th className="px-3 py-2 font-medium">Valid To</th>
                        <th className="px-3 py-2 font-medium">Active</th>
                        <th className="px-3 py-2"></th>
                      </tr>
                    </thead>
                    <tbody className="divide-y">
                      {entries.length === 0 ? (
                        <tr><td className="px-3 py-3 text-gray-600" colSpan={8}>No entries yet.</td></tr>
                      ) : (
                        entries.map((row) => (
                          <EntryRow
                            key={row.id}
                            row={row}
                            priceTerms={priceTerms}
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
              <div className="p-6 text-sm text-gray-600">Select a price book to see entries.</div>
            )}
          </div>
        </div>
      </div>
    </div>
  );
}

// ---------- Row component ----------
function EntryRow({
  row, onSave, onDelete, priceTerms,
}: {
  row: PriceBookEntry;
  onSave: (row: PriceBookEntry) => void;
  onDelete: (row: PriceBookEntry) => void;
  priceTerms: PriceTermOpt[];
}) {
  const [edit, setEdit] = useState<PriceBookEntry>({ ...row });
  useEffect(() => setEdit({ ...row }), [row]);

  return (
    <tr className="align-middle">
      <td className="px-3 py-2">
        <div className="font-mono text-xs">{row.product_code ?? row.product_id}</div>
        <div className="text-xs text-gray-600">{row.product_name ?? ""}</div>
      </td>
      <td className="px-3 py-2">
        <input
          type="number"
          className="w-32 rounded-lg border px-3 py-2 text-sm"
          value={edit.unit_price}
          onChange={(e) => setEdit({ ...edit, unit_price: Number(e.target.value || 0) })}
        />
      </td>
      <td className="px-3 py-2">
        <input
          className="w-28 rounded-lg border px-3 py-2 text-sm"
          value={edit.currency ?? ""}
          onChange={(e) => setEdit({ ...edit, currency: e.target.value })}
        />
      </td>
      {/* NEW: price term select */}
      <td className="px-3 py-2">
        <select
          className="w-44 rounded-lg border px-3 py-2 text-sm"
          value={edit.price_term_id ?? ""}
          onChange={(e) =>
            setEdit({ ...edit, price_term_id: e.target.value ? Number(e.target.value) : null })
          }
        >
          <option value="">
            {row.price_term ? `(${row.price_term})` : "— none —"}
          </option>
          {priceTerms.map((t) => (
            <option key={t.id} value={t.id}>
              {t.code}{t.name ? ` — ${t.name}` : ""}
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
          type="checkbox"
          checked={!!edit.is_active}
          onChange={(e) => setEdit({ ...edit, is_active: e.target.checked })}
        />
      </td>
      <td className="px-3 py-2 whitespace-nowrap">
        <button
          onClick={() => onSave(edit)}
          className="mr-2 px-3 py-2 text-sm rounded-lg border hover:bg-gray-50"
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
// [END FILE]
