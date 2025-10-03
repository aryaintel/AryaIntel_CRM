// frontend/src/lib/escalation.ts
import { apiGet, apiPost, apiPut, apiDelete } from "./api";

/* ---------- Types ---------- */
export type EscScope = "price" | "cost" | "both";
export type EscFrequency = "monthly" | "quarterly" | "annual";
export type EscCompounding = "compound" | "simple";

export type EscComponent = {
  id?: number;
  index_series_id: number;
  weight_pct: number;           // 0..100
  base_index_value?: number | null;
  note?: string | null;
};

export type EscalationPolicy = {
  id: number;
  name: string;
  scope: EscScope;
  rate_pct?: number | null;
  index_series_id?: number | null;
  start_year: number;
  start_month: number;
  cap_pct?: number | null;
  floor_pct?: number | null;
  frequency: EscFrequency;
  compounding: EscCompounding;
  scenario_id?: number | null;
  created_at?: string;
  updated_at?: string;
  // when fetched by id we also return components:
  components?: EscComponent[];
};

export type EscalationCreate = {
  name: string;
  scope?: EscScope;
  rate_pct?: number | null;
  index_series_id?: number | null;
  components?: EscComponent[];       // full set if index-based
  start_year: number;
  start_month: number;
  cap_pct?: number | null;
  floor_pct?: number | null;
  frequency?: EscFrequency;
  compounding?: EscCompounding;
  scenario_id?: number | null;       // bırakılırsa path’ten alınır
};

export type EscalationUpdate = Partial<Omit<EscalationCreate, "components">> & {
  components?: EscComponent[] | null; // verilirse TAM değiştirir (boş liste -> hiç component yok)
};

export type EscalationListResp = {
  items: EscalationPolicy[];
  count: number;
  limit: number;
  offset: number;
};

/* ---------- Helpers ---------- */
function q(obj: Record<string, any | undefined>) {
  const usp = new URLSearchParams();
  Object.entries(obj).forEach(([k, v]) => {
    if (v === undefined || v === null || v === "") return;
    usp.set(k, String(v));
  });
  const s = usp.toString();
  return s ? `?${s}` : "";
}

/* ---------- API ---------- */
// List (global + scenario scoped)
export async function listEscalationPolicies(
  scenarioId: number,
  params?: {
    q?: string;
    scope?: EscScope;
    frequency?: EscFrequency;
    limit?: number;
    offset?: number;
  }
): Promise<EscalationListResp> {
  return apiGet(
    `/scenarios/${scenarioId}/escalation-policies${q(params ?? {})}`
  );
}

// Create (under scenario)
export async function createEscalationPolicy(
  scenarioId: number,
  payload: EscalationCreate
): Promise<{ id: number }> {
  return apiPost(`/scenarios/${scenarioId}/escalation-policies`, payload);
}

// Update
export async function updateEscalationPolicy(
  scenarioId: number,
  policyId: number,
  payload: EscalationUpdate
): Promise<{ id: number; updated: true }> {
  return apiPut(
    `/scenarios/${scenarioId}/escalation-policies/${policyId}`,
    payload
  );
}

// Delete
export async function deleteEscalationPolicy(
  scenarioId: number,
  policyId: number
): Promise<void> {
  return apiDelete(`/scenarios/${scenarioId}/escalation-policies/${policyId}`);
}

// (Opsiyonel) Tek policy getir — Swagger’da var olan /api/escalations/policies/{pid}
export async function getEscalationPolicy(policyId: number): Promise<{
  policy: EscalationPolicy;
  components: EscComponent[];
}> {
  return apiGet(`/api/escalations/policies/${policyId}`);
}

/* ---------- Attach / Defaults (opsiyonel yardımcılar) ---------- */
// /api/escalations/services/{id}/attach
export async function attachPolicyToService(
  serviceId: number,
  policyId: number,
  target: "price" | "cogs" = "price"
): Promise<{ service_id: number; price_policy_id: number | null; cogs_policy_id: number | null }> {
  return apiPost(`/api/escalations/services/${serviceId}/attach`, {
    policy_id: policyId,
    target,
  });
}

// /api/escalations/boq-items/{id}/attach
export async function attachPolicyToBOQItem(
  itemId: number,
  policyId: number,
  target: "price" | "cogs" = "price"
): Promise<{ boq_item_id: number; price_policy_id: number | null; cogs_policy_id: number | null }> {
  return apiPost(`/api/escalations/boq-items/${itemId}/attach`, {
    policy_id: policyId,
    target,
  });
}

// /api/escalations/scenarios/{sid}/set-defaults
export async function setScenarioEscalationDefaults(
  scenarioId: number,
  payload: { price_policy_id?: number | null; cogs_policy_id?: number | null }
): Promise<{ scenario_id: number; default_price_policy_id: number | null; default_cogs_policy_id: number | null }> {
  return apiPost(`/api/escalations/scenarios/${scenarioId}/set-defaults`, payload);
}

/* ---------- Resolve (preview) ---------- */
// Swagger’da /scenarios/{scenario_id}/escalation/resolve GET
export async function resolveEscalationPreview(
  scenarioId: number,
  year: number,
  month: number
): Promise<any> {
  return apiGet(
    `/scenarios/${scenarioId}/escalation/resolve${q({ year, month })}`
  );
}
