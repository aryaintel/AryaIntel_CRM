// frontend/src/pages/scenario/api/indexSeries.ts
// v1.0.5 backend kontratına uyumlu ince API sarmalı
import { apiGet, apiPost, apiPut, apiDelete } from "../../../lib/api";

/* =========================
   Types (BE-aligned)
========================= */
export type IndexSeries = {
  id: number;
  code: string;                 // ZORUNLU
  name: string;                 // ZORUNLU
  unit?: string | null;
  country?: string | null;
  currency?: string | null;
  source?: string | null;
  fetch_adapter?: string | null;
  fetch_config?: Record<string, unknown> | null;
  is_active?: boolean;
  description?: string | null;  // varsa
};

export type IndexSeriesCreate = {
  code: string;
  name: string;
  unit?: string | null;
  country?: string | null;
  currency?: string | null;
  source?: string | null;
  fetch_adapter?: string | null;
  fetch_config?: Record<string, unknown> | null;
  is_active?: boolean;
  description?: string | null;
};

export type IndexSeriesUpdate = Partial<IndexSeriesCreate>;

export type IndexPoint = {
  // BE tekil upsert & delete için "ym" (YYYY-MM) kullanır
  ym: string;                 // "YYYY-MM"
  value: number;
  source_ref?: string | null;
};

export type IndexPointBulkItem = {
  year: number;               // 1900..3000
  month: number;              // 1..12
  value: number;
  source_ref?: string | null;
};

export type Paginated<T> = {
  items: T[];
  count: number;
  limit: number;
  offset: number;
};

/* =========================
   Helpers
========================= */
export function toYM(year: number, month: number): string {
  const m = String(month).padStart(2, "0");
  return `${year}-${m}`;
}

export function fromYM(ym: string): { year: number; month: number } {
  const [y, m] = ym.split("-");
  return { year: Number(y), month: Number(m) };
}

/* =========================
   API Calls
========================= */

// List series (supports filters in v1.0.5)
export async function listSeries(params?: {
  q?: string;
  source?: string;
  country?: string;
  currency?: string;
  is_active?: boolean;
  limit?: number;
  offset?: number;
}): Promise<Paginated<IndexSeries>> {
  const query = new URLSearchParams();
  if (params) {
    for (const [k, v] of Object.entries(params)) {
      if (v !== undefined && v !== null && v !== "") {
        query.append(k, String(v));
      }
    }
  }
  const qs = query.toString();
  return apiGet(`/api/index-series${qs ? `?${qs}` : ""}`);
}

// Create / Get / Update series
export async function createSeries(payload: IndexSeriesCreate): Promise<IndexSeries> {
  return apiPost("/api/index-series", payload);
}

export async function getSeries(sid: number): Promise<IndexSeries> {
  return apiGet(`/api/index-series/${sid}`);
}

export async function updateSeries(sid: number, payload: IndexSeriesUpdate): Promise<IndexSeries> {
  return apiPut(`/api/index-series/${sid}`, payload);
}

// Points: list (paginated envelope)
export async function listPoints(
  sid: number,
  params?: { limit?: number; offset?: number }
): Promise<Paginated<IndexPoint>> {
  const query = new URLSearchParams();
  if (params?.limit != null) query.set("limit", String(params.limit));
  if (params?.offset != null) query.set("offset", String(params.offset));
  const qs = query.toString();
  return apiGet(`/api/index-series/${sid}/points${qs ? `?${qs}` : ""}`);
}

// Single upsert: expects { ym, value, source_ref? }
export async function upsertPoint(
  sid: number,
  point: IndexPoint
): Promise<{ ok: true }> {
  return apiPost(`/api/index-series/${sid}/points:upsert`, point);
}

// Bulk upsert: expects { points: [...] }
export async function bulkUpsertPoints(
  sid: number,
  points: IndexPointBulkItem[]
): Promise<{ ok: true; inserted: number; updated: number }> {
  return apiPost(`/api/index-series/${sid}/points:bulk-upsert`, { points });
}

// Delete by ym (YYYY-MM) — apiDelete genelde 'void' döner
export async function deletePointByYM(
  sid: number,
  ym: string
): Promise<void> {
  const qs = `?ym=${encodeURIComponent(ym)}`;
  await apiDelete(`/api/index-series/${sid}/points${qs}`);
}

/* =========================
   Usage Notes
========================= */
/*
- createSeries: code & name zorunlu; aynı code için 409 dönebilir → FE'de yakala.
- upsertPoint: ym formatı "YYYY-MM"; 400 olursa tarih/format kontrol et.
- bulkUpsertPoints: {points:[{year,month,value,...}]} zarfı zorunlu.
- listSeries/listPoints: paginasyon zarflı { items, count, limit, offset } döner.
*/
