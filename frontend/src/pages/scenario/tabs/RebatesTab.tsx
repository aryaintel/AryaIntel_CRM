// [BEGIN FILE] frontend/src/pages/scenario/tabs/RebatesTab.tsx
import React, { useEffect, useMemo, useState } from "react";

/**
 * RebatesTab
 * -----------------------------------------------------------------------------
 * Scenario-level rebates management (list, create, edit, delete)
 * Backend API: /api/scenarios/:id/rebates[...]
 * - Runtime API base resolver (ENV → window.__API_URL__ → <meta> → heuristic)
 * - Robust JWT Bearer injection (storage + cookie + global + meta)
 * - Pure React (no external UI deps)
 */

type RebateKind = "percent" | "tier_percent" | "lump_sum";
type RebateScope = "all" | "boq" | "services" | "product";
type RebateBasis = "revenue" | "gross_margin" | "volume";

type RebateRow = {
  id: number;
  scenario_id: number;
  name: string;
  scope: RebateScope;
  kind: RebateKind;
  basis: RebateBasis;
  product_id?: number | null;
  valid_from_year?: number | null;
  valid_from_month?: number | null;
  valid_to_year?: number | null;
  valid_to_month?: number | null;
  accrual_method: "monthly" | "quarterly" | "annual" | "on_invoice";
  pay_month_lag: number;
  is_active: boolean;
  notes?: string | null;
  // kind-specific
  percent?: number | null; // for kind="percent"
  tiers?:
    | Array<{
        id: number;
        rebate_id: number;
        min_value: number;
        max_value?: number | null;
        percent?: number | null;
        amount?: number | null;
        description?: string | null;
        sort_order: number;
      }>
    | null;
  lumps?:
    | Array<{
        id: number;
        rebate_id: number;
        year: number;
        month: number;
        amount: number;
        currency?: string | null;
        note?: string | null;
      }>
    | null;
};

type Draft = {
  name: string;
  scope: RebateScope;
  kind: RebateKind;
  basis: RebateBasis;
  product_id?: string;
  valid_from_year?: string;
  valid_from_month?: string;
  valid_to_year?: string;
  valid_to_month?: string;
  accrual_method: "monthly" | "quarterly" | "annual" | "on_invoice";
  pay_month_lag?: string;
  is_active: boolean;
  notes?: string;

  // percent
  percent_value?: string;

  // tiered
  tiers?: Array<{
    min_value?: string;
    max_value?: string;
    percent?: string;
  }>;

  // lumps (API expects currency/note)
  lumps?: Array<{
    year?: string;
    month?: string;
    amount?: string;
    currency?: string;
    note?: string;
  }>;
};

type EditState =
  | { mode: "none" }
  | { mode: "create"; draft: Draft }
  | { mode: "edit"; id: number; draft: Draft };

function useScenarioIdFromUrl(): number | undefined {
  try {
    const m = window.location.pathname.match(/\/scenarios\/(\d+)/i);
    if (m && m[1]) return Number(m[1]);
  } catch {}
  return undefined;
}

function resolveApiBase(): string {
  // 1) Vite env
  // @ts-ignore
  const envBase = typeof import.meta !== "undefined" ? import.meta?.env?.VITE_API_URL : "";
  if (envBase) return String(envBase).replace(/\/+$/, "");

  // 2) window global override
  // @ts-ignore
  if (typeof window !== "undefined" && (window as any).__API_URL__) {
    // @ts-ignore
    return String((window as any).__API_URL__).replace(/\/+$/, "");
  }

  // 3) <meta name="api-base" content="http://127.0.0.1:8000">
  if (typeof document !== "undefined") {
    const meta = document.querySelector('meta[name="api-base"]') as HTMLMetaElement | null;
    if (meta?.content) return meta.content.replace(/\/+$/, "");
  }

  // 4) Same-origin heuristic: :5173 → :8000
  try {
    const { protocol, hostname, port } = window.location;
    const p = Number(port || (protocol === "https:" ? 443 : 80));
    const backendPort = [5173, 3000, 5174, 8080].includes(p) ? 8000 : p;
    return `${protocol}//${hostname}:${backendPort}`;
  } catch {}

  // 5) Fallback
  return "";
}
const API_BASE = resolveApiBase();

