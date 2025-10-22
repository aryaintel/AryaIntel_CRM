// relative path: frontend/src/components/engine/RunEnginePage.tsx
// Path: frontend/src/components/engine/RunEnginePage.tsx
import React, { useEffect, useMemo, useState, type ReactNode } from "react";
import { runEngine, getEngineFacts, type RunEngineResponse } from "../../api/engine";
import { apiGet } from "../../lib/api";

/**
 * Run Engine — All-in-One
 * • Üst   : Kategori & Opsiyonlar + Run / Persist / Coverage
 * • Orta  : P&L Pivot (Monthly / Quarterly / Annual)
 * • Alt   : Persisted Facts (oA.Finance-*)
 * • Debug : Engine Debug panel (run_id ve okuma stratejisi)
 *
 * Görünür debug:
 *  - BE response run_id
 *  - lastPersistedRunId (FE’nin persisted okumaları sabitlediği id)
 *  - facts okurken kullanılan strateji: run_id | latest | preview
 *  - her sheet için dönen satır sayısı
 */

const CATS = ["AN", "EM", "IE", "Services"] as const;
type EngineCategoryCode = typeof CATS[number];
type EngineCategory = { code: EngineCategoryCode; enabled: boolean };

type EngineRunRequest = {
  categories: EngineCategory[];
  options: any;
  persist: boolean;
  include_facts?: boolean;
};
type EngineRunResult = RunEngineResponse;

type Props = {
  scenarioId?: number;
  defaultCategories?: Partial<Record<EngineCategoryCode, boolean>>;
  className?: string;
};

type CatState = Record<EngineCategoryCode, boolean>;
type Mode = "month" | "quarter" | "year";
type SeriesKey = "revenue" | "cogs" | "gp";
type CategoryKey = "AN" | "Services";

type FactRow = {
  yyyymm: string;
  series: SeriesKey;
  value: number;
  sheet_code: string;
  category_code?: string | null;
};

const SHEET_BY_MODE: Record<Mode, { AN: string; Services: string }> = {
  month:   { AN: "c.Sales-AN",       Services: "c.Sales-Services" },
  quarter: { AN: "oQ.Finance-AN",    Services: "oQ.Finance-Services" },
  year:    { AN: "oA.Finance-AN",    Services: "oA.Finance-Services" },
};

const DEFAULT_OPTIONS = {
  rise_and_fall: false,
  fx_apply: false,
  tax_apply: false,
  rebates_apply: false,
  twc_apply: false,
};

function buildRequest(selected: CatState, opts: any, persist: boolean): EngineRunRequest {
  const categories: EngineCategory[] = (CATS as readonly EngineCategoryCode[]).map((c) => ({
    code: c,
    enabled: !!selected[c],
  }));
  return { categories, options: opts, persist, include_facts: true };
}

const Box = ({ title, children }: { title: string; children?: ReactNode }) => (
  <div className="rounded-xl border border-gray-200 bg-white shadow-sm">
    <div className="px-4 py-3 border-b text-sm font-semibold">{title}</div>
    <div className="p-4">{children}</div>
  </div>
);

const Label = ({ htmlFor, children }: { htmlFor?: string; children?: ReactNode }) => (
  <label htmlFor={htmlFor} className="text-sm font-medium text-gray-700">
    {children}
  </label>
);

function Toggle({
  checked,
  disabled,
  onChange,
  children,
}: {
  checked: boolean;
  disabled?: boolean;
  onChange: (v: boolean) => void;
  children: ReactNode;
}) {
  return (
    <label className="flex items-center gap-2 cursor-pointer">
      <input
        type="checkbox"
        className="h-4 w-4"
        checked={checked}
        disabled={disabled}
        onChange={(e) => onChange(e.target.checked)}
      />
      <span className="text-sm">{children}</span>
    </label>
  );
}

