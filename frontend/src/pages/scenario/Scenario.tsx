import React, { useEffect, useMemo, useState } from "react";
import { Link, useLocation, useParams, useSearchParams } from "react-router-dom";
import { apiGet, ApiError } from "../../lib/api";

// Tabs
import BOQTable from "../scenario/components/BOQTable";
import TWCTab from "../scenario/tabs/TWCTab";
import CapexTable from "../scenario/components/CapexTable";
import ServicesTable from "../scenario/components/ServicesTable";
// NEW: FX & TAX
import FxTab from "../scenario/tabs/FXTab";
import TaxTab from "../scenario/tabs/TaxTab";
// NEW: Escalation
import EscalationTab from "../scenario/tabs/EscalationTab";
// NEW: Index Series (global data)
import IndexSeriesTab from "../scenario/tabs/IndexSeriesTab";
// NEW: Rise & Fall (formulation)
import RiseAndFallTab from "../scenario/tabs/RiseAndFallTab";
// NEW: Rebates (scenario-level)
import RebatesTab from "../scenario/tabs/RebatesTab";
// NEW: Summary (server-calculated)
import SummaryTab from "../scenario/tabs/SummaryTab";

/* ---------------- Types ---------------- */
type ScenarioDetail = {
  id: number;
  business_case_id: number;
  name: string;
  months: number;
  start_date: string; // ISO
};

type Workflow = {
  scenario_id: number;
  workflow_state?:
    | "draft"
    | "boq_ready"
    | "twc_ready"
    | "capex_ready"
    | "fx_ready"
    | "tax_ready"
    | "services_ready"
    | "ready"
    | string;

  is_boq_ready?: boolean;
  is_twc_ready?: boolean;
  is_capex_ready?: boolean;
  is_fx_ready?: boolean;
  is_tax_ready?: boolean;
  is_services_ready?: boolean;
};

// Tabs (Escalation, Index, Rise&Fall & Rebates are ungated)
type Tab =
  | "pl" // kept for backward-compat — maps to Summary
  | "summary" // preferred name going forward
  | "boq"
  | "twc"
  | "index"
  | "escalation"
  | "rebates"
  | "risefall"
  | "capex"
  | "fx"
  | "tax"
  | "services";

/* ---------------- Utils ---------------- */
function cls(...a: (string | false | undefined)[]) {
  return a.filter(Boolean).join(" ");
}
function fmtDateISO(d: string) {
  try {
    return new Date(d).toISOString().slice(0, 10);
  } catch {
    return d;
  }
}
function isState(ws: string, key: string) {
  return ws === key || ws === `${key}_ready`;
}
function tabBtnClass(active: boolean, disabled?: boolean) {
  return cls(
    "px-3 py-1 rounded border text-sm transition-colors focus:outline-none",
    active
      ? "bg-indigo-600 text-white border-indigo-600 shadow font-semibold"
      : "bg-gray-100 text-gray-800 border-gray-300 hover:bg-gray-200",
    (!active && disabled) && "opacity-50 cursor-not-allowed"
  );
}

// küçük timeout sarmalayıcı
const withTimeout = <T,>(p: Promise<T>, ms = 8000): Promise<T> =>
  new Promise((res, rej) => {
    const t = setTimeout(() => rej(new Error(`Request timed out in ${ms}ms`)), ms);
    p.then((v) => {
      clearTimeout(t);
      res(v);
    }).catch((e) => {
      clearTimeout(t);
      rej(e);
    });
  });