// swagger’da gördüğümüz yapı için default prefix /api
function getApiPrefix(): string {
  try {
    // @ts-ignore
    const envPref = typeof import.meta !== "undefined" ? import.meta?.env?.VITE_API_PREFIX : "";
    if (envPref) return String(envPref);
  } catch {}
  // @ts-ignore
  if (typeof window !== "undefined" && (window as any).__API_PREFIX__) {
    // @ts-ignore
    return String((window as any).__API_PREFIX__);
  }
  // meta
  try {
    const meta = document.querySelector('meta[name="api-prefix"]') as HTMLMetaElement | null;
    if (meta?.content) return meta.content;
  } catch {}
  // varsayılan
  return "/api";
}
const API_PREFIX = getApiPrefix();

function readCsrfToken(): string | undefined {
  try {
    const meta = document.querySelector('meta[name="csrf-token"]') as HTMLMetaElement | null;
    return meta?.content || undefined;
  } catch {
    return undefined;
  }
}

function looksLikeJwt(s: string): boolean {
  return /^[A-Za-z0-9-_]+\.[A-Za-z0-9-_]+\.[A-Za-z0-9-_]+$/.test(s);
}

function deepFindJwt(obj: any): string | undefined {
  const seen = new Set<any>();
  const stack = [obj];
  while (stack.length) {
    const cur = stack.pop();
    if (cur && typeof cur === "object" && !seen.has(cur)) {
      seen.add(cur);
      for (const k of Object.keys(cur)) {
        const v = cur[k];
        if (typeof v === "string") {
          if (v.startsWith("Bearer ") && looksLikeJwt(v.slice(7))) return v;
          if (looksLikeJwt(v)) return `Bearer ${v}`;
        } else if (v && typeof v === "object") {
          stack.push(v);
        }
      }
    }
  }
  return undefined;
}

/** App genelinde kullanılan JWT token'ı (varsa) yakala (storage + cookie + global + meta) */
function getBearerToken(): string | undefined {
  try {
    // 0) Meta tag
    const meta = document.querySelector('meta[name="auth-token"]') as HTMLMetaElement | null;
    if (meta?.content) {
      const t = meta.content.trim();
      if (t.startsWith("Bearer ")) return t;
      if (looksLikeJwt(t)) return `Bearer ${t}`;
    }

    // 1) Global köprüler
    // @ts-ignore
    const w: any = window;
    if (w?.__AUTH__?.token) {
      const t = String(w.__AUTH__.token);
      if (t.startsWith("Bearer ")) return t;
      if (looksLikeJwt(t)) return `Bearer ${t}`;
    }
    if (w?.__AUTH_TOKEN__) {
      const t = String(w.__AUTH_TOKEN__);
      if (t.startsWith("Bearer ")) return t;
      if (looksLikeJwt(t)) return `Bearer ${t}`;
    }

    // 2) Storage — hedef anahtarlar (hızlı yol)
    const stores = [localStorage, sessionStorage] as const;
    const fastKeys = [
      "Authorization",
      "access_token",
      "token",
      "jwt",
      "bearer",
      "id_token",
      // not: app’te kullanılan "aryaintel_token" deep scan’de yakalanıyor (aşağıda)
    ];
    for (const st of stores) {
      for (const key of fastKeys) {
        const raw = st.getItem(key) || "";
        if (!raw) continue;
        if (raw.startsWith("Bearer ") && looksLikeJwt(raw.slice(7))) return raw;
        if (looksLikeJwt(raw)) return `Bearer ${raw}`;
        try {
          const obj = JSON.parse(raw);
          const found = deepFindJwt(obj);
          if (found) return found;
        } catch {}
      }
    }
    // 3) Storage — tüm anahtarlar (derin tarama)
    for (const st of stores) {
      for (let i = 0; i < st.length; i++) {
        const key = st.key(i)!;
        const raw = st.getItem(key) || "";
        if (raw.startsWith("Bearer ") && looksLikeJwt(raw.slice(7))) return raw;
        if (looksLikeJwt(raw)) return `Bearer ${raw}`;
        try {
          const obj = JSON.parse(raw);
          const found = deepFindJwt(obj);
          if (found) return found;
        } catch {}
      }
    }

    // 4) Cookie — HTTPOnly değilse (örn. 'access_token=...') yakala
    const cookies = document.cookie?.split(";").map((s) => s.trim()) || [];
    const cookieCandidates = ["Authorization", "access_token", "token", "jwt", "bearer", "id_token"];
    for (const c of cookies) {
      const [k, v] = c.split("=") as [string, string];
      if (!k || !v) continue;
      if (!cookieCandidates.includes(k)) continue;
      const val = decodeURIComponent(v);
      if (val.startsWith("Bearer ") && looksLikeJwt(val.slice(7))) return val;
      if (looksLikeJwt(val)) return `Bearer ${val}`;
      try {
        const obj = JSON.parse(val);
        const found = deepFindJwt(obj);
        if (found) return found;
      } catch {}
    }
  } catch {}
  return undefined;
}