function fmtHeader(mode: Mode, yyyymm: string) {
  if (mode === "month") return yyyymm;
  const [y, m] = yyyymm.split("-").map((x) => parseInt(x, 10));
  if (mode === "quarter") return `${y}-Q${Math.ceil(m / 3)}`;
  return String(y);
}
function fmt(n?: number) {
  if (n === undefined || n === null) return "—";
  try { return new Intl.NumberFormat(undefined, { maximumFractionDigits: 1 }).format(n); }
  catch { return String(n); }
}

function normalizeSeries(s: string): SeriesKey | null {
  const x = (s || "").toLowerCase();
  if (x === "revenue" || x === "sales" || x === "sales_revenue" || x === "revenue_total" || x === "sales_total") return "revenue";
  if (x === "cogs" || x === "cogs_ex_tax" || x === "cost" || x === "costs" || x === "cogs_total") return "cogs";
  if (x === "gp" || x === "gross_profit" || x === "gp_ex_tax" || x === "profit" || x === "gross") return "gp";
  return null;
}
function normalizeRows(rows: any[]): FactRow[] {
  const out: FactRow[] = [];
  for (const r of rows) {
    const ymRaw = String(r.yyyymm ?? r.month_key ?? r.period ?? "");
    const ymDigits = ymRaw.replace(/[^0-9]/g, "");
    const ym = ymDigits.length >= 6 ? `${ymDigits.slice(0,4)}-${ymDigits.slice(4,6)}` : (ymRaw || "");
    const key = normalizeSeries(String(r.series ?? r.metric ?? ""));
    if (!key) continue;
    out.push({
      yyyymm: ym,
      series: key,
      value: Number(r.value ?? r.amount ?? 0),
      sheet_code: String(r.sheet_code ?? r.sheet ?? ""),
      category_code: r.category_code ?? r.category ?? null,
    });
  }
  return out;
}
function pickRowsBySheet(all: FactRow[], desired: string): FactRow[] {
  let out = all.filter(r => r.sheet_code === desired || r.sheet_code?.startsWith(desired + "."));
  if (out.length) return out;
  const tail = desired.split("-").slice(1).join("-");
  const families = ["c.Sales", "oQ.Finance", "oA.Finance"];
  for (const f of families) {
    const cand = `${f}-${tail}`;
    out = all.filter(r => r.sheet_code === cand || r.sheet_code?.startsWith(cand + "."));
    if (out.length) return out;
  }
  return [];
}

type BoqCoverageResponse = { notes?: string[] };
async function checkBoqCoverage(scenarioId: number, category: "AN" | "EM" | "IE") {
  const url1 = `/api/scenarios/${scenarioId}/boq/coverage?category=${category}`;
  const url2 = `/api/boq/coverage?scenario_id=${scenarioId}&category=${category}`;
  try {
    return await apiGet<BoqCoverageResponse>(url1);
  } catch (e: any) {
    if (e?.status === 404) {
      try { return await apiGet<BoqCoverageResponse>(url2); }
      catch { return { notes: [] } as BoqCoverageResponse; }
    }
    throw e;
  }
}

