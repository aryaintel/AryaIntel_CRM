// src/lib/apiBoq.ts
import { apiGet } from "./api";

export type BoqPreview =
  | {
      id: number;
      scenario_id: number;
      name: string;
      period: string;          // "YYYY-MM"
      currency: string;
      unit_price: string;
      quantity: string;
      line_total: string;
      source: "formulation" | "product_price_book" | "boq_unit_price";
      // only when source = "formulation"
      base_price?: string;
      factor?: string;
      // NEW: server passes through price term on price-book source
      price_term?: string | null;
    }
  ;

export async function getBoqPricePreview(boqId: number, ym: string) {
  return apiGet<BoqPreview>(`/api/boq/${boqId}/price-preview?ym=${encodeURIComponent(ym)}`);
}

export async function getScenarioBoundedBoqPricePreview(
  scenarioId: number,
  boqId: number,
  ym: string
) {
  return apiGet<BoqPreview>(
    `/api/boq/scenarios/${scenarioId}/boq/${boqId}/price-preview?ym=${encodeURIComponent(ym)}`
  );
}