const MONTHS = Array.from({ length: 12 }, (_, i) => i + 1);

const cellClass = "px-2 py-1 border-b border-gray-200 text-sm";

// -------------------------- API HELPERS ---------------------

type RequestInitEx = RequestInit & { query?: Record<string, any> };

async function api<T>(path: string, init?: RequestInitEx): Promise<T> {
  const base = API_BASE || window.location.origin;
  const cleanPath = path.startsWith("/") ? path : `/${path}`;
  const withPrefix = `${API_PREFIX.replace(/\/+$/, "")}${cleanPath}`;
  const url = new URL(withPrefix, base);

  if (init?.query) {
    for (const [k, v] of Object.entries(init.query)) {
      if (v !== undefined && v !== null) url.searchParams.set(k, String(v));
    }
  }

  const headers: Record<string, string> = {
    Accept: "application/json",
    ...(init?.headers as Record<string, string>),
  };

  // CSRF + Ajax
  headers["X-Requested-With"] = headers["X-Requested-With"] || "XMLHttpRequest";
  const csrf = readCsrfToken();
  if (csrf && !headers["X-CSRF-Token"]) headers["X-CSRF-Token"] = csrf;

  // Authorization
  if (!headers["Authorization"]) {
    const bearer = getBearerToken();
    if (bearer) headers["Authorization"] = bearer;
  }

  // headers must be applied last so Authorization is preserved
  const res = await fetch(url.toString(), {
    ...init,
    credentials: "include",
    headers,
  });

  if (!res.ok) {
    let detail = "";
    try {
      const raw = await res.clone().json();
      if (raw?.detail) {
        if (typeof raw.detail === "string") detail = raw.detail;
        else if (Array.isArray(raw.detail) && raw.detail[0]?.msg) detail = raw.detail[0].msg;
      } else if (raw?.message) {
        detail = raw.message;
      }
    } catch {}
    const msg = `${res.status} ${res.statusText}${detail ? `: ${detail}` : ""}`;
    throw new Error(msg);
  }

  if (res.status === 204) return undefined as T;

  // Try JSON
  try {
    return (await res.json()) as T;
  } catch {
    // Plain text fallback
    const txt = await res.text();
    return txt as unknown as T;
  }
}

function toIntOrNull(x?: string): number | null {
  if (x == null || x === "") return null;
  const n = Number(x);
  return Number.isFinite(n) ? Math.trunc(n) : null;
}
function toNumOrNull(x?: string): number | null {
  if (x == null || x === "") return null;
  const n = Number(x);
  return Number.isFinite(n) ? n : null;
}

function emptyDraft(): Draft {
  return {
    name: "",
    scope: "all",
    kind: "percent",
    basis: "revenue",
    accrual_method: "monthly",
    pay_month_lag: "0",
    is_active: true,
    notes: "",
    percent_value: "",
    tiers: [],
    lumps: [],
  };
}

function rowToDraft(r: RebateRow): Draft {
  return {
    name: r.name,
    scope: r.scope,
    kind: r.kind,
    basis: r.basis,
    product_id: r.product_id != null ? String(r.product_id) : "",
    valid_from_year: r.valid_from_year != null ? String(r.valid_from_year) : "",
    valid_from_month: r.valid_from_month != null ? String(r.valid_from_month) : "",
    valid_to_year: r.valid_to_year != null ? String(r.valid_to_year) : "",
    valid_to_month: r.valid_to_month != null ? String(r.valid_to_month) : "",
    accrual_method: r.accrual_method,
    pay_month_lag: String(r.pay_month_lag ?? 0),
    is_active: !!r.is_active,
    notes: r.notes ?? "",
    percent_value: r.percent != null ? String(r.percent) : "",
    tiers: (r.tiers || [])?.map((t) => ({
      min_value: String(t.min_value ?? 0),
      max_value: t.max_value == null ? "" : String(t.max_value),
      percent: String(t.percent ?? 0),
    })),
    lumps: (r.lumps || [])?.map((l) => ({
      year: String(l.year ?? ""),
      month: String(l.month ?? ""),
      amount: String(l.amount ?? 0),
      currency: l.currency ?? "USD",
      note: l.note ?? "",
    })),
  };
}

