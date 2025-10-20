// relative path: frontend/src/api/engine.ts
// Path: frontend/src/api/engine.ts
// Single-point Engine API (uses central api.ts for base URL & credentials)

import { apiGet, apiPost, ApiError } from "../lib/api";

export const DEFAULT_OPTIONS = {
  rise_and_fall: true,
  fx_apply: true,
  tax_apply: true,
  rebates_apply: true,
  twc_apply: true,
} as const;

export function format1(v: number) {
  if (v === null || v === undefined || Number.isNaN(v)) return "-";
  return new Intl.NumberFormat(undefined, { maximumFractionDigits: 1 }).format(v);
}

/** Resilient engine run.
 * Tries canonical route first: POST /api/scenarios/{id}/run-engine
 * Falls back to:          POST /api/engine/run?scenario_id={id}
 * so FE works regardless of router prefix differences.
 */
export async function runEngine(scenarioId: number, body: any) {
  try {
    return await apiPost(`/scenarios/${scenarioId}/run-engine`, body);
  } catch (e: any) {
    const status = (e as ApiError)?.status ?? 0;
    // 404/405 => try legacy endpoint
    if (status === 404 || status === 405) {
      const q = new URLSearchParams({ scenario_id: String(scenarioId) });
      const legacyBody = { ...body, scenario_id: scenarioId };
      return await apiPost(`/engine/run?${q.toString()}`, legacyBody);
    }
    throw e;
  }
}

export async function checkBoqCoverage(
  scenarioId: number,
  section: "AN" | "EM" | "IE"
) {
  const qs = new URLSearchParams({ section });
  return apiGet(`/scenarios/${scenarioId}/boq/check-coverage?${qs.toString()}`);
}

// -------- Facts --------
export type EngineFactsRow = {
  run_id: number;
  scenario_id: number;
  sheet_code: string;
  category_code: string;
  yyyymm: number;
  value: number;
  series?: "revenue" | "cogs" | "gp";
};

export type EngineFactsResponse = {
  scenario_id: number;
  sheet?: string | null;
  category?: string | null;
  run_id?: number | null;
  count: number;
  rows: EngineFactsRow[];
};

export type GetFactsArgs = {
  scenario_id: number;
  sheet?: string;               // FE name → BE param: sheet_code
  category?: string;            // FE name → BE param: category_code
  series?: string | string[];   // "revenue" | "cogs" | "gp"
  run_id?: number;
  latest?: boolean;
  yyyymm_from?: number;
  yyyymm_to?: number;
  limit?: number;
  offset?: number;
  group_by?: "series" | "yyyymm" | "sheet" | "category";
  rollup?: "quarter" | "year";
};

/** Backward-compat: also accepts { scenarioId } and maps to { scenario_id }. Normalizes 404 → empty rows. */
export async function getEngineFacts(args: GetFactsArgs | (Partial<GetFactsArgs> & { scenarioId?: number })): Promise<EngineFactsResponse> {
  const a: any = { ...args };
  if (a.scenario_id == null && a.scenarioId != null) a.scenario_id = a.scenarioId;

  const params = new URLSearchParams();
  if (a.scenario_id == null) throw new Error("scenario_id is required");
  params.set("scenario_id", String(a.scenario_id));
  if (a.sheet) params.set("sheet_code", a.sheet);
  if (a.category) params.set("category_code", a.category);
  if (Array.isArray(a.series)) a.series.forEach((s: string) => params.append("series", s));
  else if (a.series) params.set("series", a.series);
  if (a.run_id != null) params.set("run_id", String(a.run_id));
  if (a.latest) params.set("latest", "true");
  if (a.yyyymm_from) params.set("yyyymm_from", String(a.yyyymm_from));
  if (a.yyyymm_to) params.set("yyyymm_to", String(a.yyyymm_to));
  if (a.limit) params.set("limit", String(a.limit));
  if (a.offset) params.set("offset", String(a.offset));
  if (a.group_by) params.set("group_by", a.group_by);
  if (a.rollup) params.set("rollup", a.rollup);

  try {
    return await apiGet<EngineFactsResponse>(`/engine/facts?${params.toString()}`);
  } catch (e: any) {
    const status = (e as ApiError)?.status ?? 0;
    if (status === 404) {
      return { scenario_id: Number(a.scenario_id || 0), count: 0, rows: [] };
    }
    throw e;
  }
}
