// relative path: frontend/src/pages/scenario/Scenario.tsx
// Path: frontend/src/pages/scenario/Scenario.tsx
import React, { useEffect, useMemo, useState } from "react";
import { Link, useLocation, useParams, useSearchParams } from "react-router-dom";
import { apiGet, ApiError } from "../../lib/api";
import BOQTable from "../scenario/components/BOQTable";
import TWCTab from "../scenario/tabs/TWCTab";
import CapexTable from "../scenario/components/CapexTable";
import ServicesTable from "../scenario/components/ServicesTable";
import FxTab from "../scenario/tabs/FXTab";
import TaxTab from "../scenario/tabs/TaxTab";
import EscalationTab from "../scenario/tabs/EscalationTab";
import IndexSeriesTab from "../scenario/tabs/IndexSeriesTab";
import RiseAndFallTab from "../scenario/tabs/RiseAndFallTab";
import RebatesTab from "../scenario/tabs/RebatesTab";
import SummaryTab from "../scenario/tabs/SummaryTab";
import RunEnginePage from "../../components/engine/RunEnginePage";

/* ---------------- Types ---------------- */
type ScenarioDetail = {
  id: number;
  business_case_id: number;
  name: string;
  months: number;
  start_date: string; // ISO
};

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

// Excel renk efsanesine paralel ana gruplar
type MainGroup =
  | "input"
  | "calculation"
  | "finance"
  | "output"
  | "info"
  | "templates";

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
    "px-4 py-2 rounded-md border text-sm font-medium transition-colors focus:outline-none focus:ring-2 focus:ring-offset-1",
    active
      ? "bg-indigo-600 text-white border-indigo-600 shadow focus:ring-indigo-300"
      : "bg-white text-gray-700 border-gray-300 hover:bg-gray-50 focus:ring-indigo-200",
    !active && disabled && "opacity-60 cursor-not-allowed hover:bg-white"
  );
}