function buildSubmitBody(d: Draft) {
  const base = {
    name: d.name.trim(),
    scope: d.scope,
    kind: d.kind,
    basis: d.basis,
    product_id: toIntOrNull(d.product_id),
    valid_from_year: toIntOrNull(d.valid_from_year),
    valid_from_month: toIntOrNull(d.valid_from_month),
    valid_to_year: toIntOrNull(d.valid_to_year),
    valid_to_month: toIntOrNull(d.valid_to_month),
    accrual_method: d.accrual_method,
    pay_month_lag: toIntOrNull(d.pay_month_lag) ?? 0,
    is_active: !!d.is_active,
    notes: d.notes || "",
  };

  if (d.kind === "percent") {
    const percent = toNumOrNull(d.percent_value) ?? 0;
    return { ...base, percent };
  }

  if (d.kind === "tier_percent") {
    const tiers = (d.tiers || []).map((t, idx) => ({
      min_value: Number(t.min_value ?? 0),
      max_value: t.max_value == null || t.max_value === "" ? null : Number(t.max_value),
      percent: t.percent == null || t.percent === "" ? 0 : Number(t.percent),
      sort_order: idx,
    }));
    return { ...base, tiers };
  }

  // lump_sum
  const lumps = (d.lumps || []).map((l) => ({
    year: Number(l.year ?? 0),
    month: Number(l.month ?? 0),
    amount: Number(l.amount ?? 0),
    currency: (l.currency && l.currency.trim()) || "USD",
    note: l.note || "",
  }));
  return { ...base, lumps };
}

function formatValidity(
  fromY?: number | null,
  fromM?: number | null,
  toY?: number | null,
  toM?: number | null
) {
  const p1 = fromY && fromM ? `${String(fromM).padStart(2, "0")}/${fromY}` : "—";
  const p2 = toY && toM ? `${String(toM).padStart(2, "0")}/${toY}` : "—";
  return `${p1} → ${p2}`;
}

function fmt(n?: number | null) {
  if (n == null || Number.isNaN(n)) return "—";
  return String(n);
}

function pct(n?: number | null) {
  if (n == null || Number.isNaN(n)) return "—";
  return `${n}%`;
}

function ym(y?: number | null, m?: number | null) {
  if (!y || !m) return "—";
  return `${String(m).padStart(2, "0")}/${y}`;
}

// -------------------------- UI ---------------------

