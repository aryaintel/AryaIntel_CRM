// frontend/src/pages/scenario/Scenario.tsx
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

// Backend workflow contract
type Workflow = {
  boq_ready: boolean;
  twc_ready: boolean;
  capex_ready: boolean;
  fx_ready: boolean;
  tax_ready: boolean;
  services_ready: boolean;
  rebates_ready: boolean;
  rise_fall_ready: boolean;
  summary_ready: boolean;
  current_stage:
    | "boq"
    | "twc"
    | "capex"
    | "fx"
    | "tax"
    | "services"
    | "rebates"
    | "rise_fall"
    | "summary";
  next_stage:
    | "twc"
    | "capex"
    | "fx"
    | "tax"
    | "services"
    | "rebates"
    | "rise_fall"
    | "summary"
    | null;
};

// Tabs (Escalation, Index, Rise&Fall & Rebates are ungated)
type Tab =
  | "pl"
  | "summary"
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
function tabBtnClass(active: boolean, disabled?: boolean) {
  return cls(
    "px-3 py-1 rounded border text-sm transition-colors focus:outline-none",
    active
      ? "bg-indigo-600 text-white border-indigo-600 shadow font-semibold"
      : "bg-gray-100 text-gray-800 border-gray-300 hover:bg-gray-200",
    !active && disabled && "opacity-50 cursor-not-allowed"
  );
}
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

  const id = useMemo<number | null>(() => {
    const raw =
      params.scenarioId ??
      params.id ??
      (location.pathname.match(/\/scenarios\/(\d+)/i)?.[1] ?? null);
    if (!raw) return null;
    const n = Number(raw);
    return Number.isFinite(n) && n > 0 ? n : null;
  }, [params, location.pathname]);

  const tab: Tab = useMemo(() => {
    const t = (sp.get("tab") || "boq").toLowerCase();
    const allowed = new Set<Tab>([
      "pl", "summary", "boq", "twc", "index", "escalation",
      "rebates", "risefall", "capex", "fx", "tax", "services",
    ]);
    return allowed.has(t as Tab) ? (t as Tab) : "boq";
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
        setFlow(null);
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

  const boqReady = !!flow?.boq_ready;
  const twcReady = !!flow?.twc_ready;
  const capexReady = !!flow?.capex_ready;
  const fxReady = !!flow?.fx_ready;
  const taxReady = !!flow?.tax_ready;
  const servicesReady = !!flow?.services_ready;

  const canGoTWC = boqReady;
  const canGoCAPEX = twcReady;
  const canGoFX = capexReady;
  const canGoTAX = fxReady;
  const canGoSERVICES = taxReady;
  const canGoSUMMARY = servicesReady;

  function setTabSafe(next: Tab) {
    // Ungated areas
    if (next === "index" || next === "escalation" || next === "rebates" || next === "risefall") {
      setTabRaw(next);
      return;
    }
    if (!flow) {
      setTabRaw(next === "pl" ? "summary" : next);
      return;
    }
    if (next === "twc" && !boqReady) {
      alert("First mark 'Ready' in 1. BOQ.");
      return;
    }
    if (next === "capex" && !twcReady) {
      alert("First mark 'Ready' in 2. TWC.");
      return;
    }
    if (next === "fx" && !capexReady) {
      alert("First mark 'Ready' in 5. CAPEX.");
      return;
    }
    if (next === "tax" && !fxReady) {
      alert("First mark 'Ready' in 6. FX.");
      return;
    }
    if (next === "services" && !taxReady) {
      alert("First mark 'Ready' in 7. TAX.");
      return;
    }
    if ((next === "pl" || next === "summary") && !servicesReady) {
      alert("First mark 'Ready' in 8. SERVICES.");
      return;
    }
    setTabRaw(next === "pl" ? "summary" : next);
  }

  const stateBadge = useMemo(() => {
    if (!flow) return { text: "DRAFT", cls: "bg-gray-100 text-gray-700" };
    if (flow.summary_ready) return { text: "READY", cls: "bg-emerald-100 text-emerald-700" };
    const map: Record<Workflow["current_stage"], { text: string; cls: string }> = {
      boq: { text: "BOQ", cls: "bg-gray-100 text-gray-700" },
      twc: { text: "TWC", cls: "bg-amber-100 text-amber-700" },
      capex: { text: "CAPEX", cls: "bg-sky-100 text-sky-700" },
      fx: { text: "FX", cls: "bg-indigo-100 text-indigo-700" },
      tax: { text: "TAX", cls: "bg-rose-100 text-rose-700" },
      services: { text: "SERVICES", cls: "bg-purple-100 text-purple-700" },
      rebates: { text: "REBATES", cls: "bg-teal-100 text-teal-700" },
      rise_fall: { text: "RISE & FALL", cls: "bg-lime-100 text-lime-700" },
      summary: { text: "SUMMARY", cls: "bg-emerald-100 text-emerald-700" },
    };
    return map[flow.current_stage] ?? { text: "DRAFT", cls: "bg-gray-100 text-gray-700" };
  }, [flow]);

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
              className={cls("px-2 py-1 rounded font-medium", stateBadge.cls)}
              title={
                `BOQ:${boqReady ? "✓" : "•"}  ` +
                `TWC:${twcReady ? "✓" : "•"}  ` +
                `CAPEX:${capexReady ? "✓" : "•"}  ` +
                `FX:${fxReady ? "✓" : "•"}  ` +
                `TAX:${taxReady ? "✓" : "•"}  ` +
                `SERVICES:${servicesReady ? "✓" : "•"}  ` +
                `REBATES:${flow.rebates_ready ? "✓" : "•"}  ` +
                `RISE&FALL:${flow.rise_fall_ready ? "✓" : "•"}`
              }
            >
              State: {stateBadge.text}
              {flow.next_stage ? ` → Next: ${flow.next_stage.toUpperCase().replace("_", " & ")}` : ""}
            </span>
          )}
          <button onClick={loadAll} className="ml-3 px-3 py-1 rounded bg-gray-100 hover:bg-gray-200">
            Refresh
          </button>
        </div>
      </div>

      {/* Tabs */}
      <div className="flex gap-2 flex-wrap">
        <button onClick={() => setTabSafe("boq")} className={tabBtnClass(tab === "boq")} title="BOQ (Input)">
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

        <button
          onClick={() => setTabRaw("index")}
          className={tabBtnClass(tab === "index")}
          title="Index Series (Manage time series data)"
        >
          3. Index
        </button>

        <button
          onClick={() => setTabRaw("escalation")}
          className={tabBtnClass(tab === "escalation")}
          title="Escalation (Policies & resolve)"
        >
          4. Escalation
        </button>

        <button
          onClick={() => setTabRaw("rebates")}
          className={tabBtnClass(tab === "rebates")}
          title="Scenario Rebates"
        >
          Rebates
        </button>

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

      {!loading && data && id && (
        <div className="space-y-4">
          {tab === "boq" && (
            <div className="rounded border p-4 bg-white">
              <BOQTable
                scenarioId={id}
                isReady={!!flow?.boq_ready}
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
                  // follow left-to-right → go to Index next
                  setTabRaw("index");
                }}
              />
            </div>
          )}

          {tab === "index" && (
            <div className="rounded border p-4 bg-white space-y-3">
              {/* header with Mark Ready (navigate) */}
              <div className="flex items-center justify-between">
                <div className="text-sm text-gray-700 font-medium">Index Series</div>
                <button
                  className="px-3 py-1 rounded bg-indigo-600 text-white hover:bg-indigo-700"
                  title="Mark Ready and go to 4. Escalation"
                  onClick={() => setTabRaw("escalation")}
                >
                  Mark Ready → Escalation
                </button>
              </div>
              <IndexSeriesTab />
            </div>
          )}

          {tab === "escalation" && (
            <div className="rounded border p-4 bg-white">
              <EscalationTab
                scenarioId={id}
                onMarkedReady={async () => {
                  // Escalation has no server 'ready' flag; just navigate
                  setTabRaw("rebates");
                }}
              />
            </div>
          )}

          {tab === "rebates" && (
            <div className="rounded border p-4 bg-white">
              <RebatesTab
                scenarioId={id}
                onMarkedReady={() => setTabRaw("risefall")}
              />
            </div>
          )}

          {tab === "risefall" && (
            <div className="rounded border p-4 bg-white">
              <RiseAndFallTab
                scenarioId={id}
                onMarkedReady={() => setTabRaw("capex")}
              />
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
                isReady={!!flow?.fx_ready}
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
                isReady={!!flow?.tax_ready}
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
                isReady={!!flow?.services_ready}
                onMarkedReady={async () => {
                  await loadAll();
                  setTabRaw("summary");
                }}
              />
            </div>
          )}

          {(tab === "summary" || tab === "pl") && (
            <div className="rounded border p-4 bg-white">
              <SummaryTab scenarioId={id} startDate={data.start_date} months={data.months} />
            </div>
          )}
        </div>
      )}
    </div>
  );
}