/* ---------------- Component ---------------- */
export default function ScenarioPage() {
  const params = useParams<{ scenarioId?: string; id?: string }>();
  const location = useLocation();
  const [sp, setSp] = useSearchParams();

  // Scenario id çöz
  const id = useMemo<number | null>(() => {
    const raw =
      params.scenarioId ??
      params.id ??
      (location.pathname.match(/\/scenarios\/(\d+)/i)?.[1] ?? null);
    if (!raw) return null;
    const n = Number(raw);
    return Number.isFinite(n) && n > 0 ? n : null;
  }, [params, location.pathname]);

  // Input içi sekme
  const tab: Tab = useMemo(() => {
    const t = (sp.get("tab") || "boq").toLowerCase();
    const allowed = new Set<Tab>([
      "pl",
      "summary",
      "boq",
      "twc",
      "index",
      "escalation",
      "rebates",
      "risefall",
      "capex",
      "fx",
      "tax",
      "services",
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

  // ANA GRUP (URL ?g=)
  const mainGroup: MainGroup = useMemo(() => {
    const g = (sp.get("g") || "input").toLowerCase();
    const allowed: MainGroup[] = [
      "input",
      "calculation",
      "finance",
      "output",
      "info",
      "templates",
    ];
    return (allowed as string[]).includes(g) ? (g as MainGroup) : "input";
  }, [sp]);
  function setGroup(next: MainGroup) {
    setSp(
      (prev) => {
        const ns = new URLSearchParams(prev);
        ns.set("g", next);
        return ns;
      },
      { replace: true }
    );
  }

  const [data, setData] = useState<ScenarioDetail | null>(null);
  const [flow, setFlow] = useState<Workflow | null>(null);
  const [loading, setLoading] = useState(true);
  const [err, setErr] = useState<string | null>(null);
  const [authError, setAuthError] = useState<string | null>(null);

  useEffect(() => {
    const onUnauthorized = (e: Event) => {
      setAuthError("Session expired or invalid token. Please sign in again.");
      console.warn("auth:unauthorized", (e as CustomEvent).detail || {});
    };
    window.addEventListener("auth:unauthorized", onUnauthorized as EventListener);
    return () =>
      window.removeEventListener(
        "auth:unauthorized",
        onUnauthorized as EventListener
      );
  }, []);

  async function loadAll() {
    if (!id) {
      setErr("Invalid scenario id.");
      setLoading(false);
      return;
    }
    setLoading(true);
    setErr(null);
    setAuthError(null);
    try {
      await apiGet("/me").catch((e) => {
        const msg =
          (e instanceof ApiError && e.message) ||
          e?.payload?.detail ||
          "Unauthorized. Please login.";
        // ApiError ctor imzasına bağlı kalmamak için düz Error fırlat
        throw new Error(String(msg));
      });
      const sc = await apiGet<ScenarioDetail>(`/business-cases/scenarios/${id}`);
      setData(sc);
      try {
        const wf = await apiGet<Workflow>(`/scenarios/${id}/workflow`);
        setFlow(wf);
      } catch {
        setFlow(null);
      }
    } catch (e: any) {
      const msg =
        (e instanceof ApiError && e.message) ||
        e?.response?.data?.detail ||
        e?.message ||
        "Failed to load scenario.";
      setErr(String(msg));
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

  const boqReady = !!flow?.boq_ready,
    twcReady = !!flow?.twc_ready,
    capexReady = !!flow?.capex_ready;
  const fxReady = !!flow?.fx_ready,
    taxReady = !!flow?.tax_ready,
    servicesReady = !!flow?.services_ready;
  const canGoTWC = boqReady,
    canGoCAPEX = twcReady,
    canGoFX = capexReady,
    canGoTAX = fxReady,
    canGoSERVICES = taxReady,
    canGoSUMMARY = servicesReady;
  const gatingActive = !!flow;

  type TabButtonItem = {
    key: Tab;
    label: string;
    title: string;
    disabled?: boolean;
    isSummary?: boolean;
  };
  const tabItems = useMemo<TabButtonItem[]>(
    () => [
      { key: "boq", label: "1. Products", title: "Products (Input)" },
      {
        key: "services",
        label: "2. Services",
        title: "Services Pricing",
        disabled: gatingActive && !canGoSERVICES,
      },
      {
        key: "twc",
        label: "3. TWC",
        title: "Transfer Window Calculation",
        disabled: gatingActive && !canGoTWC,
      },
      {
        key: "index",
        label: "4. Index",
        title: "Index Series (Manage time series data)",
      },
      {
        key: "escalation",
        label: "5. Escalation",
        title: "Escalation (Policies & resolve)",
      },
      { key: "rebates", label: "6. Rebates", title: "Scenario Rebates" },
      {
        key: "risefall",
        label: "7. Rise & Fall",
        title: "Rise & Fall (Formulation)",
      },
      {
        key: "capex",
        label: "8. CAPEX",
        title: "CAPEX inputs",
        disabled: gatingActive && !canGoCAPEX,
      },
      {
        key: "fx",
        label: "9. FX",
        title: "Foreign exchange settings",
        disabled: gatingActive && !canGoFX,
      },
      {
        key: "tax",
        label: "10. TAX",
        title: "Tax configuration",
        disabled: gatingActive && !canGoTAX,
      },
      {
        key: "summary",
        label: "11. Summary",
        title: "Scenario summary",
        disabled: gatingActive && !canGoSUMMARY,
        isSummary: true,
      },
    ],
    [
      canGoCAPEX,
      canGoFX,
      canGoSERVICES,
      canGoSUMMARY,
      canGoTAX,
      canGoTWC,
      gatingActive,
    ]
  );

  function setTabSafe(next: Tab) {
    if (
      next === "index" ||
      next === "escalation" ||
      next === "rebates" ||
      next === "risefall"
    ) {
      setTabRaw(next);
      return;
    }
    if (!flow) {
      setTabRaw(next === "pl" ? "summary" : next);
      return;
    }
    if (next === "twc" && !boqReady) {
      alert("First mark 'Ready' in 1. Products.");
      return;
    }
    if (next === "capex" && !twcReady) {
      alert("First mark 'Ready' in 3. TWC.");
      return;
    }
    if (next === "fx" && !capexReady) {
      alert("First mark 'Ready' in 8. CAPEX.");
      return;
    }
    if (next === "tax" && !fxReady) {
      alert("First mark 'Ready' in 9. FX.");
      return;
    }
    if (next === "services" && !taxReady) {
      alert("First mark 'Ready' in 10. TAX.");
      return;
    }
    if ((next === "pl" || next === "summary") && !servicesReady) {
      alert("First mark 'Ready' in 2. Services.");
      return;
    }
    setTabRaw(next === "pl" ? "summary" : next);
  }

  const stateBadge = useMemo(() => {
    if (!flow) return { text: "DRAFT", cls: "bg-gray-100 text-gray-700" };
    if (flow.summary_ready)
      return { text: "READY", cls: "bg-emerald-100 text-emerald-700" };
    const map: Record<Workflow["current_stage"], { text: string; cls: string }> =
      {
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
    return (
      map[flow.current_stage] ?? {
        text: "DRAFT",
        cls: "bg-gray-100 text-gray-700",
      }
    );
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
              ID: {data.id} • Name:{" "}
              <span className="font-medium">{data.name}</span> • Months:{" "}
              {data.months} • Start: {fmtDateISO(data.start_date)} • BC{" "}
              <Link to={bcLink} className="text-indigo-600 underline">
                #{data.business_case_id}
              </Link>
            </div>
          )}
          {flow && (
            <span className={cls("px-2 py-1 rounded font-medium", stateBadge.cls)}>
              State: {stateBadge.text}
              {flow.next_stage
                ? ` → Next: ${flow.next_stage.toUpperCase().replace("_", " & ")}`
                : ""}
            </span>
          )}
          <button
            onClick={loadAll}
            className="ml-3 px-3 py-1 rounded bg-gray-100 hover:bg-gray-200"
          >
            Refresh
          </button>
        </div>
      </div>

      {/* Main Group Selector (renkli chip’ler) */}
      <div className="flex flex-wrap gap-2">
        {(
          [
            ["input", "Input"],
            ["calculation", "Calculation (Engine)"],
            ["finance", "Finance annual"],
            ["output", "Output"],
            ["info", "Information"],
            ["templates", "Templates"],
          ] as [MainGroup, string][]
        ).map(([key, label]) => {
          const active = mainGroup === key;
          const base = "px-3 py-1 text-sm rounded border";
          let color = "bg-white text-slate-700 border-slate-300";
          if (key === "info")
            color = active
              ? "bg-blue-900 text-white border-blue-900"
              : "bg-white text-blue-900 border-blue-300";
          else if (key === "input")
            color = active
              ? "bg-green-100 text-green-900 border-green-300"
              : "bg-white text-green-700 border-green-300";
          else if (key === "output")
            color = active
              ? "bg-slate-100 text-slate-900 border-slate-300"
              : "bg-white text-slate-700 border-slate-300";
          else if (key === "finance")
            color = active
              ? "bg-gray-700 text-white border-gray-700"
              : "bg-white text-gray-700 border-gray-300";
          else if (key === "calculation")
            color = active
              ? "bg-black text-white border-black"
              : "bg-white text-black border-black";
          else if (key === "templates")
            color = active
              ? "bg-red-600 text-white border-red-600"
              : "bg-white text-red-600 border-red-300";
          return (
            <button
              key={key}
              className={`${base} ${color}${active ? " shadow-sm" : ""}`}
              onClick={() => setGroup(key as MainGroup)}
            >
              {label}
            </button>
          );
        })}
      </div>

      {/* Engine panel: SADECE Calculation grubunda */}
      {mainGroup === "calculation" && id ? (
        <div className="rounded border p-4 bg-white">
          <RunEnginePage key={id} scenarioId={id!} />
        </div>
      ) : null}

      {/* Global auth error */}
      {authError && (
        <div className="text-sm text-red-600 bg-red-50 border border-red-200 p-2 rounded">
          {authError}
        </div>
      )}

      {/* Tabs (sadece Input grubunda) */}
      {mainGroup === "input" && (
        <>
          <div className="flex gap-2 flex-wrap">
            {tabItems.map((item) => {
              const isActive = item.isSummary
                ? tab === "summary" || tab === "pl"
                : tab === item.key;
              return (
                <button
                  key={item.key}
                  onClick={() => setTabSafe(item.key)}
                  className={tabBtnClass(isActive, item.disabled)}
                  title={item.title}
                >
                  {item.label}
                </button>
              );
            })}
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
                      setTabSafe("services");
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
                      setTabSafe("index");
                    }}
                  />
                </div>
              )}

              {tab === "index" && (
                <div className="rounded border p-4 bg-white space-y-3">
                  <div className="flex items-center justify-between">
                    <div className="text-sm text-gray-700 font-medium">
                      Index Series
                    </div>
                    <button
                      className="px-3 py-1 rounded bg-indigo-600 text-white hover:bg-indigo-700"
                      title="Mark Ready and go to 5. Escalation"
                      onClick={() => setTabSafe("escalation")}
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
                    onMarkedReady={() => setTabSafe("rebates")}
                  />
                </div>
              )}

              {tab === "rebates" && (
                <div className="rounded border p-4 bg-white">
                  <RebatesTab
                    scenarioId={id}
                    onMarkedReady={() => setTabSafe("risefall")}
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
                      setTabSafe("fx");
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
                      setTabSafe("tax");
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
                      setTabSafe("services");
                    }}
                  />
                </div>
              )}

              {tab === "services" && (
                <div className="rounded border p-4 bg-white">
                  <ServicesTable
                    scenarioId={id}
                    onMarkedReady={async () => {
                      await loadAll();
                      setTabRaw("twc");
                    }}
                  />
                </div>
              )}

              {(tab === "summary" || tab === "pl") && (
                <div className="rounded border p-4 bg-white">
                  <SummaryTab
                    scenarioId={id}
                    startDate={data.start_date}
                    months={data.months}
                  />
                </div>
              )}
            </div>
          )}
        </>
      )}

      {/* Diğer ana gruplar (placeholder) */}
      {mainGroup === "finance" && (
        <div className="rounded border p-4 bg-white text-sm text-slate-600">
          Finance annual (AN/EM/Services pivot) – sonraki adımda eklenecek.
        </div>
      )}
      {mainGroup === "output" && (
        <div className="rounded border p-4 bg-white text-sm text-slate-600">
          Output reports – sonraki adımda eklenecek.
        </div>
      )}
      {mainGroup === "info" && (
        <div className="rounded border p-4 bg-white text-sm text-slate-600">
          Information / notes – opsiyonel.
        </div>
      )}
      {mainGroup === "templates" && (
        <div className="rounded border p-4 bg-white text-sm text-slate-600">
          Templates – opsiyonel.
        </div>
      )}
    </div>
  );
}
