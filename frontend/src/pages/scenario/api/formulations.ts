// frontend/src/pages/scenario/api/formulations.ts
import { apiGet, apiPost, apiPut } from "../../../lib/api";

export type ComponentIn = {
  index_series_id: number;
  weight_pct: number;             // 0..100 (UI can pass %; BE normalizes)
  base_index_value?: number | null;
  note?: string | null;
};

export type FormulationCreate = {
  product_id: number;             // pass the owning product/service product_id
  code: string;                    // unique per product (e.g., "SVC-BASE-001")
  name?: string | null;
  base_price?: number | null;
  base_currency?: string | null;   // default "USD"
  components: ComponentIn[];
};

export type FormulationUpdate = Partial<{
  code: string;
  name: string | null;
  base_price: number | null;
  base_currency: string | null;
  components: ComponentIn[];       // if provided -> full replace
}>;

export async function createFormulation(payload: FormulationCreate): Promise<{ id: number }> {
  return apiPost("/api/formulations", payload);
}

export async function updateFormulation(fid: number, payload: FormulationUpdate): Promise<{ id: number; updated: true }> {
  return apiPut(`/api/formulations/${fid}`, payload);
}

export async function attachFormulationToService(serviceId: number, formulationId: number, allowArchived = false) {
  return apiPost(`/api/services/${serviceId}/attach-formulation`, {
    formulation_id: formulationId,
    allow_archived: allowArchived,
  });
}

export async function detachFormulationFromService(serviceId: number) {
  return apiPost(`/api/services/${serviceId}/detach-formulation`, {});
}

export async function attachFormulationToBoqItem(itemId: number, formulationId: number, allowArchived = false) {
  return apiPost(`/api/boq-items/${itemId}/attach-formulation`, {
    formulation_id: formulationId,
    allow_archived: allowArchived,
  });
}

export async function detachFormulationFromBoqItem(itemId: number) {
  return apiPost(`/api/boq-items/${itemId}/detach-formulation`, {});
}
