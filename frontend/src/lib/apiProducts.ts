// src/lib/apiProducts.ts
import { apiGet, apiPost, apiPut, apiDelete, ApiError } from "./api";

// ---------- Types ----------
export type ProductFamily = {
  id: number;
  name: string;
  description?: string | null;
  is_active: 0 | 1;
};

export type Product = {
  id: number;
  code: string;
  name: string;
  description?: string | null;
  uom?: string | null;
  currency?: string | null;
  base_price?: number | null;
  tax_rate_pct?: number | null;
  barcode_gtin?: string | null;
  is_active: 0 | 1;
  metadata?: string | null;
  product_family_id?: number | null;
};

export type PriceBook = {
  id: number;
  name: string;
  currency?: string | null;
  is_active: 0 | 1;
  is_default: 0 | 1;
  valid_from?: string | null;
  valid_to?: string | null;
};

export type PriceBookEntry = {
  id: number;
  price_book_id: number;
  product_id: number;
  unit_price: number;
  currency?: string | null;
  valid_from?: string | null;
  valid_to?: string | null;
  is_active: 0 | 1;
  product_code?: string;
  product_name?: string;
};

// ---------- Price Terms ----------
export type PriceTerm = {
  id: number;
  code: string;
  name: string;
  description?: string | null;
  is_active: 0 | 1;
  sort_order?: number | null;
  // tolerate old UI fields if they exist in the form
  default_days?: number | null;
  notes?: string | null;
};

const PRICE_TERMS_BASES = ["/api/price-terms", "/api/price_terms"];

async function getWithFallback<T>(paths: string[]): Promise<T> {
  let lastErr: unknown;
  for (const p of paths) {
    try {
      return await apiGet<T>(p);
    } catch (e) {
      lastErr = e;
      if (e instanceof ApiError && (e.status === 404 || e.status === 405)) {
        continue; // try next candidate
      }
      throw e; // real error (401/403/500…) bubble up
    }
  }
  throw lastErr ?? new ApiError(404, "PriceTerms endpoint not found");
}

async function postWithFallback<T>(paths: string[], body: any): Promise<T> {
  let lastErr: unknown;
  for (const p of paths) {
    try {
      return await apiPost<T>(p, body);
    } catch (e) {
      lastErr = e;
      if (e instanceof ApiError && (e.status === 404 || e.status === 405)) continue;
      throw e;
    }
  }
  throw lastErr ?? new ApiError(404, "PriceTerms endpoint not found");
}

async function putWithFallback<T>(paths: string[], body: any): Promise<T> {
  let lastErr: unknown;
  for (const p of paths) {
    try {
      return await apiPut<T>(p, body);
    } catch (e) {
      lastErr = e;
      if (e instanceof ApiError && (e.status === 404 || e.status === 405)) continue;
      throw e;
    }
  }
  throw lastErr ?? new ApiError(404, "PriceTerms endpoint not found");
}

async function deleteWithFallback(paths: string[]): Promise<void> {
  let lastErr: unknown;
  for (const p of paths) {
    try {
      await apiDelete(p);
      return;
    } catch (e) {
      lastErr = e;
      if (e instanceof ApiError && (e.status === 404 || e.status === 405)) continue;
      throw e;
    }
  }
  throw lastErr ?? new ApiError(404, "PriceTerms endpoint not found");
}

export async function listPriceTerms(params?: { q?: string; active_only?: boolean; limit?: number; offset?: number }) {
  const u = new URLSearchParams();
  if (params?.q) u.set("q", params.q);
  if (params?.active_only !== undefined) u.set("active_only", String(params.active_only));
  if (params?.limit !== undefined) u.set("limit", String(params.limit));
  if (params?.offset !== undefined) u.set("offset", String(params.offset));
  const qs = u.toString() ? `?${u}` : "";
  return getWithFallback<PriceTerm[]>(PRICE_TERMS_BASES.map((b) => `${b}${qs}`));
}

export async function listPriceTermOptions() {
  return getWithFallback<Array<Pick<PriceTerm, "id" | "code" | "name">>>(
    PRICE_TERMS_BASES.map((b) => `${b}/options`)
  );
}

export async function getPriceTerm(termId: number) {
  return getWithFallback<PriceTerm>(PRICE_TERMS_BASES.map((b) => `${b}/${termId}`));
}

export async function getPriceTermByCode(code: string) {
  return getWithFallback<PriceTerm>(PRICE_TERMS_BASES.map((b) => `${b}/by-code/${encodeURIComponent(code)}`));
}

