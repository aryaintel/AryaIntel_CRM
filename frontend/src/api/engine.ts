// Pathway: C:/Dev/AryaIntel_CRM/frontend/src/api/engine.ts
// API client for Run Engine & diagnostics with robust error messages.
// DEV-FRIENDLY BASE: If VITE_API_BASE is not set and we are on Vite (port 5173),
// default to http://127.0.0.1:8000 so /api calls don't 404 on the FE server.

export type EngineCategoryCode = "AN" | "EM" | "IE" | "Services";

export type EngineCategory = {
  code: EngineCategoryCode;
  enabled: boolean;
};

export type EngineOptions = {
  rise_and_fall: boolean | null; // null = auto (locked by policy if present)
  fx_apply: boolean;
  tax_apply: boolean;
  rebates_apply: boolean;
  twc_apply: boolean;
};

export type RunEngineRequest = {
  categories: EngineCategory[];
  options: EngineOptions;
  persist: boolean;
};

export type SheetPayload = {
  name: string;
  months: string[]; // "YYYY-MM"
  values: number[];
};

export type RunEngineResult = {
  scenario_id: number;
  generated: SheetPayload[];
  locks: { rise_and_fall: boolean };
  notes?: string | null;
  persisted: boolean;
  persisted_rows: number;
  run_id?: number | null;
};

export type FactsRow = {
  run_id?: number | null;
  scenario_id?: number | null;
  sheet_code: string;
  category_code: string;
  yyyymm: number;
  value: number;
};

export type FactsResponse = {
  total?: number | null;
  rows: FactsRow[];
};

export type BoqCoverage = {
  scenario_id: number;
  section: string;
  scenario_start: string;
  scenario_months: number;
  total_active_rows: number;
  rows_in_window: number;
  rows_before_window: number;
  rows_after_window: number;
  zero_value_rows: number;
  notes: string[];
  samples: Array<Record<string, any>>;
};

const JSON_HEADERS: HeadersInit = {
  "Content-Type": "application/json",
  Accept: "application/json",
};

function apiBase(): string {
  // 1) Respect explicit base if provided
  const envBase = (import.meta as any)?.env?.VITE_API_BASE as string | undefined;
  if (envBase && envBase.trim().length > 0) {
    return envBase.replace(/\/+$/, "");
  }
  // 2) Smart default for dev server: if we're on Vite (default port 5173), talk to backend 8000
  if (typeof window !== "undefined" && window.location && window.location.port === "5173") {
    return "http://127.0.0.1:8000";
  }
  // 3) Otherwise leave empty → relative "/api" (useful behind reverse proxy in prod)
  return "";
}

async function parseError(res: Response): Promise<never> {
  let msg = `HTTP ${res.status}`;
  try {
    const data = await res.json();
    if (data?.detail) {
      msg = `${msg} – ${typeof data.detail === "string" ? data.detail : JSON.stringify(data.detail)}`;
    }
  } catch {
    // ignore
  }
  throw new Error(msg);
}

export async function runEngine(
  scenarioId: number,
  body: RunEngineRequest,
): Promise<RunEngineResult> {
  const res = await fetch(`${apiBase()}/api/scenarios/${scenarioId}/run-engine`, {
    method: "POST",
    headers: JSON_HEADERS,
    body: JSON.stringify(body),
  });
  if (!res.ok) return parseError(res);
  return res.json();
}

export async function readEngineFacts(params: {
  scenario_id?: number;
  run_id?: number;
  sheet?: string;
  category?: string;
  yyyymm_from?: number;
  yyyymm_to?: number;
  limit?: number;
  offset?: number;
}): Promise<FactsResponse> {
  const q = new URLSearchParams();
  Object.entries(params).forEach(([k, v]) => {
    if (v !== undefined && v !== null && v !== "") q.set(k, String(v));
  });
  const res = await fetch(`${apiBase()}/api/engine/facts?${q.toString()}`, {
    method: "GET",
    headers: JSON_HEADERS,
  });
  if (!res.ok) return parseError(res);
  return res.json();
}

export async function checkBoqCoverage(
  scenarioId: number,
  section: "AN" | "EM" | "IE",
): Promise<BoqCoverage> {
  const res = await fetch(
    `${apiBase()}/api/scenarios/${scenarioId}/boq/check-coverage?section=${section}`,
    { method: "GET", headers: JSON_HEADERS }
  );
  if (!res.ok) return parseError(res);
  return res.json();
}

// Helpers
export function format1(n: number): string {
  // 1 ondalık (proje standardı)
  const v = Number.isFinite(n) ? n : 0;
  return v.toLocaleString(undefined, { minimumFractionDigits: 1, maximumFractionDigits: 1 });
}

export const DEFAULT_OPTIONS: EngineOptions = {
  rise_and_fall: null,
  fx_apply: true,
  tax_apply: true,
  rebates_apply: true,
  twc_apply: true,
};