/* ---------------- Component ---------------- */
export default function ScenarioPage() {
  const params = useParams<{ scenarioId?: string; id?: string }>();
  const location = useLocation();
  const [sp, setSp] = useSearchParams();

  // Route’tan ID’yi sağlam al (farklı param isimleri destekli)
  const id = useMemo<number | null>(() => {
    const raw =
      params.scenarioId ??
      params.id ??
      (location.pathname.match(/\/scenarios\/(\d+)/i)?.[1] ?? null);
    if (!raw) return null;
    const n = Number(raw);
    return Number.isFinite(n) && n > 0 ? n : null;
  }, [params, location.pathname]);

  // URL param tab (default: boq). Hatalıysa güvenli default’a düş.
  const tab: Tab = useMemo(() => {
    const t = (sp.get("tab") || "boq").toLowerCase();
    const allowed = new Set<Tab>([
      "pl","summary","boq","twc","index","escalation","rebates","risefall","capex","fx","tax","services"
    ]);
    return (allowed.has(t as Tab) ? (t as Tab) : "boq");
  }, [sp]);

  function setTabRaw(next: Tab) {
    setSp(
      (prev) => {
        const ns = new URLSearchParams(prev);
        ns.set("tab", next);
        return ns;
      },
      { replace: true }
    );
  }

  // Escalation, Index, Rise&Fall ve Rebates her zaman erişilebilir; diğerleri workflow-guarded
  function setTabSafe(next: Tab) {
    if (!flow) {
      setTabRaw(next === "pl" ? "summary" : next);
      return;
    }
    if (next === "twc" && !flow.is_boq_ready) {
      alert("First mark 'Ready' in 1. BOQ.");
      return;
    }
    if (next === "capex" && !flow.is_twc_ready) {
      alert("First mark 'Ready' in 2. TWC.");
      return;
    }
    if (next === "fx" && !flow.is_capex_ready) {
      alert("First mark 'Ready' in 5. CAPEX.");
      return;
    }
    if (next === "tax" && !flow.is_fx_ready) {
      alert("First mark 'Ready' in 6. FX.");
      return;
    }
    if (next === "services" && !flow.is_tax_ready) {
      alert("First mark 'Ready' in 7. TAX.");
      return;
    }
    // Summary (was: P&L) remains gated by services readiness
    if ((next === "pl" || next === "summary") && !flow.is_services_ready) {
      alert("First mark 'Ready' in 8. SERVICES.");
      return;
    }
    setTabRaw(next === "pl" ? "summary" : next);
  }

  const [data, setData] = useState<ScenarioDetail | null>(null);
  const [flow, setFlow] = useState<Workflow | null>(null);
  const [loading, setLoading] = useState(true);
  const [err, setErr] = useState<string | null>(null);

  async function loadAll() {
    if (!id) {
      setErr("Invalid scenario id.");
      setLoading(false);
      return;
    }
    setLoading(true);
    setErr(null);
    try {
      const [scRes, wfRes] = await Promise.allSettled([
        withTimeout(apiGet<ScenarioDetail>(`/business-cases/scenarios/${id}`), 8000),
        withTimeout(apiGet<Workflow>(`/scenarios/${id}/workflow`), 8000),
      ]);

      if (scRes.status === "fulfilled") {
        setData(scRes.value);
      } else {
        const e: any = scRes.reason;
        const msg =
          (e instanceof ApiError && e.message) ||
          e?.response?.data?.detail ||
          e?.message ||
          "Failed to load scenario.";
        setErr(String(msg));
      }

      if (wfRes.status === "fulfilled") {
        setFlow(wfRes.value);
      } else {
        // workflow gelmezse sayfa yine de çalışsın
        setFlow({ scenario_id: id, workflow_state: "draft" });
        console.warn("Workflow load failed:", (wfRes as any).reason);
      }
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    if (id) loadAll();
    else {
      setErr("Invalid scenario id.");
      setLoading(false);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [id]);

  const bcLink = useMemo(
    () => (data ? `/business-cases/${data.business_case_id}` : "#"),
    [data]
  );

  const canGoTWC = !!flow?.is_boq_ready;
  const canGoCAPEX = !!flow?.is_twc_ready;
  const canGoFX = !!flow?.is_capex_ready;
  const canGoTAX = !!flow?.is_fx_ready;
  const canGoSERVICES = !!flow?.is_tax_ready;
  const canGoSUMMARY = !!flow?.is_services_ready; // replaces canGoPL

  const ws = (flow?.workflow_state ?? "draft").toString();
  const stateSafe = ws === "ready" ? "READY" : ws.replace("_ready", "").toUpperCase();

  return (
    <div className="space-y-4">
      {/* Header */}
      <div className="flex items-center justify-between">
        <div>
          <h2 className="text-xl font-semibold">Scenario</h2>
        </div>
        <div className="text-sm">
          {data && (
            <div className="text-sm text-gray-600 mb-2">
              ID: {data.id} • Name: <span className="font-medium">{data.name}</span>{" "}
              • Months: {data.months} • Start: {fmtDateISO(data.start_date)} • BC{" "}
              <Link to={bcLink} className="text-indigo-600 underline">
                #{data.business_case_id}
              </Link>
            </div>
          )}
          {flow && (
            <span
              className={cls(
                "px-2 py-1 rounded font-medium",
                ws === "draft" && "bg-gray-100 text-gray-700",
                isState(ws, "twc") && "bg-amber-100 text-amber-700",
                isState(ws, "capex") && "bg-sky-100 text-sky-700",
                isState(ws, "fx") && "bg-indigo-100 text-indigo-700",
                isState(ws, "tax") && "bg-rose-100 text-rose-700",
                flow.is_tax_ready && !flow.is_services_ready && "bg-purple-100 text-purple-700",
                ws === "ready" && "bg-emerald-100 text-emerald-700"
              )}
              title={`BOQ:${flow.is_boq_ready ? "✓" : "•"}  TWC:${flow.is_twc_ready ? "✓" : "•"}  CAPEX:${flow.is_capex_ready ? "✓" : "•"}  FX:${flow.is_fx_ready ? "✓" : "•"}  TAX:${flow.is_tax_ready ? "✓" : "•"}  SERVICES:${flow.is_services_ready ? "✓" : "•"}`}
            >
              State: {stateSafe}
            </span>
          )}
          <button onClick={loadAll} className="ml-3 px-3 py-1 rounded bg-gray-100 hover:bg-gray-200">
            Refresh
          </button>
        </div>
      </div>

      {/* Tabs — order:
          1. BOQ, 2. TWC, 3. Index, 4. Escalation, (ungated) Rebates & Rise & Fall,
          5. CAPEX, 6. FX, 7. TAX, 8. SERVICES, 9. Summary */}
      <div className="flex gap-2 flex-wrap">
        <button
          onClick={() => setTabSafe("boq")}
          className={tabBtnClass(tab === "boq")}
          title="BOQ (Input)"
        >
          1. BOQ
        </button>

        <button
          onClick={() => setTabSafe("twc")}
          disabled={!canGoTWC}
          className={tabBtnClass(tab === "twc", !canGoTWC)}
          title={!canGoTWC ? "First complete 1. BOQ → Mark Ready." : "TWC (Input)"}
        >
          2. TWC
        </button>

        {/* NEW: Index (ungated) */}
        <button
          onClick={() => setTabRaw("index")}
          className={tabBtnClass(tab === "index")}
          title="Index Series (Manage time series data)"
        >
          3. Index
        </button>

        {/* NEW: Escalation (ungated) */}
        <button
          onClick={() => setTabRaw("escalation")}
          className={tabBtnClass(tab === "escalation")}
          title="Escalation (Policies & resolve)"
        >
          4. Escalation
        </button>

        {/* NEW: Rebates (ungated) */}
        <button
          onClick={() => setTabRaw("rebates")}
          className={tabBtnClass(tab === "rebates")}
          title="Scenario Rebates"
        >
          Rebates
        </button>

        {/* NEW: Rise & Fall (ungated) */}
        <button
          onClick={() => setTabRaw("risefall")}
          className={tabBtnClass(tab === "risefall")}
          title="Rise & Fall (Formulation)"
        >
          Rise & Fall
        </button>

        <button
          onClick={() => setTabSafe("capex")}
          disabled={!canGoCAPEX}
          className={tabBtnClass(tab === "capex", !canGoCAPEX)}
          title={!canGoCAPEX ? "First complete 2. TWC → Mark Ready." : "CAPEX (Input)"}
        >
          5. CAPEX
        </button>

        <button
          onClick={() => setTabSafe("fx")}
          disabled={!canGoFX}
          className={tabBtnClass(tab === "fx", !canGoFX)}
          title={!canGoFX ? "First complete 5. CAPEX → Mark Ready." : "FX (Input)"}
        >
          6. FX
        </button>

        <button
          onClick={() => setTabSafe("tax")}
          disabled={!canGoTAX}
          className={tabBtnClass(tab === "tax", !canGoTAX)}
          title={!canGoTAX ? "First complete 6. FX → Mark Ready." : "TAX (Input)"}
        >
          7. TAX
        </button>

        <button
          onClick={() => setTabSafe("services")}
          disabled={!canGoSERVICES}
          className={tabBtnClass(tab === "services", !canGoSERVICES)}
          title={!canGoSERVICES ? "First complete 7. TAX → Mark Ready." : "Services (Input)"}
        >
          8. SERVICES
        </button>

        {/* Summary (replaces P&L) */}
        <button
          onClick={() => setTabSafe("summary")}
          disabled={!canGoSUMMARY}
          className={tabBtnClass(tab === "summary" || tab === "pl", !canGoSUMMARY)}
          title={!canGoSUMMARY ? "First complete 8. SERVICES → Mark Ready." : "Summary (Output)"}
        >
          9. Summary
        </button>
      </div>

      {loading && <div className="text-sm text-gray-500">Loading…</div>}
      {err && (
        <div className="text-sm text-red-600 bg-red-50 border border-red-200 p-2 rounded">
          {err}
        </div>
      )}

      {/* flow gelmese de data geldiyse render et */}
      {!loading && data && id && (
        <div className="space-y-4">
          {tab === "boq" && (
            <div className="rounded border p-4 bg-white">
              <BOQTable
                scenarioId={id}
                onChanged={loadAll}
                onMarkedReady={async () => {
                  await loadAll();
                  setTabRaw("twc");
                }}
              />
            </div>
          )}

          {tab === "twc" && (
            <div className="rounded border p-4 bg-white">
              <TWCTab
                scenarioId={id}
                onMarkedReady={async () => {
                  await loadAll();
                  setTabRaw("capex");
                }}
              />
            </div>
          )}

          {tab === "index" && (
            <div className="rounded border p-4 bg-white">
              <IndexSeriesTab />
            </div>
          )}

          {tab === "escalation" && (
            <div className="rounded border p-4 bg-white">
              <EscalationTab scenarioId={id} />
            </div>
          )}

          {tab === "rebates" && (
            <div className="rounded border p-4 bg-white">
              <RebatesTab scenarioId={id} />
            </div>
          )}

          {tab === "risefall" && (
            <div className="rounded border p-4 bg-white">
              <RiseAndFallTab scenarioId={id} />
            </div>
          )}

          {tab === "capex" && (
            <div className="rounded border p-4 bg-white">
              <CapexTable
                scenarioId={id}
                onChanged={loadAll}
                onMarkedReady={async () => {
                  await loadAll();
                  setTabRaw("fx");
                }}
              />
            </div>
          )}

          {tab === "fx" && (
            <div className="rounded border p-4 bg-white">
              <FxTab
                scenarioId={id}
                isReady={!!flow?.is_fx_ready}
                onMarkedReady={async () => {
                  await loadAll();
                  setTabRaw("tax");
                }}
              />
            </div>
          )}

          {tab === "tax" && (
            <div className="rounded border p-4 bg-white">
              <TaxTab
                scenarioId={id}
                isReady={!!flow?.is_tax_ready}
                onMarkedReady={async () => {
                  await loadAll();
                  setTabRaw("services");
                }}
              />
            </div>
          )}

          {tab === "services" && (
            <div className="rounded border p-4 bg-white">
              <ServicesTable
                scenarioId={id}
                isReady={!!flow?.is_services_ready}
                onMarkedReady={async () => {
                  await loadAll();
                  setTabRaw("summary");
                }}
              />
            </div>
          )}

          {(tab === "summary" || tab === "pl") && (
            <div className="rounded border p-4 bg-white">
              {/* UPDATED: pass startDate & months into SummaryTab */}
              <SummaryTab
                scenarioId={id}
                startDate={data.start_date}
                months={data.months}
              />
            </div>
          )}
        </div>
      )}
    </div>
  );
}
