// src/types/scenario.ts

/* ===================== PRODUCTS ===================== */
export type ProductMonth = { year: number; month: number; quantity: number };

export type ScenarioProduct = {
  id: number;
  name: string;
  price: number;
  unit_cogs: number;
  is_active: boolean;
  months: ProductMonth[];
};

/* ===================== OVERHEADS ===================== */
export type ScenarioOverhead = {
  id: number;
  name: string;
  type: "fixed" | "%_revenue";
  amount: number;
};

/* ===================== BOQ ===================== */
export type BOQFrequency = "once" | "monthly" | "per_shipment" | "per_tonne";
export const BOQ_FREQUENCIES: BOQFrequency[] = [
  "once",
  "monthly",
  "per_shipment",
  "per_tonne",
];

// Category tipi & yardımcı sabitler
export type BOQCategory = "bulk_with_freight" | "bulk_ex_freight" | "freight";
export const BOQ_CATEGORIES: BOQCategory[] = [
  "bulk_with_freight",
  "bulk_ex_freight",
  "freight",
];
export const BOQ_CATEGORY_LABELS: Record<BOQCategory, string> = {
  bulk_with_freight: "Bulk (with Freight)",
  bulk_ex_freight: "Bulk (ex Freight)",
  freight: "Freight",
};

export type ScenarioBOQItem = {
  id: number;
  scenario_id?: number;
  section?: string | null;
  item_name: string;
  unit: string;
  quantity: number;
  unit_price: number;
  unit_cogs?: number | null; // nullable
  frequency: BOQFrequency;
  start_year?: number;
  start_month?: number;
  months?: number;
  is_active?: boolean;
  notes?: string | null;
  category?: BOQCategory | null; // NEW
};
export type NewScenarioBOQItem = Omit<ScenarioBOQItem, "id">;

/* ===================== CAPEX ===================== */
export type CapexEntry = {
  id: number;
  year: number;   // 2025
  month: number;  // 1..12
  amount: number; // yatırım çıkışı (-) veya iade (+)
  notes?: string | null;

  // V2/V3 alanları – backend ile uyumlu, UI’da opsiyonel kullanılabilir
  asset_name?: string | null;
  category?: string | null;
  service_start_year?: number | null;
  service_start_month?: number | null;
  useful_life_months?: number | null;
  depr_method?: "straight_line" | "declining_balance" | "sum_of_years";
  salvage_value?: number | null;
  is_active?: boolean | null;

  disposal_year?: number | null;
  disposal_month?: number | null;
  disposal_proceeds?: number | null;
  replace_at_end?: boolean | null;
  per_unit_cost?: number | null;
  quantity?: number | null;
  contingency_pct?: number | null;
  partial_month_policy?: "full_month" | "half_month" | "actual_days";
};
export type NewCapexEntry = Omit<CapexEntry, "id">;

/* ===================== SERVICES (OPEX) ===================== */
export type PaymentTerm = "monthly" | "annual_prepaid" | "one_time";
export const PAYMENT_TERMS: PaymentTerm[] = ["monthly", "annual_prepaid", "one_time"];

export type CashOutMonthPolicy =
  | "service_month"
  | "start_month"
  | "contract_anniversary";
export const CASH_OUT_POLICIES: CashOutMonthPolicy[] = [
  "service_month",
  "start_month",
  "contract_anniversary",
];

export type EscalationFreq = "annual" | "none";
export const ESCALATION_FREQS: EscalationFreq[] = ["annual", "none"];

export type ScenarioService = {
  id: number;
  scenario_id?: number;

  // Temel
  service_name: string;
  category?: string | null;
  vendor?: string | null;
  unit?: string | null;

  // Fiyat / miktar
  quantity: number;
  unit_cost: number;
  currency: string;

  // Zamanlama
  start_year: number;
  start_month: number;
  duration_months?: number | null;
  end_year?: number | null;
  end_month?: number | null;

  // Ödeme & Nakit
  payment_term: PaymentTerm;
  cash_out_month_policy: CashOutMonthPolicy;

  // Endeks / Artış
  escalation_pct: number;
  escalation_freq: EscalationFreq;

  // Vergi
  tax_rate: number;
  expense_includes_tax: boolean;

  // Diğer
  notes?: string | null;
  is_active: boolean;

  created_at?: string;
  updated_at?: string;
};
export type NewScenarioService = Omit<ScenarioService, "id">;

export type ScenarioServiceMonth = {
  id: number;
  service_id: number;
  year: number;
  month: number;
  expense_amount: number;
  cash_out: number;
  tax_amount: number;
};

/* ===================== WORKFLOW ===================== */
export type WorkflowState = "draft" | "twc" | "capex" | "services" | "ready";
export type Workflow = {
  scenario_id: number;
  workflow_state: WorkflowState | string;
  is_boq_ready: boolean;
  is_twc_ready: boolean;
  is_capex_ready: boolean;
  is_services_ready: boolean;
};

/* ===================== SCENARIO DETAIL (API) ===================== */
export type ScenarioDetail = {
  id: number;
  business_case_id: number;
  name: string;
  months: number;
  start_date: string;
  products: ScenarioProduct[];
  overheads: ScenarioOverhead[];
  boq_items?: ScenarioBOQItem[];
  capex?: CapexEntry[];            // CAPEX satırları
  services?: ScenarioService[];    // NEW: Services listesi
};

/* ===================== P&L (COMPUTE) ===================== */
export type PLMonth = {
  year: number;
  month: number;
  revenue: number;
  cogs: number;
  gross_margin: number;
  overhead_fixed: number;
  overhead_var_pct: number;
  overhead_var_amount: number;
  overhead_total: number;
  depreciation: number;  // NEW
  ebit: number;
  net_income: number;
  // Frontend uyumluluğu için opsiyonel alias:
  depr?: number;
};

export type PLResponse = {
  scenario: {
    id: number;
    name: string;
    months: number;
    start_date: string;
    overheads: { fixed_sum: number; pct_sum: number };
  };
  months: PLMonth[];
  totals: {
    revenue: number;
    cogs: number;
    gross_margin: number;
    overhead_fixed_total: number;
    overhead_var_total: number;
    overhead_total: number;
    depreciation_total: number; // NEW
    depr_total?: number;        // alias (backend sağlıyorsa)
    ebit: number;
    net_income: number;
  };
};

/* ===================== MISC ===================== */
export type CapexRow = { year: number; month: number; amount: number };
export type FinanceMode = "proxy" | "fcf";
