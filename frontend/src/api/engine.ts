// frontend/src/api/engine.ts
// Uses VITE_API_BASE (e.g. http://127.0.0.1:8000/api) or falls back to "/api".
// Automatically adds "/api" if env var only provides the host.

function normalizeBase(): string {
  let base = (import.meta as any).env?.VITE_API_BASE || "/api";
  if (!base.endsWith("/api")) {
    if (base.endsWith("/")) base = base.slice(0, -1);
    base = base + "/api";
  }
  return base;
}

const BASE = normalizeBase();

async function request<T = any>(path: string, init: RequestInit = {}): Promise<T> {
  const url = `${BASE}${path.startsWith("/") ? "" : "/"}${path}`;
  const headers: Record<string, string> = {
    Accept: "application/json",
    ...(init.headers as any),
  };
  if (init.body && typeof init.body === "string" && !headers["Content-Type"]) {
    headers["Content-Type"] = "application/json";
  }
  const res = await fetch(url, { ...init, headers });
  const text = await res.text();
  let json: any = null;
  try {
    json = text ? JSON.parse(text) : null;
  } catch {
    throw new Error(`API ${res.status}: Response is not JSON: ${text.slice(0, 160)}…`);
  }
  if (!res.ok) throw new Error(`API ${res.status}: ${text}`);
  return json as T;
}

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

export async function runEngine(scenarioId: number, body: any) {
  return request(`/scenarios/${scenarioId}/run-engine`, {
    method: "POST",
    body: JSON.stringify(body),
  });
}

export async function checkBoqCoverage(scenarioId: number, section: "AN" | "EM" | "IE") {
  return request(`/engine/coverage?scenario_id=${scenarioId}&section=${section}`);
}

// Types used by Facts
export type EngineFactsRow = {
  run_id: number;
  scenario_id: number;
  sheet_code: string;
  category_code: string;
  yyyymm: number;
  value: number;
};

export type EngineFactsResponse = {
  scenario_id: number;
  sheet?: string | null;
  category?: string | null;
  run_id?: number | null;
  count: number;
  rows: EngineFactsRow[];
};

export async function getEngineFacts(args: {
  scenario_id: number;
  sheet?: string;
  category?: string;
  run_id?: number;
  latest?: boolean;
  yyyymm_from?: number;
  yyyymm_to?: number;
  limit?: number;
  offset?: number;
}): Promise<EngineFactsResponse> {
  const params = new URLSearchParams();
  params.set("scenario_id", String(args.scenario_id));
  if (args.sheet) params.set("sheet", args.sheet);
  if (args.category) params.set("category", args.category);
  if (args.run_id != null) params.set("run_id", String(args.run_id));
  if (args.latest) params.set("latest", "true");
  if (args.yyyymm_from) params.set("yyyymm_from", String(args.yyyymm_from));
  if (args.yyyymm_to) params.set("yyyymm_to", String(args.yyyymm_to));
  if (args.limit) params.set("limit", String(args.limit));
  if (args.offset) params.set("offset", String(args.offset));
  return request<EngineFactsResponse>(`/engine/facts?${params.toString()}`);
}
