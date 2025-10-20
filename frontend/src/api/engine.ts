// Pathway: frontend/src/api/engine.ts
import { apiGet, apiPost } from "../lib/api";

/* ------------------------------------------------------------------ */
/* Types                                                              */
/* ------------------------------------------------------------------ */
export type EngineSeries = "revenue" | "cogs" | "gp";

export type GetFactsOpts = {
  scenarioId: number;
  /** c.Sales-AN, oA.Finance-AN, oQ.Finance-AN, ... */
  sheet?: string;
  /** Tek bir değer veya dizi; dizi gelirse virgülle birleştirilir */
  series?: EngineSeries | EngineSeries[];
  /** YYYYMM (örn. 202501) aralığı opsiyoneldir */
  yyyymmFrom?: string;
  yyyymmTo?: string;
  /** true → persisted (oA/oQ), false/undefined → preview (c.Sales) */
  persisted?: boolean;
  /** sayfalama opsiyonel */
  page?: number;
  pageSize?: number;
};

export type EngineFactRow = {
  yyyymm: string;
  /** örn. 'revenue' | 'cogs' | 'gp' */
  series: EngineSeries;
  /** kategori/sheet bağı (örn. AN) varsa BE zaten taşır */
  [key: string]: any;
};

type EngineFactsResponse = {
  rows: EngineFactRow[];
};

/* ------------------------------------------------------------------ */
/* Helpers                                                            */
/* ------------------------------------------------------------------ */
const SERIES_ORDER: EngineSeries[] = ["revenue", "cogs", "gp"];

function normalizeSeries(input?: EngineSeries | EngineSeries[]): string | undefined {
  if (!input) return undefined;
  const arr = Array.isArray(input) ? input : [input];
  // uniq + belirli sırada (BE tarafındaki tablo yazımıyla tutarlı olsun)
  const uniq = Array.from(new Set(arr)).filter(Boolean) as EngineSeries[];
  const ordered = SERIES_ORDER.filter((s) => uniq.includes(s));
  return ordered.length ? ordered.join(",") : undefined;
}

function toQuery(params: Record<string, string | number | boolean | undefined>) {
  const q = new URLSearchParams();
  Object.entries(params).forEach(([k, v]) => {
    if (v === undefined || v === null || v === "") return;
    q.set(k, String(v));
  });
  return q.toString();
}

/* ------------------------------------------------------------------ */
/* API                                                                */
/* ------------------------------------------------------------------ */

/** Engine’ı çalıştırır (preview veya persist flag’i BE default’larına göre) */
export async function runEngine(scenarioId: number, body: Record<string, any> = {}) {
  // Not: api.ts otomatik /api eklemediği için yol bilinçli /api ile başlıyor
  return apiPost(`/api/scenarios/${scenarioId}/run-engine`, body);
}

/**
 * Engine facts (preview veya persisted) çeker.
 * Kök neden düzeltmesi: `series` dizisi TEK parametre olarak gönderilir.
 */
export async function getEngineFacts(opts: GetFactsOpts): Promise<EngineFactRow[]> {
  const {
    scenarioId,
    sheet,
    series,
    yyyymmFrom,
    yyyymmTo,
    persisted,
    page,
    pageSize,
  } = opts;

  const seriesStr = normalizeSeries(series);

  const query = toQuery({
    scenario_id: scenarioId,
    sheet,
    series: seriesStr, // <— TEK parametre, virgüllü
    yyyymm_from: yyyymmFrom,
    yyyymm_to: yyyymmTo,
    persisted: persisted ? 1 : 0,
    page,
    page_size: pageSize,
  });

  const url = `/api/engine/facts?${query}`;

  try {
    const res = await apiGet<EngineFactsResponse>(url);
    return Array.isArray(res?.rows) ? res.rows : [];
  } catch (e: any) {
    // Sprint notuna göre: 404 "No data found..." → boş dizi dön
    if (e?.status === 404) return [];
    throw e;
  }
}