export default function RebatesTab(props: { scenarioId?: number }) {
  const urlScenarioId = useScenarioIdFromUrl();
  const scenarioId = props.scenarioId ?? urlScenarioId;

  const [items, setItems] = useState<RebateRow[]>([]);
  const [loading, setLoading] = useState(false);
  const [err, setErr] = useState<string | null>(null);
  const [edit, setEdit] = useState<EditState>({ mode: "none" });
  const [refreshTick, setRefreshTick] = useState(0);
  const [expanded, setExpanded] = useState<Record<number, boolean>>({});
  const doRefresh = () => setRefreshTick((t) => t + 1);

  useEffect(() => {
    if (!scenarioId) return;
    let ignore = false;
    setLoading(true);
    setErr(null);
    api<RebateRow[]>(`/scenarios/${scenarioId}/rebates`, {
      query: { include_details: true },
    })
      .then((rows) => {
        if (ignore) return;
        setItems(rows);
      })
      .catch((e) => !ignore && setErr(e.message || String(e)))
      .finally(() => !ignore && setLoading(false));
    return () => {
      ignore = true;
    };
  }, [scenarioId, refreshTick]);

  const startCreate = () => setEdit({ mode: "create", draft: emptyDraft() });

  const startEdit = (row: RebateRow) => {
    setEdit({ mode: "edit", id: row.id, draft: rowToDraft(row) });
  };

  const cancelEdit = () => setEdit({ mode: "none" });

  const remove = async (row: RebateRow) => {
    if (!scenarioId) return;
    if (!confirm(`Delete rebate "${row.name}"?`)) return;
    try {
      await api(`/scenarios/${scenarioId}/rebates/${row.id}`, {
        method: "DELETE",
      });
      doRefresh();
    } catch (e: any) {
      alert(e?.message || String(e));
    }
  };

  const toggleActive = async (row: RebateRow) => {
    if (!scenarioId) return;
    try {
      const draft = rowToDraft(row);
      draft.is_active = !row.is_active;
      const body = buildSubmitBody(draft);
      await api(`/scenarios/${scenarioId}/rebates/${row.id}`, {
        method: "PUT",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(body),
      });
      doRefresh();
    } catch (e: any) {
      alert(e?.message || String(e));
    }
  };

  const onSave = async () => {
    if (!scenarioId) return;
    if (edit.mode === "none") return;

    const d = edit.draft;
    if (!d.name || !d.kind || !d.scope || !d.basis) {
      alert("name, kind, scope and basis are required.");
      return;
    }
    if (d.kind === "percent" && (d.percent_value === undefined || d.percent_value === null || d.percent_value === "")) {
      alert("percent_value is required for kind='percent'.");
      return;
    }

    const body = buildSubmitBody(d);

    try {
      if (edit.mode === "create") {
        await api(`/scenarios/${scenarioId}/rebates`, {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify(body),
        });
      } else {
        await api(`/scenarios/${scenarioId}/rebates/${edit.id}`, {
          method: "PUT",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify(body),
        });
      }
      setEdit({ mode: "none" });
      doRefresh();
    } catch (e: any) {
      alert(e?.message || String(e));
    }
  };

  const toggleDetails = (id: number) => {
    setExpanded((prev) => ({ ...prev, [id]: !prev[id] }));
  };

  const renderDetails = (r: RebateRow) => {
    return (
      <div className="bg-gray-50 rounded p-3 text-xs text-gray-700">
        {/* Notes */}
        {(r.notes && r.notes.trim() !== "") && (
          <div className="mb-2">
            <span className="font-semibold">Notes:</span> {r.notes}
          </div>
        )}

        {/* Percent summary */}
        {r.kind === "percent" && (
          <div className="mb-2">
            <span className="font-semibold">Flat Percent:</span> {pct(r.percent)}
          </div>
        )}

        {/* Tiers summary */}
        {r.kind === "tier_percent" && (
          <div className="mb-2">
            <div className="font-semibold mb-1">Tiers:</div>
            {(r.tiers && r.tiers.length > 0) ? (
              <div className="overflow-x-auto">
                <table className="min-w-[640px] border border-gray-200">
                  <thead className="bg-white">
                    <tr>
                      <th className="px-2 py-1 border-b text-left">#</th>
                      <th className="px-2 py-1 border-b text-left">Min</th>
                      <th className="px-2 py-1 border-b text-left">Max</th>
                      <th className="px-2 py-1 border-b text-left">%</th>
                      <th className="px-2 py-1 border-b text-left">Amount</th>
                      <th className="px-2 py-1 border-b text-left">Desc</th>
                    </tr>
                  </thead>
                  <tbody>
                    {[...r.tiers].sort((a, b) => (a.sort_order ?? 0) - (b.sort_order ?? 0)).map((t, i) => (
                      <tr key={t.id ?? i} className="odd:bg-gray-50">
                        <td className="px-2 py-1 border-b">{t.sort_order ?? i}</td>
                        <td className="px-2 py-1 border-b">{fmt(t.min_value)}</td>
                        <td className="px-2 py-1 border-b">{t.max_value == null ? "∞" : fmt(t.max_value)}</td>
                        <td className="px-2 py-1 border-b">{t.percent == null ? "—" : `${t.percent}%`}</td>
                        <td className="px-2 py-1 border-b">{t.amount == null ? "—" : fmt(t.amount)}</td>
                        <td className="px-2 py-1 border-b">{t.description || "—"}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            ) : (
              <div className="text-gray-500">No tiers.</div>
            )}
          </div>
        )}

        {/* Lumps summary */}
        {r.kind === "lump_sum" && (
          <div className="mb-2">
            <div className="font-semibold mb-1">Lump Sums:</div>
            {(r.lumps && r.lumps.length > 0) ? (
              <div className="overflow-x-auto">
                <table className="min-w-[640px] border border-gray-200">
                  <thead className="bg-white">
                    <tr>
                      <th className="px-2 py-1 border-b text-left">Year/Month</th>
                      <th className="px-2 py-1 border-b text-left">Amount</th>
                      <th className="px-2 py-1 border-b text-left">Currency</th>
                      <th className="px-2 py-1 border-b text-left">Note</th>
                    </tr>
                  </thead>
                  <tbody>
                    {r.lumps.map((l, i) => (
                      <tr key={l.id ?? i} className="odd:bg-gray-50">
                        <td className="px-2 py-1 border-b">{ym(l.year, l.month)}</td>
                        <td className="px-2 py-1 border-b">{fmt(l.amount)}</td>
                        <td className="px-2 py-1 border-b">{l.currency || "USD"}</td>
                        <td className="px-2 py-1 border-b">{l.note || "—"}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            ) : (
              <div className="text-gray-500">No lump entries.</div>
            )}
          </div>
        )}
      </div>
    );
  };

  return (
    <div className="space-y-4">
      {/* List */}
      <div className="rounded border p-4 bg-white">
        <div className="flex justify-between items-center mb-3">
          <h3 className="font-semibold">Scenario Rebates</h3>
          <div className="flex gap-2">
            <button className="btn btn-secondary" onClick={doRefresh}>
              Refresh
            </button>
            <button className="btn btn-primary" onClick={startCreate}>
              New Rebate
            </button>
          </div>
        </div>
        {loading && <div className="text-sm text-gray-500">Loading...</div>}
        {err && <div className="text-sm text-red-600">{err}</div>}
        {!loading && !err && items.length === 0 && (
          <div className="text-sm text-gray-500">No rebates yet. Click “New Rebate”.</div>
        )}
        {items.length > 0 && (
          <table className="w-full text-sm">
            <thead>
              <tr className="text-left text-gray-500">
                <th className={cellClass}>Name</th>
                <th className={cellClass}>Kind</th>
                <th className={cellClass}>Scope</th>
                <th className={cellClass}>Basis</th>
                <th className={cellClass}>Validity</th>
                <th className={cellClass}>Accrual</th>
                <th className={cellClass}>Lag</th>
                <th className={cellClass}>Status</th>
                <th className={cellClass}>Actions</th>
              </tr>
            </thead>
            <tbody>
              {items.map((r) => (
                <React.Fragment key={r.id}>
                  <tr>
                    <td className={cellClass}>{r.name}</td>
                    <td className={cellClass}>{r.kind}</td>
                    <td className={cellClass}>{r.scope}</td>
                    <td className={cellClass}>{r.basis}</td>
                    <td className={cellClass}>
                      {formatValidity(
                        r.valid_from_year,
                        r.valid_from_month,
                        r.valid_to_year,
                        r.valid_to_month
                      )}
                    </td>
                    <td className={cellClass}>{r.accrual_method}</td>
                    <td className={cellClass}>{r.pay_month_lag ?? 0}</td>
                    <td className={cellClass}>
                      <span className={r.is_active ? "text-green-600" : "text-gray-500"}>
                        {r.is_active ? "Active" : "Inactive"}
                      </span>
                    </td>
                    <td className={cellClass}>
                      <div className="flex gap-2">
                        <button className="btn btn-xs" onClick={() => startEdit(r)}>
                          Edit
                        </button>
                        <button className="btn btn-xs" onClick={() => toggleActive(r)}>
                          {r.is_active ? "Deactivate" : "Activate"}
                        </button>
                        <button className="btn btn-xs" onClick={() => toggleDetails(r.id)}>
                          {expanded[r.id] ? "Hide" : "Details"}
                        </button>
                        <button className="btn btn-xs btn-danger" onClick={() => remove(r)}>
                          Delete
                        </button>
                      </div>
                    </td>
                  </tr>

                  {expanded[r.id] && (
                    <tr>
                      <td className="px-2 py-2 bg-gray-50" colSpan={9}>
                        {renderDetails(r)}
                      </td>
                    </tr>
                  )}
                </React.Fragment>
              ))}
            </tbody>
          </table>
        )}
      </div>

      {/* Create / Edit Form */}
      {(edit.mode === "create" || edit.mode === "edit") && (
        <div className="rounded border p-4 bg-white">
          <h3 className="font-semibold mb-3">
            {edit.mode === "create" ? "Create Rebate" : "Edit Rebate"}
          </h3>

          {/* Basic fields */}
          <div className="grid grid-cols-2 gap-4">
            <div>
              <label className="block text-xs text-gray-500 mb-1">Name</label>
              <input
                className="w-full border rounded px-2 py-1"
                value={edit.draft.name}
                onChange={(e) => setEdit({ ...edit, draft: { ...edit.draft, name: e.target.value } })}
              />
            </div>
            <div>
              <label className="block text-xs text-gray-500 mb-1">Scope</label>
              <select
                className="w-full border rounded px-2 py-1"
                value={edit.draft.scope}
                onChange={(e) =>
                  setEdit({ ...edit, draft: { ...edit.draft, scope: e.target.value as RebateScope } })
                }
              >
                <option value="all">all</option>
                <option value="boq">boq</option>
                <option value="services">services</option>
                <option value="product">product</option>
              </select>
            </div>
            <div>
              <label className="block text-xs text-gray-500 mb-1">Kind</label>
              <select
                className="w-full border rounded px-2 py-1"
                value={edit.draft.kind}
                onChange={(e) =>
                  setEdit({ ...edit, draft: { ...edit.draft, kind: e.target.value as RebateKind } })
                }
              >
                <option value="percent">percent</option>
                <option value="tier_percent">tier_percent</option>
                <option value="lump_sum">lump_sum</option>
              </select>
            </div>
            <div>
              <label className="block text-xs text-gray-500 mb-1">Basis</label>
              <select
                className="w-full border rounded px-2 py-1"
                value={edit.draft.basis}
                onChange={(e) =>
                  setEdit({ ...edit, draft: { ...edit.draft, basis: e.target.value as RebateBasis } })
                }
              >
                <option value="revenue">revenue</option>
                <option value="gross_margin">gross_margin</option>
                <option value="volume">volume</option>
              </select>
            </div>
            <div>
              <label className="block text-xs text-gray-500 mb-1">Product ID (when scope=product)</label>
              <input
                className="w-full border rounded px-2 py-1"
                placeholder="e.g. 101"
                value={edit.draft.product_id || ""}
                onChange={(e) =>
                  setEdit({ ...edit, draft: { ...edit.draft, product_id: e.target.value } })
                }
              />
            </div>
            <div>
              <label className="block text-xs text-gray-500 mb-1">Accrual Method</label>
              <select
                className="w-full border rounded px-2 py-1"
                value={edit.draft.accrual_method}
                onChange={(e) =>
                  setEdit({
                    ...edit,
                    draft: { ...edit.draft, accrual_method: e.target.value as any },
                  })
                }
              >
                <option value="monthly">monthly</option>
                <option value="quarterly">quarterly</option>
                <option value="annual">annual</option>
                <option value="on_invoice">on_invoice</option>
              </select>
            </div>
            <div>
              <label className="block text-xs text-gray-500 mb-1">Pay Month Lag</label>
              <input
                className="w-full border rounded px-2 py-1"
                value={edit.draft.pay_month_lag || "0"}
                onChange={(e) =>
                  setEdit({ ...edit, draft: { ...edit.draft, pay_month_lag: e.target.value } })
                }
              />
            </div>
            <div>
              <label className="block text-xs text-gray-500 mb-1">Notes</label>
              <textarea
                className="w-full border rounded px-2 py-1"
                value={edit.draft.notes || ""}
                onChange={(e) =>
                  setEdit({ ...edit, draft: { ...edit.draft, notes: e.target.value } })
                }
              />
            </div>
          </div>

          {/* Conditional sections */}
          {edit.draft.kind === "percent" && (
            <div className="mt-4">
              <label className="block text-xs text-gray-500 mb-1">Flat percent</label>
              <input
                className="w-full border rounded px-2 py-1"
                placeholder="Percent (%)"
                value={edit.draft.percent_value || ""}
                onChange={(e) =>
                  setEdit({ ...edit, draft: { ...edit.draft, percent_value: e.target.value } })
                }
              />
            </div>
          )}

          {edit.draft.kind === "tier_percent" && (
            <div className="mt-4">
              <div className="text-xs text-gray-500 mb-1">Tiers</div>
              {(edit.draft.tiers || []).map((t, i) => (
                <div className="grid grid-cols-3 gap-2 mb-2" key={i}>
                  <input
                    className="border rounded px-2 py-1"
                    placeholder="Min value"
                    value={t.min_value || ""}
                    onChange={(e) => {
                      const tiers = [...(edit.draft.tiers || [])];
                      tiers[i] = { ...tiers[i], min_value: e.target.value };
                      setEdit({ ...edit, draft: { ...edit.draft, tiers } });
                    }}
                  />
                  <input
                    className="border rounded px-2 py-1"
                    placeholder="Max value (optional)"
                    value={t.max_value || ""}
                    onChange={(e) => {
                      const tiers = [...(edit.draft.tiers || [])];
                      tiers[i] = { ...tiers[i], max_value: e.target.value };
                      setEdit({ ...edit, draft: { ...edit.draft, tiers } });
                    }}
                  />
                  <input
                    className="border rounded px-2 py-1"
                    placeholder="Percent (%)"
                    value={t.percent || ""}
                    onChange={(e) => {
                      const tiers = [...(edit.draft.tiers || [])];
                      tiers[i] = { ...tiers[i], percent: e.target.value };
                      setEdit({ ...edit, draft: { ...edit.draft, tiers } });
                    }}
                  />
                </div>
              ))}
              <button
                className="btn btn-xs"
                onClick={() =>
                  setEdit({
                    ...edit,
                    draft: { ...edit.draft, tiers: [...(edit.draft.tiers || []), {}] },
                  })
                }
              >
                + Add Tier
              </button>
            </div>
          )}

          {edit.draft.kind === "lump_sum" && (
            <div className="mt-4">
              <div className="text-xs text-gray-500 mb-1">Lump sums</div>
              {(edit.draft.lumps || []).map((l, i) => (
                <div className="grid grid-cols-5 gap-2 mb-2" key={i}>
                  <input
                    className="border rounded px-2 py-1"
                    placeholder="Year"
                    value={l.year || ""}
                    onChange={(e) => {
                      const lumps = [...(edit.draft.lumps || [])];
                      lumps[i] = { ...lumps[i], year: e.target.value };
                      setEdit({ ...edit, draft: { ...edit.draft, lumps } });
                    }}
                  />
                  <select
                    className="border rounded px-2 py-1"
                    value={l.month || ""}
                    onChange={(e) => {
                      const lumps = [...(edit.draft.lumps || [])];
                      lumps[i] = { ...lumps[i], month: e.target.value };
                      setEdit({ ...edit, draft: { ...edit.draft, lumps } });
                    }}
                  >
                    <option value="">--</option>
                    {MONTHS.map((m) => (
                      <option key={m} value={m}>
                        {m}
                      </option>
                    ))}
                  </select>
                  <input
                    className="border rounded px-2 py-1"
                    placeholder="Amount"
                    value={l.amount || ""}
                    onChange={(e) => {
                      const lumps = [...(edit.draft.lumps || [])];
                      lumps[i] = { ...lumps[i], amount: e.target.value };
                      setEdit({ ...edit, draft: { ...edit.draft, lumps } });
                    }}
                  />
                  <input
                    className="border rounded px-2 py-1"
                    placeholder="Currency (e.g. USD)"
                    value={l.currency || "USD"}
                    onChange={(e) => {
                      const lumps = [...(edit.draft.lumps || [])];
                      lumps[i] = { ...lumps[i], currency: e.target.value };
                      setEdit({ ...edit, draft: { ...edit.draft, lumps } });
                    }}
                  />
                  <input
                    className="border rounded px-2 py-1"
                    placeholder="Note"
                    value={l.note || ""}
                    onChange={(e) => {
                      const lumps = [...(edit.draft.lumps || [])];
                      lumps[i] = { ...lumps[i], note: e.target.value };
                      setEdit({ ...edit, draft: { ...edit.draft, lumps } });
                    }}
                  />
                </div>
              ))}
              <button
                className="btn btn-xs"
                onClick={() =>
                  setEdit({
                    ...edit,
                    draft: { ...edit.draft, lumps: [...(edit.draft.lumps || []), { currency: "USD" }] },
                  })
                }
              >
                + Add Lump
              </button>
            </div>
          )}

          {/* Actions */}
          <div className="mt-4 flex gap-2">
            <button className="btn btn-secondary" onClick={cancelEdit}>
              Cancel
            </button>
            <button className="btn btn-primary" onClick={onSave}>
              Save
            </button>
          </div>
        </div>
      )}
    </div>
  );
}
// [END FILE]
