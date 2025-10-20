
// C:/Dev/AryaIntel_CRM/frontend/src/pages/scenario/components/ServicesTable.tsx
// ServicesTable — Excel parity with `i.ServicesPricing` (improved)
// - CRUD base: /scenarios/:scenarioId/services  (legacy prefix – no /api)
// - One-line rows, Source column, inline Details row (expand/collapse), friendly labels, max 1 decimal
// - Category & Service Name: typeahead with Service Catalogue scoping

import React, { useEffect, useMemo, useRef, useState } from "react";
import { apiGet, apiPost, apiPut, apiDelete } from "../../../lib/api";

/* --------------------------------- Utils ---------------------------------- */

function cls(...a: Array<string | false | undefined>) {
  return a.filter(Boolean).join(" ");
}
function pad2(n: number) {
  return String(n).padStart(2, "0");
}
function clamp(n: number, min: number, max: number) {
  return Math.max(min, Math.min(max, n));
}
function toInt(v: any, d: number | null = null) {
  if (v === null || v === undefined || v === "") return d;
  const n = Number(v);
  return Number.isFinite(n) ? Math.trunc(n) : d;
}
function toNum(v: any, d: number | null = null) {
  if (v === null || v === undefined || v === "") return d;
  const n = Number(String(v).toString().replace(",", "."));
  return Number.isFinite(n) ? n : d;
}
function monthAdd(y: number, m: number, delta: number): { y: number; m: number } {
  const z = (y * 12 + (m - 1)) + delta;
  const ny = Math.floor(z / 12);
  const nm = (z % 12) + 1;
  return { y: ny, m: nm };
}
// format with at most 1 decimal digit
function fmt1(n: any): string {
  const v = Number(n ?? 0);
  if (!Number.isFinite(v)) return "—";
  return v.toLocaleString(undefined, { maximumFractionDigits: 1 });
}
// debounce
function useDebounce<T>(value: T, delay = 250) {
  const [debounced, setDebounced] = useState(value);
  useEffect(() => {
    const id = setTimeout(() => setDebounced(value), delay);
    return () => clearTimeout(id);
  }, [value, delay]);
  return debounced;
}

/* ----------------------------- Domain Typings ----------------------------- */

type PaymentTerm = "monthly" | "annual_prepaid" | "one_time";
type CashOutPolicy = "service_month" | "start_month" | "contract_anniversary";
type EscalationFreq = "annual" | "none";

export type ServiceRow = {
  id?: number;
  scenario_id?: number;

  service_name: string;
  vendor?: string | null;
  category?: string | null; // we'll infer Source from this

  unit?: string | null;
  quantity?: number | null;

  unit_cost?: number | null;
  currency?: string | null;

  start_year?: number | null;
  start_month?: number | null;
  duration_months?: number | null;

  end_year?: number | null;
  end_month?: number | null;

  payment_term?: PaymentTerm | null;
  cash_out_month_policy?: CashOutPolicy | null;

  escalation_pct?: number | null;
  escalation_freq?: EscalationFreq | null;

  tax_rate?: number | null;
  expense_includes_tax?: boolean | null;

  notes?: string | null;
  is_active?: boolean | null;
};

// Service Catalogue types
type ServiceFamily = {
  id: number;
  code: string;
  name: string;
  is_active?: number;
};
type ServiceCatalogItem = {
  id: number;
  family_id: number;
  code: string;
  name: string;
  uom?: string | null;
  default_currency?: string | null;
  is_active?: number;
  description?: string | null;
};

type Props = {
  scenarioId: number;
  onChanged?: () => void;
  onMarkedReady?: () => void;
};

/* ----------------------------- UI Dictionaries ---------------------------- */

const PAYMENT_TERMS: { value: PaymentTerm; label: string }[] = [
  { value: "monthly", label: "Monthly" },
  { value: "annual_prepaid", label: "Annual (Prepaid)" },
  { value: "one_time", label: "One-time" },
];

const CASHOUT_POLICIES: { value: CashOutPolicy; label: string }[] = [
  { value: "service_month", label: "In Service Month" },
  { value: "start_month", label: "At Start Month" },
  { value: "contract_anniversary", label: "At Contract Anniversary" },
];

const CASHOUT_LABEL: Record<CashOutPolicy, string> = {
  service_month: "In Service Month",
  start_month: "At Start Month",
  contract_anniversary: "At Contract Anniversary",
};

const ESC_FREQS: { value: EscalationFreq; label: string }[] = [
  { value: "annual", label: "Annual" },
  { value: "none", label: "None" },
];

const CURRENCIES = ["USD", "EUR", "GBP", "TRY", "SAR", "AED"];
/* ---------- Backend endpoint fallbacks for Service Catalogue ---------- */
const CATALOG_ENDPOINTS = {
  families: [
    "/api/services-catalog/families",
    "/api/service-catalog/families",
    "/api/services-catalog/family",
    "/api/service-families",
    "/api/catalog/services/families",
  ],
  services: [
    "/api/services-catalog",
    "/api/services-catalog/search",
    "/api/service-catalog",
    "/api/catalog/services",
    "/api/services",
  ],
} as const;