export default function RunEnginePage({
  scenarioId: scenarioIdProp,
  defaultCategories,
  className,
}: Props) {
  const [scenarioIdLocal, setScenarioIdLocal] = useState<number>(scenarioIdProp ?? 1);
  const scenarioId = scenarioIdProp ?? scenarioIdLocal;

  const [cats, setCats] = useState<CatState>({
    AN: defaultCategories?.AN ?? true,
    EM: defaultCategories?.EM ?? false,
    IE: defaultCategories?.IE ?? false,
    Services: defaultCategories?.Services ?? true,
  });
  const [opts, setOpts] = useState<any>(DEFAULT_OPTIONS);

  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [result, setResult] = useState<EngineRunResult | null>(null);

  // Çalıştırma takibi
  const [runSeq, setRunSeq] = useState(0);
  const [lastAction, setLastAction] = useState<"preview" | "persist" | "init">("init");
  const [lastPersistedRunId, setLastPersistedRunId] = useState<number | null>(null);

  // Debug: facts okuma izleri (hangi sheet, hangi strateji, kaç satır)
  const [factsDebug, setFactsDebug] = useState<Record<string, { used: "run_id" | "latest" | "preview"; runId?: number; rows: number }>>({});

  const [mode, setMode] = useState<Mode>("month");
  const [seriesSel, setSeriesSel] = useState<SeriesKey[]>(["revenue", "cogs", "gp"]);
  const [catsSel, setCatsSel] = useState<CategoryKey[]>(["AN", "Services"]);

  const [coverage, setCoverage] = useState<{ AN: string[]; EM: string[]; IE: string[] }>({ AN: [], EM: [], IE: [] });

  // ---- RUN & COVERAGE -------------------------------------------------------
  const run = async (persist: boolean) => {
    setBusy(true);
    setError(null);
    try {
      const body = buildRequest(cats, opts, persist);
      const data: RunEngineResponse = await runEngine(scenarioId, body as any);
      setOpts((o: any) => ({ ...o, rise_and_fall: (data as any)?.locks?.rise_and_fall ? true : o.rise_and_fall }));
      setResult(data as EngineRunResult);

      if (persist && data?.run_id != null) {
        setLastPersistedRunId(Number(data.run_id));
        setLastAction("persist");
      } else {
        setLastAction("preview");
      }
      setRunSeq((n) => n + 1);
    } catch (e: any) {
      setError(e?.message || "Run failed");
    } finally {
      setBusy(false);
    }
  };

  const doCheckCoverage = async () => {
    const sections = (["AN", "EM", "IE"] as const).filter((c) => cats[c]);
    const notes: { AN: string[]; EM: string[]; IE: string[] } = { AN: [], EM: [], IE: [] };
    for (const s of sections) {
      try {
        const res = await checkBoqCoverage(scenarioId, s);
        (notes as any)[s] = res?.notes || [];
      } catch {
        (notes as any)[s] = ["error"];
      }
    }
    setCoverage(notes);
  };

  // ---- FACTS HELPERS --------------------------------------------------------
  function rowsPayloadToArray(payload: any): any[] {
    if (!payload) return [];
    if (Array.isArray(payload?.rows)) return payload.rows;
    if (Array.isArray(payload)) return payload;
    return [];
  }

  async function fetchFacts(optsIn: {
    scenarioId: number;
    sheet: string;
    series: ("revenue" | "cogs" | "gp")[];
    category: "AN" | "Services";
    persistedOnly?: boolean;
  }) {
    const isPersistedFamily = /^o[QA]\.Finance/.test(optsIn.sheet);
    let rowsRaw: any[] = [];
    let used: "run_id" | "latest" | "preview" = "preview";
    let usedRunId: number | undefined;

    if (isPersistedFamily) {
      const useRunId = lastAction === "persist" && lastPersistedRunId ? lastPersistedRunId : undefined;
      usedRunId = useRunId;
      const res1 = await getEngineFacts({
        scenarioId: optsIn.scenarioId,
        sheet: optsIn.sheet,
        series: optsIn.series,
        runId: useRunId,
        latest: useRunId ? undefined : true,
      }).catch((e) => (e?.status === 404 ? [] : Promise.reject(e)));
      rowsRaw = rowsPayloadToArray(res1);
      used = useRunId ? "run_id" : "latest";

      if (!optsIn.persistedOnly && rowsRaw.length === 0) {
        const res2 = await getEngineFacts({
          scenarioId: optsIn.scenarioId,
          sheet: optsIn.sheet,
          series: optsIn.series,
        }).catch((e) => (e?.status === 404 ? [] : Promise.reject(e)));
        rowsRaw = rowsPayloadToArray(res2);
        used = "preview";
      }
    } else {
      const res = await getEngineFacts({
        scenarioId: optsIn.scenarioId,
        sheet: optsIn.sheet,
        series: optsIn.series,
      }).catch((e) => (e?.status === 404 ? [] : Promise.reject(e)));
      rowsRaw = rowsPayloadToArray(res);
      used = "preview";
    }

    const all = normalizeRows(rowsRaw);
    const finalRows = pickRowsBySheet(all, optsIn.sheet);

    // debug kaydı
    setFactsDebug((prev) => ({
      ...prev,
      [optsIn.sheet]: { used, runId: usedRunId, rows: finalRows.length },
    }));

    return finalRows;
  }

  // ---- Pivot state ----------------------------------------------------------
  const [rowsAN, setRowsAN] = useState<FactRow[]>([]);
  const [rowsSVC, setRowsSVC] = useState<FactRow[]>([]);
  const [loadingPivot, setLoadingPivot] = useState(false);

  useEffect(() => {
    let mounted = true;
    (async () => {
      setLoadingPivot(true);
      try {
        const sheetAN = SHEET_BY_MODE[mode].AN;
        const sheetSV = SHEET_BY_MODE[mode].Services;
        const [a, s] = await Promise.all([
          fetchFacts({ scenarioId, sheet: sheetAN, series: seriesSel, category: "AN" }),
          fetchFacts({ scenarioId, sheet: sheetSV, series: seriesSel, category: "Services" }),
        ]);
        if (mounted) {
          setRowsAN(a);
          setRowsSVC(s);
        }
      } catch {
        if (mounted) { setRowsAN([]); setRowsSVC([]); }
      } finally {
        if (mounted) setLoadingPivot(false);
      }
    })();
    return () => { mounted = false; };
  }, [scenarioId, mode, seriesSel, runSeq]);

  // ---- Persisted panel ------------------------------------------------------
  const [persisted, setPersisted] = useState<Record<string, FactRow[]>>({});
  const [loadingPersisted, setLoadingPersisted] = useState(false);
  useEffect(() => {
    let mounted = true;
    (async () => {
      setLoadingPersisted(true);
      const out: Record<string, FactRow[]> = {};
      try {
        for (const entry of [
          { sheet: "oA.Finance-AN", category: "AN" as const },
          { sheet: "oA.Finance-Services", category: "Services" as const },
        ]) {
          const useRunId = lastPersistedRunId ?? undefined;
          const res = await getEngineFacts({
            scenarioId,
            sheet: entry.sheet,
            series: ["revenue", "cogs", "gp"],
            runId: useRunId,
            latest: useRunId ? undefined : true,
          }).catch((e) => (e?.status === 404 ? [] : Promise.reject(e)));
          const rows = pickRowsBySheet(normalizeRows(rowsPayloadToArray(res)), entry.sheet);
          out[entry.sheet] = rows;

          // debug kaydı (persisted panel için de)
          setFactsDebug((prev) => ({
            ...prev,
            [entry.sheet]: { used: useRunId ? "run_id" : "latest", runId: useRunId, rows: rows.length },
          }));
        }
      } catch {
        // ignore
      } finally {
        if (mounted) { setPersisted(out); setLoadingPersisted(false); }
      }
    })();
    return () => { mounted = false; };
  }, [scenarioId, lastPersistedRunId]);

  // ---- Render ---------------------------------------------------------------
  return (
    <div className={className ?? ""}>

      {/* ÜST KONTROLLER */}
      <div className="sticky top-0 z-10 bg-gray-50/80 backdrop-blur border-b">
        <Box title="Run Engine">
          <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
            {!scenarioIdProp && (
              <div>
                <Label htmlFor="scenarioId">Scenario ID</Label>
                <input
                  id="scenarioId"
                  type="number"
                  className="mt-1 w-full rounded-md border px-3 py-2"
                  value={scenarioIdLocal}
                  min={1}
                  onChange={(e) => setScenarioIdLocal(parseInt(e.target.value || "1", 10))}
                />
              </div>
            )}
            <div className={!scenarioIdProp ? "col-span-2 grid grid-cols-2 gap-2" : "grid grid-cols-2 gap-2"}>
              {CATS.map((c) => (
                <Toggle key={c} checked={cats[c]} onChange={(v) => setCats((s) => ({ ...s, [c]: v }))}>
                  {c}
                </Toggle>
              ))}
            </div>
          </div>

          <div className="mt-3 grid grid-cols-2 md:grid-cols-6 gap-3">
            <Toggle checked={!!opts.rise_and_fall} disabled={!!result?.locks?.rise_and_fall}
                    onChange={(v) => setOpts((s: any) => ({ ...s, rise_and_fall: v }))}>
              Rise &amp; Fall {result?.locks?.rise_and_fall ? "(locked)" : ""}
            </Toggle>
            <Toggle checked={!!opts.fx_apply}      onChange={(v) => setOpts((s: any) => ({ ...s, fx_apply: v }))}>FX Apply</Toggle>
            <Toggle checked={!!opts.tax_apply}     onChange={(v) => setOpts((s: any) => ({ ...s, tax_apply: v }))}>Tax Apply</Toggle>
            <Toggle checked={!!opts.rebates_apply} onChange={(v) => setOpts((s: any) => ({ ...s, rebates_apply: v }))}>Rebates Apply</Toggle>
            <Toggle checked={!!opts.twc_apply}     onChange={(v) => setOpts((s: any) => ({ ...s, twc_apply: v }))}>TWC Apply</Toggle>
          </div>

          <div className="flex flex-wrap items-center gap-3 mt-4">
            <button className="rounded-md bg-blue-600 text-white px-4 py-2 disabled:opacity-50"
                    onClick={() => run(false)} disabled={busy}>
              {busy ? "Running..." : "Preview"}
            </button>
            <button className="rounded-md bg-emerald-600 text-white px-4 py-2 disabled:opacity-50"
                    onClick={() => run(true)} disabled={busy}>
              {busy ? "Persisting..." : "Run & Persist"}
            </button>
            <button className="rounded-md bg-gray-100 text-gray-800 px-3 py-2 border"
                    onClick={doCheckCoverage} disabled={busy}>
              Check BOQ Coverage
            </button>

            {result && (
              <span className="ml-auto text-xs text-gray-600">
                Persisted: <b>{result.persisted ? "yes" : "no"}</b> • Rows: <b>{result.persisted_rows ?? 0}</b>
                {result.notes ? ` • ${result.notes}` : ""}
              </span>
            )}
          </div>

          {error && <div className="mt-2 text-sm text-red-600">{error}</div>}
        </Box>
      </div>

      {/* P&L PIVOT (AN & Services) */}
      <PlPivot
        mode={mode}
        setMode={setMode}
        seriesSel={seriesSel}
        setSeriesSel={setSeriesSel}
        catsSel={catsSel}
        setCatsSel={setCatsSel}
        rowsAN={rowsAN}
        rowsSVC={rowsSVC}
        loading={loadingPivot}
      />

      {/* Persisted */}
      <Box title="Finance Facts (persisted)">
        {loadingPersisted && <div className="text-xs text-gray-500">Loading…</div>}
        {!loadingPersisted && <PersistedTables persisted={persisted} />}
      </Box>

      {/* 🔎 ENGINE DEBUG */}
      <Box title="Engine Debug">
        <div className="text-xs grid gap-2">
          <div>Scenario: <b>{scenarioId}</b></div>
          <div>Last action: <b>{lastAction}</b></div>
          <div>BE response run_id (last run): <b>{result?.run_id ?? "—"}</b></div>
          <div>FE pinned persisted run_id: <b>{lastPersistedRunId ?? "—"}</b></div>
          <div className="mt-2">
            <div className="font-semibold">Facts reads (last):</div>
            <table className="mt-1 w-full text-xs border">
              <thead className="bg-gray-50">
                <tr>
                  <th className="text-left px-2 py-1 border-r">Sheet</th>
                  <th className="text-left px-2 py-1 border-r">Used</th>
                  <th className="text-left px-2 py-1 border-r">run_id</th>
                  <th className="text-right px-2 py-1">rows</th>
                </tr>
              </thead>
              <tbody>
                {Object.entries(factsDebug).map(([sheet, d]) => (
                  <tr key={sheet} className="odd:bg-white even:bg-gray-50">
                    <td className="px-2 py-1 border-r">{sheet}</td>
                    <td className="px-2 py-1 border-r">{d.used}</td>
                    <td className="px-2 py-1 border-r">{d.runId ?? "—"}</td>
                    <td className="px-2 py-1 text-right">{d.rows}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          <div className="mt-2">
            <button
              className="px-2 py-1 text-xs border rounded"
              onClick={() => setFactsDebug({})}
            >
              Clear debug
            </button>
          </div>
        </div>
      </Box>

      {(coverage.AN.length || coverage.EM.length || coverage.IE.length) && (
        <Box title="BOQ Coverage Notes">
          <pre className="text-xs overflow-auto bg-gray-50 p-3 border rounded">
            {JSON.stringify(coverage, null, 2)}
          </pre>
        </Box>
      )}
    </div>
  );
}

/* --------------------------- Alt bileşenler --------------------------- */

function PlPivot({
  mode, setMode,
  seriesSel, setSeriesSel,
  catsSel, setCatsSel,
  rowsAN, rowsSVC,
  loading,
}: {
  mode: Mode; setMode: (m: Mode) => void;
  seriesSel: SeriesKey[]; setSeriesSel: (s: SeriesKey[]) => void;
  catsSel: CategoryKey[]; setCatsSel: (c: CategoryKey[]) => void;
  rowsAN: FactRow[]; rowsSVC: FactRow[]; loading: boolean;
}) {
  const headersAN  = useMemo(() => Array.from(new Set(rowsAN.map(r=>r.yyyymm))).sort(), [rowsAN]);
  const headersSVC = useMemo(() => Array.from(new Set(rowsSVC.map(r=>r.yyyymm))).sort(), [rowsSVC]);
  const idx = (rows: FactRow[]) =>
    rows.reduce((a, r) => ((a[r.series] = a[r.series] || {}), (a[r.series]![r.yyyymm] = r.value), a),
      {} as Record<SeriesKey, Record<string, number>>);
  const idxAN  = useMemo(() => idx(rowsAN),  [rowsAN]);
  const idxSVC = useMemo(() => idx(rowsSVC), [rowsSVC]);

  return (
    <Box title="Finance – P&L View (Monthly / Quarterly / Annual)">
      <div className="flex flex-wrap items-center gap-3 mb-3">
        <div className="inline-flex rounded-md border border-gray-300 overflow-hidden">
          {(["month","quarter","year"] as Mode[]).map((m, i) => {
            const active = mode === m;
            return (
              <button key={m} onClick={() => setMode(m)}
                className={"px-3 py-1 text-sm " + (active ? "bg-gray-900 text-white" : "bg-white text-gray-700 hover:bg-gray-50")
                  + (i>0 ? " border-l border-gray-300" : "")}>
                {m==="month"?"Monthly":m==="quarter"?"Quarterly":"Annual"}
              </button>
            );
          })}
        </div>
        <div className="flex items-center gap-2">
          {(["revenue","cogs","gp"] as SeriesKey[]).map((s) => {
            const on = seriesSel.includes(s);
            return (
              <button key={s}
                onClick={() =>
                  setSeriesSel(on ? seriesSel.filter(x=>x!==s) : [...seriesSel, s])}
                className={"px-2 py-1 text-xs rounded border " + (on ? "bg-indigo-600 text-white border-indigo-600" :
                  "bg-white text-gray-700 border-gray-300 hover:bg-gray-50")}>
                {s.toUpperCase()}
              </button>
            );
          })}
        </div>
        <div className="flex items-center gap-2">
          {(["AN","Services"] as CategoryKey[]).map((c) => {
            const on = catsSel.includes(c);
            return (
              <button key={c}
                onClick={() => setCatsSel(on ? catsSel.filter(x=>x!==c) : [...catsSel, c])}
                className={"px-2 py-1 text-xs rounded border " + (on ? "bg-emerald-700 text-white border-emerald-700" :
                  "bg-white text-gray-700 border-gray-300 hover:bg-gray-50")}>
                {c}
              </button>
            );
          })}
        </div>
        {loading && <span className="text-xs text-gray-500">Loading…</span>}
      </div>

      {/* AN */}
      {catsSel.includes("AN") && (
        <div className="rounded border bg-white mb-6">
          <div className="px-3 py-2 border-b font-medium text-gray-800">
            AN (Finance) • {SHEET_BY_MODE[mode].AN}
          </div>
          <div className="overflow-x-auto">
            <table className="min-w-[1200px] w-full text-xs">
              <thead className="bg-gray-50">
                <tr>
                  <th className="text-left px-3 py-2 w-48">Series</th>
                  {headersAN.map((h) => (
                    <th key={h} className="text-right px-2 py-2 whitespace-nowrap">
                      {fmtHeader(mode, h)}
                    </th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {(["revenue","cogs","gp"] as SeriesKey[]).map((s)=>(
                  <tr key={s} className="odd:bg-white even:bg-gray-50">
                    <td className="px-3 py-1 font-semibold capitalize">{s}</td>
                    {headersAN.map((h)=>(
                      <td key={h} className="text-right px-2 py-1 tabular-nums">
                        {fmt(idxAN[s]?.[h])}
                      </td>
                    ))}
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      )}

      {/* Services */}
      {catsSel.includes("Services") && (
        <div className="rounded border bg-white">
          <div className="px-3 py-2 border-b font-medium text-gray-800">
            Services (Finance) • {SHEET_BY_MODE[mode].Services}
          </div>
          <div className="overflow-x-auto">
            <table className="min-w-[1200px] w-full text-xs">
              <thead className="bg-gray-50">
                <tr>
                  <th className="text-left px-3 py-2 w-48">Series</th>
                  {headersSVC.map((h) => (
                    <th key={h} className="text-right px-2 py-2 whitespace-nowrap">
                      {fmtHeader(mode, h)}
                    </th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {(["revenue","cogs","gp"] as SeriesKey[]).map((s)=>(
                  <tr key={s} className="odd:bg-white even:bg-gray-50">
                    <td className="px-3 py-1 font-semibold capitalize">{s}</td>
                    {headersSVC.map((h)=>(
                      <td key={h} className="text-right px-2 py-1 tabular-nums">
                        {fmt(idxSVC[s]?.[h])}
                      </td>
                    ))}
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      )}
    </Box>
  );
}

function PersistedTables({ persisted }: { persisted: Record<string, FactRow[]> }) {
  return (
    <div className="space-y-6">
      {Object.entries(persisted).map(([sheet, rows]) => {
        const headers = Array.from(new Set(rows.map((r) => r.yyyymm))).sort();
        const idx = rows.reduce((acc, r) => {
          (acc[r.series] = acc[r.series] || {})[r.yyyymm] = r.value;
          return acc;
        }, {} as Record<SeriesKey, Record<string, number>>);

        return (
          <div key={sheet}>
            <div className="font-semibold text-gray-800 mb-1">{sheet}</div>
            <div className="overflow-x-auto rounded border bg-white">
              <table className="min-w-[1200px] w-full text-xs">
                <thead className="bg-gray-50">
                  <tr>
                    <th className="text-left px-3 py-2 w-48">Series</th>
                    {headers.map((h) => (
                      <th key={h} className="text-right px-2 py-2">{h}</th>
                    ))}
                  </tr>
                </thead>
                <tbody>
                  {(["revenue","cogs","gp"] as SeriesKey[]).map((s)=>(
                    <tr key={s} className="odd:bg-white even:bg-gray-50">
                      <td className="px-3 py-1 font-semibold uppercase">{s}</td>
                      {headers.map((h)=>(
                        <td key={h} className="text-right px-2 py-1 tabular-nums">
                          {fmt(idx[s]?.[h])}
                        </td>
                      ))}
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </div>
        );
      })}
    </div>
  );
}
