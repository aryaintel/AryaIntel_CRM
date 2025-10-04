// frontend/src/pages/scenario/api/indexSeries.ts
// API wrapper aligned with backend /api/index-series routes

import { apiGet, apiPost, apiPut, apiDelete } from "../../../lib/api";

/* ========== Types (BE-aligned) ========== */
export type IndexSeries = {
  id: number;
  code: string;
  name: string;
  unit?: string | null;
  country?: string | null;
  currency?: string | null;
  source?: string | null;
  fetch_adapter?: string | null;
  fetch_config?: string | null | Record<string, unknown>;
  is_active?: boolean;
  description?: string | null;
};

export type IndexSeriesCreate = {
  code: string;
  name: string;
  unit?: string | null;
  country?: string | null;
  currency?: string | null;
  source?: string | null;
  fetch_adapter?: string | null;
  fetch_config?: string | null | Record<string, unknown>;
  is_active?: boolean;
  description?: string | null;
};

export type IndexSeriesUpdate = Partial<IndexSeriesCreate>;

export type Paginated<T> = {
  items: T[];
  count: number;
  limit: number;
  offset: number;
};

export type IndexPoint = {
  ym: string;               // "YYYY-MM" (used by FE single-upsert/delete)
  value: number;
  source_ref?: string | null;
};

export type IndexPointBulkItem = {
  year: number;
  month: number;            // 1..12
  value: number;
  source_ref?: string | null;
};

/** When BE returns year/month instead of ym (list endpoints) */
export type RawPoint = {
  ym?: string;
  year?: number;
  month?: number;
  value: number;
  source_ref?: string | null;
};

/* ========== Helpers ========== */
export function toYM(year: number, month: number): string {
  return `${year}-${String(month).padStart(2, "0")}`;
}
export function fromYM(ym: string): { year: number; month: number } {
  const [y, m] = ym.split("-").map(Number);
  return { year: y, month: m };
}

/* ========== Base ========== */
const BASE = "/api/index-series";

/* ========== Series endpoints ========== */

export async function listSeries(params?: {
  q?: string;
  source?: string;
  country?: string;
  currency?: string;
  is_active?: boolean;
  limit?: number;
  offset?: number;
}): Promise<Paginated<IndexSeries>> {
  const usp = new URLSearchParams();
  if (params) {
    Object.entries(params).forEach(([k, v]) => {
      if (v !== undefined && v !== null && v !== "") usp.append(k, String(v));
    });
  }
  const qs = usp.toString();
  return apiGet<Paginated<IndexSeries>>(`${BASE}${qs ? `?${qs}` : ""}`);
}

export async function createSeries(payload: IndexSeriesCreate): Promise<IndexSeries> {
  // BE returns { id }; fetch full object afterwards for the UI
  const created = await apiPost<{ id: number }>(`${BASE}`, payload);
  return getSeries(created.id);
}

export function getSeries(id: number): Promise<IndexSeries> {
  return apiGet<IndexSeries>(`${BASE}/${id}`);
}

export async function updateSeries(id: number, payload: IndexSeriesUpdate): Promise<IndexSeries> {
  await apiPut(`${BASE}/${id}`, payload); // BE returns {updated:true}, we re-fetch
  return getSeries(id);
}

/* ========== Points endpoints ========== */

export async function listPoints(
  seriesId: number,
  params?: { limit?: number; offset?: number; date_from?: string; date_to?: string }
): Promise<Paginated<RawPoint>> {
  const usp = new URLSearchParams();
  if (params?.limit != null) usp.set("limit", String(params.limit));
  if (params?.offset != null) usp.set("offset", String(params.offset));
  if (params?.date_from) usp.set("date_from", params.date_from); // YYYY-MM
  if (params?.date_to) usp.set("date_to", params.date_to);       // YYYY-MM
  const qs = usp.toString();
  return apiGet<Paginated<RawPoint>>(`${BASE}/${seriesId}/points${qs ? `?${qs}` : ""}`);
}

export function upsertPoint(
  seriesId: number,
  point: { ym: string; value: number; source_ref?: string | null }
): Promise<{ series_id: number; ym: string; value: number }> {
  return apiPost(`${BASE}/${seriesId}/points:upsert`, point);
}

export function bulkUpsertPoints(
  seriesId: number,
  points: IndexPointBulkItem[]
): Promise<{ series_id: number; upserted: number }> {
  return apiPost(`${BASE}/${seriesId}/points:bulk-upsert`, { points });
}

export async function deletePointByYM(
  seriesId: number,
  ym: string
): Promise<void> {
  const qs = `?ym=${encodeURIComponent(ym)}`;
  await apiDelete(`${BASE}/${seriesId}/points${qs}`);
}