export async function createPriceTerm(payload: Partial<PriceTerm>) {
  // backend expects: code, name, description?, is_active?, sort_order?
  return postWithFallback<PriceTerm>(PRICE_TERMS_BASES, payload);
}

export async function updatePriceTerm(termId: number, payload: Partial<PriceTerm>) {
  return putWithFallback<PriceTerm>(PRICE_TERMS_BASES.map((b) => `${b}/${termId}`), payload);
}

export async function deletePriceTerm(termId: number, force = false) {
  const qs = force ? "?force=true" : "";
  return deleteWithFallback(PRICE_TERMS_BASES.map((b) => `${b}/${termId}${qs}`));
}

// ---------- Product Families ----------
export async function listProductFamilies(params?: { active?: boolean }) {
  const qs =
    params?.active === undefined ? "" : `?active=${params.active ? "true" : "false"}`;
  return apiGet<{ items: ProductFamily[] }>(`/api/product-families${qs}`);
}

export async function createProductFamily(payload: Partial<ProductFamily>) {
  return apiPost<{ id: number }>("/api/product-families", payload);
}

export async function updateProductFamily(id: number, payload: Partial<ProductFamily>) {
  return apiPut<{ updated: 1 | 0 }>(`/api/product-families/${id}`, payload);
}

export async function deleteProductFamily(id: number) {
  return apiDelete(`/api/product-families/${id}`) as Promise<{ deleted: boolean }>;
}

// ------------- Products ---------------
export async function listProducts(params?: {
  q?: string;
  active?: boolean;
  family_id?: number;
  limit?: number;
  offset?: number;
}) {
  const u = new URLSearchParams();
  if (params?.q) u.set("q", params.q);
  if (params?.active !== undefined) u.set("active", String(params.active));
  if (params?.family_id !== undefined) u.set("family_id", String(params.family_id));
  if (params?.limit !== undefined) u.set("limit", String(params.limit));
  if (params?.offset !== undefined) u.set("offset", String(params.offset));
  const qs = u.toString() ? `?${u}` : "";

  return apiGet<{ items: Product[]; total: number; limit: number; offset: number }>(
    `/api/products${qs}`
  );
}

export async function getProduct(id: number) {
  return apiGet<Product>(`/api/products/${id}`);
}

export async function createProduct(payload: Partial<Product>) {
  return apiPost<{ id: number }>("/api/products", payload);
}

export async function updateProduct(id: number, payload: Partial<Product>) {
  return apiPut<{ updated: 1 | 0 }>(`/api/products/${id}`, payload);
}

export async function deleteProduct(id: number, hard = false) {
  const qs = hard ? "?hard=true" : "";
  return apiDelete(`/api/products/${id}${qs}`) as Promise<{ deleted: boolean }>;
}

// ------------- Price Books ------------
export async function listPriceBooks(params?: { active?: boolean }) {
  const qs =
    params?.active === undefined ? "" : `?active=${params.active ? "true" : "false"}`;
  return apiGet<{ items: PriceBook[] }>(`/api/price-books${qs}`);
}

export async function listPriceBookEntries(bookId: number, productId?: number) {
  const qs = productId ? `?product_id=${productId}` : "";
  return apiGet<{ items: PriceBookEntry[] }>(`/api/price-books/${bookId}/entries${qs}`);
}

export async function createPriceBookEntry(
  bookId: number,
  payload: Partial<PriceBookEntry>
) {
  return apiPost<{ id: number }>(`/api/price-books/${bookId}/entries`, payload);
}

export async function updatePriceBookEntry(
  bookId: number,
  entryId: number,
  payload: Partial<PriceBookEntry>
) {
  return apiPut<{ updated: 1 | 0 }>(`/api/price-books/${bookId}/entries/${entryId}`, payload);
}

export async function deletePriceBookEntry(bookId: number, entryId: number) {
  return apiDelete(
    `/api/price-books/${bookId}/entries/${entryId}`
  ) as Promise<{ deleted: boolean }>;
}

// -------- Best Price Resolver ---------
export async function getBestPriceForProduct(
  productId: number,
  opts?: { on?: string; price_book_id?: number }
) {
  const u = new URLSearchParams();
  if (opts?.on) u.set("on", opts.on);
  if (opts?.price_book_id !== undefined) u.set("price_book_id", String(opts.price_book_id));
  const qs = u.toString() ? `?${u}` : "";

  return apiGet<{
    product_id: number;
    price_book_id: number;
    price_book_entry_id: number;
    unit_price: number;
    currency?: string | null;
    valid_from?: string | null;
    valid_to?: string | null;
  }>(`/api/products/${productId}/best-price${qs}`);
}