const LAST_GOOD: { families?: string; services?: string } = {};

function buildQS(params?: Record<string, string | number | undefined>) {
  if (!params) return "";
  const pruned: Record<string, string> = {};
  for (const [k, v] of Object.entries(params)) {
    if (v !== undefined && v !== null && String(v).length > 0) pruned[k] = String(v);
  }
  const qs = new URLSearchParams(pruned).toString();
  return qs ? `?${qs}` : "";
}


/* ---------------------- Stable Helper Components (top-level) --------------------- */

function HeaderCell({ children, className }: { children: React.ReactNode; className?: string }) {
  return (
    <th className={cls("px-3 py-2 text-left text-xs font-semibold text-gray-600 border-b", className)}>
      {children}
    </th>
  );
}
function Cell({
  children,
  className,
  colSpan,
  title,
}: {
  children: React.ReactNode;
  className?: string;
  colSpan?: number;
  title?: string;
}) {
  return (
    <td className={cls("px-3 py-2 text-sm border-b whitespace-nowrap", className)} colSpan={colSpan} title={title}>
      {children}
    </td>
  );
}
function NumInput(props: React.InputHTMLAttributes<HTMLInputElement>) {
  return (
    <input
      {...props}
      className={cls(
        "w-full rounded-md border px-2 py-1 text-sm outline-none",
        "focus:ring-2 focus:ring-indigo-500 border-gray-300",
        props.className
      )}
      inputMode="decimal"
    />
  );
}
function TxtInput(props: React.InputHTMLAttributes<HTMLInputElement>) {
  return (
    <input
      {...props}
      className={cls(
        "w-full rounded-md border px-2 py-1 text-sm outline-none",
        "focus:ring-2 focus:ring-indigo-500 border-gray-300",
        props.className
      )}
    />
  );
}
function SelectGeneric<T extends string>({
  value,
  onChange,
  options,
}: {
  value: T | null | undefined;
  onChange: (v: T | null) => void;
  options: { value: T; label: string }[];
}) {
  return (
    <select
      value={value ?? ""}
      onChange={(e) => onChange((e.target.value as T) || null)}
      className={cls(
        "w-full rounded-md border px-2 py-1 text-sm outline-none",
        "focus:ring-2 focus:ring-indigo-500 border-gray-300"
      )}
    >
      <option value="">—</option>
      {options.map((o) => (
        <option key={o.value} value={o.value}>
          {o.label}
        </option>
      ))}
    </select>
  );
}

function MonthInput({
  value,
  onChange,
}: {
  value?: number | null;
  onChange: (v: number | null) => void;
}) {
  return (
    <NumInput
      value={value ?? ""}
      onChange={(e) => {
        const v = toInt(e.target.value, null);
        onChange(v ? clamp(v, 1, 12) : null);
      }}
      placeholder="MM"
    />
  );
}

function YearInput({
  value,
  onChange,
}: {
  value?: number | null;
  onChange: (v: number | null) => void;
}) {
  return <NumInput value={value ?? ""} onChange={(e) => onChange(toInt(e.target.value, null))} placeholder="YYYY" />;
}

function CurrencySelect({
  value,
  onChange,
}: {
  value?: string | null;
  onChange: (v: string | null) => void;
}) {
  return (
    <select
      value={value ?? ""}
      onChange={(e) => onChange(e.target.value || null)}
      className="w-full rounded-md border px-2 py-1 text-sm outline-none focus:ring-2 focus:ring-indigo-500 border-gray-300"
    >
      <option value="">—</option>
      {CURRENCIES.map((c) => (
        <option key={c} value={c}>
          {c}
        </option>
      ))}
    </select>
  );
}

// Simple, dependency-free typeahead dropdown
function Typeahead<T>({
  value,
  onSelect,
  onQueryChange,
  options,
  open,
  setOpen,
  placeholder,
  renderLine,
  className,
}: {
  value: string;
  onSelect: (item: T) => void;
  onQueryChange: (q: string) => void;
  options: T[];
  open: boolean;
  setOpen: (v: boolean) => void;
  placeholder?: string;
  renderLine?: (item: T) => React.ReactNode;
  className?: string;
}) {
  const ref = useRef<HTMLDivElement | null>(null);
  useEffect(() => {
    function onDoc(e: MouseEvent) {
      if (!ref.current) return;
      if (!ref.current.contains(e.target as Node)) setOpen(false);
    }
    document.addEventListener("mousedown", onDoc);
    return () => document.removeEventListener("mousedown", onDoc);
  }, [setOpen]);
  return (
    <div ref={ref} className={cls("relative", className)}>
      <input
        className={cls(
          "w-full rounded-md border px-2 py-1 text-sm outline-none",
          "focus:ring-2 focus:ring-indigo-500 border-gray-300"
        )}
        placeholder={placeholder}
        value={value}
        onChange={(e) => {
          onQueryChange(e.target.value);
          if (!open) setOpen(true);
        }}
        onFocus={() => setOpen(true)}
      />
      {open && (
        <div className="absolute z-10 mt-1 max-h-56 w-full overflow-auto rounded-md border bg-white shadow">
          {options.length === 0 ? (
            <div className="px-2 py-2 text-xs text-gray-500">No results</div>
          ) : (
            options.map((opt, idx) => (
              <button
                key={idx}
                type="button"
                className="block w-full text-left px-2 py-1.5 text-sm hover:bg-gray-50"
                onClick={() => {
                  onSelect(opt);
                  setOpen(false);
                }}
              >
                {renderLine ? renderLine(opt) : (opt as any).name}
              </button>
            ))
          )}
        </div>
      )}
    </div>
  );
}

/* -------------------------------- Component ------------------------------- */

export default function ServicesTable({ scenarioId, onChanged, onMarkedReady }: Props) {
  // IMPORTANT: services CRUD lives under legacy /scenarios prefix (no /api)
    const baseUrl = `/api/scenarios/${scenarioId}/services`;

  const [rows, setRows] = useState<ServiceRow[]>([]);
  const [loading, setLoading] = useState(false);
  const [err, setErr] = useState<string | null>(null);

  const [draft, setDraft] = useState<ServiceRow>(() => ({
    service_name: "",
    vendor: null,
    category: null,
    unit: null,
    quantity: null,
    unit_cost: null,
    currency: "USD",
    start_year: null,
    start_month: null,
    duration_months: null,
    end_year: null,
    end_month: null,
    payment_term: "monthly",
    cash_out_month_policy: "service_month",
    escalation_pct: null,
    escalation_freq: "none",
    tax_rate: null,
    expense_includes_tax: false,
    notes: null,
    is_active: true,
  }));

  const [editing, setEditing] = useState<Record<number, ServiceRow>>({});
  const [expanded, setExpanded] = useState<Record<string, boolean>>({ draft: false });

  // ---------- Service Catalogue state (Category & Service Name typeahead) ----------
  const [familyQ, setFamilyQ] = useState("");
  const debouncedFamilyQ = useDebounce(familyQ, 250);
  const [families, setFamilies] = useState<ServiceFamily[]>([]);
  const [familyOpen, setFamilyOpen] = useState(false);

  const [serviceQ, setServiceQ] = useState("");
  const debouncedServiceQ = useDebounce(serviceQ, 250);
  const [catalog, setCatalog] = useState<ServiceCatalogItem[]>([]);
  const [catalogOpen, setCatalogOpen] = useState(false);

  // track selected family (for scoped search)
  const [selectedFamily, setSelectedFamily] = useState<ServiceFamily | null>(null);

  // fetch families when query changes or dropdown opens
  useEffect(() => {
    let alive = true;
    if (!familyOpen) return;
    (async () => {
      try {
        const bases = LAST_GOOD.families
          ? [LAST_GOOD.families, ...CATALOG_ENDPOINTS.families.filter((u) => u !== LAST_GOOD.families)]
          : CATALOG_ENDPOINTS.families;
        const queries = debouncedFamilyQ && debouncedFamilyQ.trim().length >= 2
          ? [
              buildQS({ q: debouncedFamilyQ }),
              buildQS({ query: debouncedFamilyQ }),
              buildQS({ search: debouncedFamilyQ }),
            ]
          : [""];
        let data: ServiceFamily[] | null = null;
        for (const base of bases) {
          for (const qs of queries) {
            try {
              const res = await apiGet<ServiceFamily[]>(`${base}${qs}`);
              LAST_GOOD.families = base;
              data = res;
              break;
            } catch (e: any) {
              if (e?.response?.status && e.response.status !== 404) throw e;
            }
          }
          if (data) break;
        }
        if (alive) setFamilies(Array.isArray(data) ? data : []);
      } catch (_e) {
        if (alive) setFamilies([]);
      }
    })();
    return () => {
      alive = false;
    };
  }, [familyOpen, debouncedFamilyQ]);

  // fetch services scoped by family
  useEffect(() => {
    let alive = true;
    if (!catalogOpen) return;
    (async () => {
      try {
        const bases = LAST_GOOD.services
          ? [LAST_GOOD.services, ...CATALOG_ENDPOINTS.services.filter((u) => u !== LAST_GOOD.services)]
          : CATALOG_ENDPOINTS.services;
        const q = debouncedServiceQ && debouncedServiceQ.trim().length >= 2 ? debouncedServiceQ.trim() : "";
        const fam = selectedFamily?.id ? String(selectedFamily.id) : "";
        const queryVariants: string[] = [];
        if (q) {
          for (const name of ["q", "query", "search"]) {
          queryVariants.push(buildQS({ [name]: q, familyId: fam || undefined } as any));
          }
        } else {
          queryVariants.push(buildQS({ familyId: fam || undefined } as any));
          if (!fam) queryVariants.push("");
        }
        let data: ServiceCatalogItem[] | null = null;
        for (const base of bases) {
          for (const qs of queryVariants) {
            try {
              const res = await apiGet<ServiceCatalogItem[]>(`${base}${qs}`);
              LAST_GOOD.services = base;
              data = res;
              break;
            } catch (e: any) {
              if (e?.response?.status && e.response.status !== 404) throw e;
            }
          }
          if (data) break;
        }
        if (alive) setCatalog(Array.isArray(data) ? data : []);
      } catch (_e) {
        if (alive) setCatalog([]);
      }
    })();
    return () => {
      alive = false;
    };
  }, [catalogOpen, debouncedServiceQ, selectedFamily?.id]);

  useEffect(() => {
    reload();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [scenarioId]);

  async function reload() {
    setLoading(true);
    setErr(null);
    try {
      const data = await apiGet<ServiceRow[]>(baseUrl);
      setRows(Array.isArray(data) ? data : []);
    } catch (e: any) {
      setErr(e?.response?.data?.detail || e?.message || "Failed to load services.");
    } finally {
      setLoading(false);
    }
  }

  function computeEnd(startY?: number | null, startM?: number | null, dur?: number | null) {
    if (!startY || !startM || !dur || dur <= 0) return { end_year: null, end_month: null };
    const { y, m } = monthAdd(startY, startM, Math.max(0, dur - 1));
    return { end_year: y, end_month: m };
  }

  function withAutoEnd<T extends ServiceRow>(r: T): T {
    const { end_year, end_month } = computeEnd(r.start_year ?? null, r.start_month ?? null, r.duration_months ?? null);
    return { ...r, end_year, end_month };
  }

  // infer source column from category (capex_return, opex, etc.)
  function sourceOf(r: ServiceRow | undefined): string {
    const c = (r?.category || "").toLowerCase();
    if (c === "capex_return") return "Capex Return";
    if (c === "opex") return "OPEX";
    return "n/a";
  }

  function toggleExpand(key: string) {
    setExpanded((m) => ({ ...m, [key]: !m[key] }));
  }

  /* ------------------------------ CRUD Handlers ------------------------------ */

  async function createRow() {
    const payload = withAutoEnd({
      ...draft,
      service_name: (draft.service_name || "").trim(),
      unit: (draft.unit || "") || null,
      vendor: (draft.vendor || "") || null,
      category: (selectedFamily?.name ?? draft.category) || null,
      notes: (draft.notes || "") || null,
      quantity: toNum(draft.quantity, null),
      unit_cost: toNum(draft.unit_cost, null),
      start_year: toInt(draft.start_year, null),
      start_month: draft.start_month ? clamp(toInt(draft.start_month, null) || 0, 1, 12) : null,
      duration_months: toInt(draft.duration_months, null),
      tax_rate: toNum(draft.tax_rate, null),
      escalation_pct: toNum(draft.escalation_pct, null),
    });

    if (!payload.service_name) {
      setErr("Service Name is required.");
      return;
    }

    try {
      await apiPost<ServiceRow>(baseUrl, payload);
      // keep selected family for consecutive adds; clear service field
      setDraft((d) => ({ ...d, service_name: "", quantity: null, unit_cost: null, notes: null }));
      setServiceQ("");
      setCatalog([]);
      setCatalogOpen(false);
      await reload();
      onChanged?.();
    } catch (e: any) {
      setErr(e?.response?.data?.detail || e?.message || "Failed to create service.");
    }
  }

  function startEdit(row: ServiceRow) {
    if (!row.id) return;
    setEditing((m) => ({ ...m, [row.id!]: { ...row } }));
  }

  function cancelEdit(id?: number) {
    if (!id) return;
    setEditing((m) => {
      const { [id]: _omit, ...rest } = m;
      return rest;
    });
  }

  async function saveEdit(id?: number) {
    if (!id) return;
    const row = editing[id];
    if (!row) return;

    const payload = withAutoEnd({
      ...row,
      service_name: (row.service_name || "").trim(),
      unit: (row.unit || "") || null,
      vendor: (row.vendor || "") || null,
      category: (row.category || "") || null,
      notes: (row.notes || "") || null,
      quantity: toNum(row.quantity, null),
      unit_cost: toNum(row.unit_cost, null),
      start_year: toInt(row.start_year, null),
      start_month: row.start_month ? clamp(toInt(row.start_month, null) || 0, 1, 12) : null,
      duration_months: toInt(row.duration_months, null),
      tax_rate: toNum(row.tax_rate, null),
      escalation_pct: toNum(row.escalation_pct, null),
    });

    if (!payload.service_name) {
      setErr("Service Name is required.");
      return;
    }

    try {
      await apiPut<ServiceRow>(`${baseUrl}/${id}`, payload);
      cancelEdit(id);
      await reload();
      onChanged?.();
    } catch (e: any) {
      setErr(e?.response?.data?.detail || e?.message || "Failed to save changes.");
    }
  }

  async function removeRow(id?: number) {
    if (!id) return;
    if (!confirm("Delete this service?")) return;
    try {
      await apiDelete(`${baseUrl}/${id}`);
      await reload();
      onChanged?.();
    } catch (e: any) {
      setErr(e?.response?.data?.detail || e?.message || "Failed to delete service.");
    }
  }

  async function toggleActive(row: ServiceRow) {
    if (!row.id) return;
    try {
      await apiPut<ServiceRow>(`${baseUrl}/${row.id}`, { ...row, is_active: !row.is_active });
      await reload();
      onChanged?.();
    } catch (e: any) {
      setErr(e?.response?.data?.detail || e?.message || "Failed to update status.");
    }
  }

  /* --------------------------------- Render --------------------------------- */

  const totalMonthlyCost = useMemo(() => {
    return rows.reduce((sum, r) => {
      const qty = Number(r.quantity ?? 0);
      const cost = Number(r.unit_cost ?? 0);
      if (!qty || !cost) return sum;
      return sum + qty * cost;
    }, 0);
  }, [rows]);

  const VISIBLE_COLS = 20;

  return (
    <div className="space-y-3">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <h3 className="text-base font-semibold">Services Pricing (Excel parity)</h3>
        <div className="flex items-center gap-3">
          <div className="text-xs text-gray-500">
            Monthly Cost (rough): <span className="font-semibold">{fmt1(totalMonthlyCost)}</span>
          </div>
          {onMarkedReady && (
            <button
              className="px-3 py-1 rounded bg-indigo-600 text-white hover:bg-indigo-700"
              title="Mark Ready and go to Summary"
              onClick={onMarkedReady}
            >
              Mark Ready → Summary
            </button>
          )}
        </div>
      </div>

      {err && (
        <div className="rounded-md border border-red-300 bg-red-50 px-3 py-2 text-sm text-red-800">{err}</div>
      )}

      <div className="overflow-auto rounded-lg border border-gray-200">
        <table className="min-w-[1280px] w-full">
          <thead className="bg-gray-50">
            <tr>
              <HeaderCell>Active</HeaderCell>
              <HeaderCell>Source</HeaderCell>
              <HeaderCell>Service Name</HeaderCell>
              <HeaderCell>Vendor</HeaderCell>
               <HeaderCell className="w-[130px]">Category</HeaderCell>
              <HeaderCell>UoM</HeaderCell>
              <HeaderCell className="text-right">Qty</HeaderCell>
              <HeaderCell className="text-right">Unit Cost</HeaderCell>
              <HeaderCell>Currency</HeaderCell>
              <HeaderCell>Start (Y/M)</HeaderCell>
              <HeaderCell className="text-right">Duration (mo)</HeaderCell>
              <HeaderCell>End (Y/M)</HeaderCell>
              <HeaderCell>Payment Term</HeaderCell>
              <HeaderCell>Cash-out Policy</HeaderCell>
              <HeaderCell className="text-right">Escalation %</HeaderCell>
              <HeaderCell>Esc. Freq</HeaderCell>
              <HeaderCell className="text-right">Tax %</HeaderCell>
              <HeaderCell>Includes Tax?</HeaderCell>
              <HeaderCell>Details</HeaderCell>
              <HeaderCell className="text-right">Actions</HeaderCell>
            </tr>
          </thead>

          <tbody>
            {/* Draft Row */}
            <tr className="bg-white">
              <Cell>
                <input
                  type="checkbox"
                  checked={!!draft.is_active}
                  onChange={(e) => setDraft((d) => ({ ...d, is_active: e.target.checked }))}
                />
              </Cell>

              <Cell title="Source is inferred from Category (capex_return/opex).">n/a</Cell>

              {/* Service Name with typeahead (scoped by selected family) */}
              <Cell className="max-w-[360px]">
                 <div className="flex flex-col">
                  <Typeahead<ServiceCatalogItem>
                    value={serviceQ}
                      onQueryChange={(q) => {
                      setServiceQ(q);
                      setDraft((d) => ({ ...d, service_name: q }));
                    }}
                    options={catalog}
                    open={catalogOpen}
                    setOpen={setCatalogOpen}
                    placeholder={selectedFamily ? "Search services in selected category..." : "Search services..."}
                    onSelect={(item) => {
                      setDraft((d) => ({
                        ...d,
                        service_name: item.name,
                        unit: item.uom ?? d.unit,
                        currency: (item.default_currency as any) || d.currency,
                      }));
                      setServiceQ(item.name);
                    }}
                    renderLine={(item) => (
                      <div className="flex flex-col">
                        <span className="font-medium">{(item as any).name}</span>
                        <span className="text-xs text-gray-500">{(item as any).code}</span>
                      </div>
                    )}
                  />
  
                </div>
              </Cell>

              <Cell>
                <TxtInput
                  placeholder="Vendor"
                  value={draft.vendor ?? ""}
                  onChange={(e) => setDraft((d) => ({ ...d, vendor: e.target.value || null }))}
                />
              </Cell>

              {/* Category (Service Family) with typeahead */}
               <Cell className="min-w-[130px]">
                <Typeahead<ServiceFamily>
                  value={familyQ}
                  onQueryChange={(q) => {
                    setFamilyQ(q);
                    const nextCategory = q.trim().length > 0 ? q : null;
                    setDraft((d) => ({ ...d, category: nextCategory }));
                    setSelectedFamily((prev) => {
                      if (!prev) return prev;
                      return q === prev.name ? prev : null;
                    });
                  }}
                  options={families}
                  open={familyOpen}
                  setOpen={(open) => {
                    setFamilyOpen(open);
                  }}
                  placeholder="Search category (Service Family)..."
                  onSelect={(fam) => {
                    setSelectedFamily(fam);
                    setFamilyQ(fam.name);
                    setDraft((d) => ({ ...d, category: fam.name }));
                  // NOT: serviceQ'yu olduğu gibi bırakıyoruz ki kullanıcı girdisi kaybolmasın.
                      // İstersen katalogu açık tutup anında scoped sonuç gösterebilirsin:
                      // setCatalogOpen(true);
                  }}

                  renderLine={(fam) => (
                    <div className="flex flex-col">
                      <span className="font-medium">{(fam as any).name}</span>
                      <span className="text-xs text-gray-500">{(fam as any).code}</span>
                    </div>
                  )}
                />
                
              </Cell>

              <Cell>
                <TxtInput
                  placeholder="UoM"
                  value={draft.unit ?? ""}
                  onChange={(e) => setDraft((d) => ({ ...d, unit: e.target.value || null }))}
                />
              </Cell>

              <Cell className="text-right">
                <NumInput
                  placeholder="Qty"
                  value={draft.quantity ?? ""}
                  onChange={(e) => setDraft((d) => ({ ...d, quantity: toNum(e.target.value, null) }))}
                />
              </Cell>

              <Cell className="text-right">
                <NumInput
                  placeholder="Unit Cost"
                  value={draft.unit_cost ?? ""}
                  onChange={(e) => setDraft((d) => ({ ...d, unit_cost: toNum(e.target.value, null) }))}
                />
              </Cell>

              <Cell>
                <CurrencySelect
                  value={draft.currency ?? ""}
                  onChange={(v) => setDraft((d) => ({ ...d, currency: v }))}
                />
              </Cell>

              <Cell>
                <div className="flex gap-1">
                  <YearInput
                    value={draft.start_year ?? null}
                    onChange={(v) => {
                      const next = { ...draft, start_year: v };
                      const withEnd = withAutoEnd(next);
                      setDraft(withEnd);
                    }}
                  />
                  <MonthInput
                    value={draft.start_month ?? null}
                    onChange={(v) => {
                      const next = { ...draft, start_month: v };
                      const withEnd = withAutoEnd(next);
                      setDraft(withEnd);
                    }}
                  />
                </div>
              </Cell>

              <Cell className="text-right">
                <NumInput
                  placeholder="Months"
                  value={draft.duration_months ?? ""}
                  onChange={(e) => {
                    const v = toInt(e.target.value, null);
                    const next = { ...draft, duration_months: v };
                    const withEnd = withAutoEnd(next);
                    setDraft(withEnd);
                  }}
                />
              </Cell>

              <Cell>{draft.end_year && draft.end_month ? `${draft.end_year}-${pad2(draft.end_month)}` : "—"}</Cell>

              <Cell>
                <SelectGeneric
                  value={draft.payment_term ?? null}
                  onChange={(v) => setDraft((d) => ({ ...d, payment_term: v }))}
                  options={PAYMENT_TERMS}
                />
              </Cell>

              <Cell>
                <SelectGeneric
                  value={draft.cash_out_month_policy ?? null}
                  onChange={(v) => setDraft((d) => ({ ...d, cash_out_month_policy: v }))}
                  options={CASHOUT_POLICIES}
                />
              </Cell>

              <Cell className="text-right">
                <NumInput
                  placeholder="%"
                  value={draft.escalation_pct ?? ""}
                  onChange={(e) => setDraft((d) => ({ ...d, escalation_pct: toNum(e.target.value, null) }))}
                />
              </Cell>

              <Cell>
                <SelectGeneric
                  value={draft.escalation_freq ?? null}
                  onChange={(v) => setDraft((d) => ({ ...d, escalation_freq: v }))}
                  options={ESC_FREQS}
                />
              </Cell>

              <Cell className="text-right">
                <NumInput
                  placeholder="%"
                  value={draft.tax_rate ?? ""}
                  onChange={(e) => setDraft((d) => ({ ...d, tax_rate: toNum(e.target.value, null) }))}
                />
              </Cell>

              <Cell>
                <input
                  type="checkbox"
                  checked={!!draft.expense_includes_tax}
                  onChange={(e) => setDraft((d) => ({ ...d, expense_includes_tax: e.target.checked }))}
                />
              </Cell>

              <Cell>
                <button
                  type="button"
                  className="inline-flex items-center rounded-md border px-2.5 py-1 text-xs text-gray-700 hover:bg-gray-50"
                  onClick={() => toggleExpand("draft")}
                >
                  {expanded["draft"] ? "Hide" : "Details"}
                </button>
              </Cell>

              <Cell className="text-right">
                <button
                  onClick={createRow}
                  className={cls(
                    "inline-flex items-center rounded-md bg-indigo-600 px-3 py-1.5 text-white text-sm",
                    "hover:bg-indigo-700 focus:outline-none focus:ring-2 focus:ring-indigo-500"
                  )}
                  disabled={loading}
                >
                  Add
                </button>
              </Cell>
            </tr>

            {expanded["draft"] && (
              <tr className="bg-gray-50">
                <Cell colSpan={VISIBLE_COLS}>
                  <div className="p-3">
                    <div className="text-xs text-gray-500 mb-1">Notes</div>
                    <textarea
                      className="w-full rounded-md border px-2 py-1 text-sm outline-none focus:ring-2 focus:ring-indigo-500 border-gray-300"
                      rows={3}
                      placeholder="Notes for this service line…"
                      value={draft.notes ?? ""}
                      onChange={(e) => setDraft((d) => ({ ...d, notes: e.target.value || null }))}
                    />
                  </div>
                </Cell>
              </tr>
            )}

            {/* Data Rows */}
            {rows.map((r) => {
              const ed = r.id ? editing[r.id] : undefined;
              const isEditing = !!ed;
              const view = isEditing ? ed : r;
              const source = sourceOf(view);
              const key = String(r.id);

              return (
                <React.Fragment key={r.id}>
                  <tr className="bg-white hover:bg-gray-50">
                    <Cell>
                      <input
                        type="checkbox"
                        checked={!!view.is_active}
                        onChange={() =>
                          (isEditing
                            ? setEditing((m) => ({ ...m, [r.id!]: { ...ed!, is_active: !ed!.is_active } }))
                            : toggleActive(r)
                          )
                        }
                        disabled={!isEditing}
                      />
                    </Cell>

                    <Cell title={`Derived from category: ${view.category || "n/a"}`}>{source}</Cell>

                    <Cell className="max-w-[360px] truncate" title={view.service_name}>
                      {isEditing ? (
                        <TxtInput
                          value={ed!.service_name}
                          onChange={(e) => setEditing((m) => ({ ...m, [r.id!]: { ...ed!, service_name: e.target.value } }))}
                        />
                      ) : (
                        <span className="font-medium">{view.service_name}</span>
                      )}
                    </Cell>

                    <Cell>
                      {isEditing ? (
                        <TxtInput
                          value={ed!.vendor ?? ""}
                          onChange={(e) => setEditing((m) => ({ ...m, [r.id!]: { ...ed!, vendor: e.target.value || null } }))}
                        />
                      ) : (
                        view.vendor || "—"
                      )}
                    </Cell>

                  <Cell className="min-w-[130px]" title={view.category || ""}>
                      {isEditing ? (
                        <TxtInput
                          value={ed!.category ?? ""}
                          onChange={(e) => setEditing((m) => ({ ...m, [r.id!]: { ...ed!, category: e.target.value || null } }))}
                        />
                      ) : (
                        view.category || "—"
                      )}
                    </Cell>

                    <Cell>
                      {isEditing ? (
                        <TxtInput
                          value={ed!.unit ?? ""}
                          onChange={(e) => setEditing((m) => ({ ...m, [r.id!]: { ...ed!, unit: e.target.value || null } }))}
                        />
                      ) : (
                        view.unit || "—"
                      )}
                    </Cell>

                    <Cell className="text-right">
                      {isEditing ? (
                        <NumInput
                          value={ed!.quantity ?? ""}
                          onChange={(e) =>
                            setEditing((m) => ({ ...m, [r.id!]: { ...ed!, quantity: toNum(e.target.value, null) } }))
                          }
                        />
                      ) : (
                        fmt1(view.quantity)
                      )}
                    </Cell>

                    <Cell className="text-right">
                      {isEditing ? (
                        <NumInput
                          value={ed!.unit_cost ?? ""}
                          onChange={(e) =>
                            setEditing((m) => ({ ...m, [r.id!]: { ...ed!, unit_cost: toNum(e.target.value, null) } }))
                          }
                        />
                      ) : (
                        fmt1(view.unit_cost)
                      )}
                    </Cell>

                    <Cell>{view.currency || "—"}</Cell>

                    <Cell>
                      {isEditing ? (
                        <div className="flex gap-1">
                          <YearInput
                            value={ed!.start_year ?? null}
                            onChange={(v) => {
                              const next = withAutoEnd({ ...ed!, start_year: v });
                              setEditing((m) => ({ ...m, [r.id!]: next }));
                            }}
                          />
                          <MonthInput
                            value={ed!.start_month ?? null}
                            onChange={(v) => {
                              const next = withAutoEnd({ ...ed!, start_month: v });
                              setEditing((m) => ({ ...m, [r.id!]: next }));
                            }}
                          />
                        </div>
                      ) : view.start_year && view.start_month ? (
                        `${view.start_year}-${pad2(view.start_month)}`
                      ) : (
                        "—"
                      )}
                    </Cell>

                    <Cell className="text-right">
                      {isEditing ? (
                        <NumInput
                          value={ed!.duration_months ?? ""}
                          onChange={(e) => {
                            const v = toInt(e.target.value, null);
                            const next = withAutoEnd({ ...ed!, duration_months: v });
                            setEditing((m) => ({ ...m, [r.id!]: next }));
                          }}
                        />
                      ) : (
                        fmt1(view.duration_months)
                      )}
                    </Cell>

                    <Cell>{view.end_year && view.end_month ? `${view.end_year}-${pad2(view.end_month)}` : "—"}</Cell>

                    <Cell>
                      {isEditing ? (
                        <SelectGeneric
                          value={ed!.payment_term ?? null}
                          onChange={(v) => setEditing((m) => ({ ...m, [r.id!]: { ...ed!, payment_term: v } }))}
                          options={PAYMENT_TERMS}
                        />
                      ) : (
                        view.payment_term || "—"
                      )}
                    </Cell>

                    <Cell>
                      {isEditing ? (
                        <SelectGeneric
                          value={ed!.cash_out_month_policy ?? null}
                          onChange={(v) => setEditing((m) => ({ ...m, [r.id!]: { ...ed!, cash_out_month_policy: v } }))}
                          options={CASHOUT_POLICIES}
                        />
                      ) : view.cash_out_month_policy ? (
                        CASHOUT_LABEL[view.cash_out_month_policy]
                      ) : (
                        "—"
                      )}
                    </Cell>

                    <Cell className="text-right">
                      {isEditing ? (
                        <NumInput
                          value={ed!.escalation_pct ?? ""}
                          onChange={(e) =>
                            setEditing((m) => ({ ...m, [r.id!]: { ...ed!, escalation_pct: toNum(e.target.value, null) } }))
                          }
                        />
                      ) : (
                        fmt1(view.escalation_pct)
                      )}
                    </Cell>

                    <Cell>
                      {isEditing ? (
                        <SelectGeneric
                          value={ed!.escalation_freq ?? null}
                          onChange={(v) => setEditing((m) => ({ ...m, [r.id!]: { ...ed!, escalation_freq: v } }))}
                          options={ESC_FREQS}
                        />
                      ) : (
                        view.escalation_freq || "—"
                      )}
                    </Cell>

                    <Cell className="text-right">
                      {isEditing ? (
                        <NumInput
                          value={ed!.tax_rate ?? ""}
                          onChange={(e) =>
                            setEditing((m) => ({ ...m, [r.id!]: { ...ed!, tax_rate: toNum(e.target.value, null) } }))
                          }
                        />
                      ) : (
                        fmt1(view.tax_rate)
                      )}
                    </Cell>

                    <Cell>
                      {isEditing ? (
                        <input
                          type="checkbox"
                          checked={!!ed!.expense_includes_tax}
                          onChange={(e) =>
                            setEditing((m) => ({
                              ...m,
                              [r.id!]: { ...ed!, expense_includes_tax: e.target.checked },
                            }))
                          }
                        />
                      ) : (
                        <input type="checkbox" checked={!!view.expense_includes_tax} readOnly />
                      )}
                    </Cell>

                    <Cell>
                      <button
                        type="button"
                        className="inline-flex items-center rounded-md border px-2.5 py-1 text-xs text-gray-700 hover:bg-gray-50"
                        onClick={() => toggleExpand(key)}
                      >
                        {expanded[key] ? "Hide" : "Details"}
                      </button>
                    </Cell>

                    <Cell className="text-right whitespace-nowrap">
                      {isEditing ? (
                        <>
                          <button
                            onClick={() => saveEdit(r.id)}
                            className="mr-2 inline-flex items-center rounded-md bg-indigo-600 px-2.5 py-1.5 text-white text-xs hover:bg-indigo-700"
                          >
                            Save
                          </button>
                          <button
                            onClick={() => cancelEdit(r.id)}
                            className="inline-flex items-center rounded-md bg-gray-200 px-2.5 py-1.5 text-gray-700 text-xs hover:bg-gray-300"
                          >
                            Cancel
                          </button>
                        </>
                      ) : (
                        <>
                          <button
                            onClick={() => startEdit(r)}
                            className="mr-2 inline-flex items-center rounded-md bg-white border px-2.5 py-1.5 text-gray-700 text-xs hover:bg-gray-50"
                          >
                            Edit
                          </button>
                          <button
                            onClick={() => removeRow(r.id)}
                            className="inline-flex items-center rounded-md bg-rose-600 px-2.5 py-1.5 text-white text-xs hover:bg-rose-700"
                          >
                            Delete
                          </button>
                        </>
                      )}
                    </Cell>
                  </tr>

                  {expanded[key] && (
                    <tr className="bg-gray-50">
                      <Cell colSpan={VISIBLE_COLS}>
                        <div className="p-3 space-y-3">
                          <div>
                            <div className="text-xs text-gray-500 mb-1">Notes</div>
                            {isEditing ? (
                              <textarea
                                className="w-full rounded-md border px-2 py-1 text-sm outline-none focus:ring-2 focus:ring-indigo-500 border-gray-300"
                                rows={3}
                                placeholder="Notes for this service line…"
                                value={ed!.notes ?? ""}
                                onChange={(e) =>
                                  setEditing((m) => ({ ...m, [r.id!]: { ...ed!, notes: e.target.value || null } }))
                                }
                              />
                            ) : (
                              <div className="text-sm text-gray-800 whitespace-pre-wrap">
                                {view.notes || "No notes"}
                              </div>
                            )}
                          </div>
                        </div>
                      </Cell>
                    </tr>
                  )}
                </React.Fragment>
              );
            })}

            {rows.length === 0 && (
              <tr>
                <Cell className="text-center text-gray-500" colSpan={VISIBLE_COLS}>
                  No services yet. Use the draft row above to add new services.
                </Cell>
              </tr>
            )}
          </tbody>
        </table>
      </div>

      {loading && <div className="text-xs text-gray-500">Loading…</div>}
    </div>
  );
}
