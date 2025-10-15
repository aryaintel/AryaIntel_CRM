import React, { useMemo, useState, type ReactNode } from "react";
import {
  runEngine,
  DEFAULT_OPTIONS,
  checkBoqCoverage,
  format1,
} from "../../api/engine";
import EngineFactsGrid from "./EngineFactsGrid";
import { useEngineFacts } from "./useEngineFacts";

export const CATS = ["AN", "EM", "IE", "Services"] as const;
export type EngineCategoryCode = typeof CATS[number];

type EngineCategory = { code: EngineCategoryCode; enabled: boolean };
type EngineRunRequest = { categories: EngineCategory[]; options: any; persist: boolean; include_facts?: boolean };
type EngineRunResult = {
  scenario_id: number;
  run_id?: number | null;
  locks?: { rise_and_fall?: boolean };
  notes?: string | null;
  persisted?: boolean;
  persisted_rows?: number;
  generated: { name: string; months: string[]; values: number[] }[];
};

type Props = {
  scenarioId?: number;
  defaultCategories?: Partial<Record<EngineCategoryCode, boolean>>;
  className?: string;
};

type CatState = Record<EngineCategoryCode, boolean>;

function buildRequest(selected: CatState, opts: any, persist: boolean): EngineRunRequest {
  const categories: EngineCategory[] = (CATS as readonly EngineCategoryCode[]).map((c) => ({
    code: c,
    enabled: !!selected[c],
  }));
  return { categories, options: opts, persist, include_facts: true };
}

const Label = ({ htmlFor, children }: { htmlFor?: string; children?: ReactNode }) => (
  <label htmlFor={htmlFor} className="text-sm font-medium text-gray-700">{children}</label>
);

const Box = ({ title, children }: { title: string; children?: ReactNode }) => (
  <div className="rounded-xl border border-gray-200 bg-white shadow-sm">
    <div className="px-4 py-3 border-b text-sm font-semibold">{title}</div>
    <div className="p-4">{children}</div>
  </div>
);

function EngineOptionToggle(props: {
  id?: string;
  checked: boolean;
  disabled?: boolean;
  onChange: (v: boolean) => void;
  children?: ReactNode;
}) {
  const { id, checked, disabled, onChange, children } = props;
  return (
    <label className="flex items-center gap-2 cursor-pointer">
      <input
        id={id}
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

function MiniTable({ name, months, values }: { name: string; months: string[]; values: number[] }) {
  return (
    <div className="mb-6">
      <div className="font-semibold text-sm mb-2">{name}</div>
      <div className="overflow-auto">
        <table className="min-w-[720px] text-xs border border-gray-200">
          <thead className="bg-gray-50">
            <tr>
              {months.map((m, i) => (
                <th key={i} className="px-2 py-1 border-b border-r">{m}</th>
              ))}
            </tr>
          </thead>
          <tbody>
            <tr>
              {values.map((v, i) => (
                <td key={i} className="px-2 py-1 border-b border-r text-right">{format1 ? format1(v) : v.toFixed(1)}</td>
              ))}
            </tr>
          </tbody>
        </table>
      </div>
    </div>
  );
}

function SectionDivider({ title }: { title: string }) {
  return <div className="text-xs uppercase tracking-wider text-gray-500 font-semibold mt-6 mb-2">{title}</div>;
}

export default function RunEnginePage({ scenarioId: scenarioIdProp, defaultCategories, className }: Props) {
  const [scenarioIdLocal, setScenarioIdLocal] = useState<number>(scenarioIdProp ?? 1);
  const scenarioId = scenarioIdProp ?? scenarioIdLocal;

  const [cats, setCats] = useState<CatState>({
    AN: defaultCategories?.AN ?? true,
    EM: defaultCategories?.EM ?? false,
    IE: defaultCategories?.IE ?? false,
    Services: defaultCategories?.Services ?? true
  });
  const [opts, setOpts] = useState<any>(DEFAULT_OPTIONS);
  const [busy, setBusy] = useState<boolean>(false);
  const [error, setError] = useState<string | null>(null);
  const [result, setResult] = useState<EngineRunResult | null>(null);
  const [showResults, setShowResults] = useState<boolean>(true);
  const [showFacts, setShowFacts] = useState<boolean>(true);

  const AN_SHEETS = ["oA.Finance-AN.Revenue","oA.Finance-AN.COGS","oA.Finance-AN.GP"];
  const SV_SHEETS = ["oA.Finance-Services.Revenue","oA.Finance-Services.COGS","oA.Finance-Services.GP"];

  const [coverage, setCoverage] = useState<{ AN: string[]; EM: string[]; IE: string[] }>({
    AN: [], EM: [], IE: []
  });

  const selectedList = useMemo(
    () => (CATS as readonly EngineCategoryCode[]).filter((c) => cats[c]),
    [cats]
  );

  const run = async (doPersist: boolean) => {
    setBusy(true); setError(null);
    try {
      const body = buildRequest(cats, opts, doPersist);
      const data: any = await runEngine(scenarioId, body as any);
      setOpts((o: any) => ({ ...o, rise_and_fall: data?.locks?.rise_and_fall ? true : o.rise_and_fall }));
      setResult(data as EngineRunResult);
      setShowResults(true);
      setShowFacts(true);
    } catch (e: any) {
      setError(e?.message || "Run failed");
    } finally {
      setBusy(false);
    }
  };

  const checkCoverage = async () => {
    const sections = (["AN","EM","IE"] as const).filter((c) => cats[c]);
    const notes: { AN: string[]; EM: string[]; IE: string[] } = { AN: [], EM: [], IE: [] };
    for (const s of sections) {
      try {
        const res: any = await checkBoqCoverage(scenarioId, s);
        (notes as any)[s] = res?.notes || [];
      } catch {
        (notes as any)[s] = ["error"];
      }
    }
    setCoverage(notes);
  };

  return (
    <div className={className ?? ""}>
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
            {(CATS as readonly EngineCategoryCode[]).map((c) => (
              <EngineOptionToggle key={c} checked={cats[c]} onChange={(v) => setCats((s) => ({ ...s, [c]: v }))}>
                {c}
              </EngineOptionToggle>
            ))}
          </div>
        </div>

        <SectionDivider title="Options" />
        <div className="grid grid-cols-2 md:grid-cols-6 gap-3">
          <EngineOptionToggle
            checked={!!opts.rise_and_fall}
            disabled={!!result?.locks?.rise_and_fall}
            onChange={(v) => setOpts((s: any) => ({ ...s, rise_and_fall: v }))}
          >
            Rise &amp; Fall {result?.locks?.rise_and_fall ? "(locked)" : ""}
          </EngineOptionToggle>
          <EngineOptionToggle checked={!!opts.fx_apply} onChange={(v) => setOpts((s: any) => ({ ...s, fx_apply: v }))}>
            FX Apply
          </EngineOptionToggle>
          <EngineOptionToggle checked={!!opts.tax_apply} onChange={(v) => setOpts((s: any) => ({ ...s, tax_apply: v }))}>
            Tax Apply
          </EngineOptionToggle>
          <EngineOptionToggle checked={!!opts.rebates_apply} onChange={(v) => setOpts((s: any) => ({ ...s, rebates_apply: v }))}>
            Rebates Apply
          </EngineOptionToggle>
          <EngineOptionToggle checked={!!opts.twc_apply} onChange={(v) => setOpts((s: any) => ({ ...s, twc_apply: v }))}>
            TWC Apply
          </EngineOptionToggle>
          <EngineOptionToggle checked={showFacts} onChange={setShowFacts}>
            Show Finance Facts
          </EngineOptionToggle>
        </div>

        <div className="flex flex-wrap items-center gap-3 mt-4">
          <button
            className="rounded-md bg-blue-600 text-white px-4 py-2 disabled:opacity-50"
            onClick={() => run(false)}
            disabled={busy}
          >
            {busy ? "Running..." : "Preview"}
          </button>
          <button
            className="rounded-md bg-gray-100 text-gray-800 px-3 py-2 border"
            onClick={() => setShowResults((v) => !v)}
            title={showResults ? "Hide results" : "Show results"}
          >
            {showResults ? "Hide" : "Show"}
          </button>
          <button
            className="rounded-md bg-emerald-600 text-white px-4 py-2 disabled:opacity-50"
            onClick={() => run(true)}
            disabled={busy}
          >
            {busy ? "Persisting..." : "Run & Persist"}
          </button>
          <button
            className="rounded-md bg-gray-100 text-gray-800 px-3 py-2 border"
            onClick={checkCoverage}
            disabled={busy}
            title="Check BOQ coverage for selected AN/EM/IE"
          >
            Check BOQ Coverage
          </button>
        </div>

        {error && <div className="mt-3 text-sm text-red-600">{error}</div>}
      </Box>

      {!!selectedList.length && (
        <Box title="Selected Categories">
          <div className="flex flex-wrap gap-2 text-sm">
            {selectedList.map((c) => (
              <span key={c} className="px-2 py-1 rounded bg-gray-100 border">{c}</span>
            ))}
          </div>
        </Box>
      )}

      {showResults && result && (
        <Box title={`Result • Scenario ${result.scenario_id}${result.run_id ? ` • Run #${result.run_id}` : ""}`}>
          {result.notes && <div className="mb-2 text-xs text-amber-700">{result.notes}</div>}
          <div className="mb-4 text-xs text-gray-600">
            Persisted: <b>{result.persisted ? "yes" : "no"}</b> • Rows: <b>{result.persisted_rows}</b>
          </div>
          <div>
            {result.generated.map((s, i) => (
              <MiniTable key={i} name={s.name} months={s.months} values={s.values} />
            ))}
          </div>
          <details className="mt-2">
            <summary className="cursor-pointer text-sm">Raw JSON</summary>
            <pre className="text-xs overflow-auto bg-gray-50 p-3 border rounded">{JSON.stringify(result, null, 2)}</pre>
          </details>
        </Box>
      )}

      {showFacts && (
        <Box title="Finance Facts (persisted)">
          <EngineFactsGrid scenarioId={scenarioId} category="AN" sheets={AN_SHEETS} />
          <EngineFactsGrid scenarioId={scenarioId} category="Services" sheets={SV_SHEETS} className="mt-6" />
        </Box>
      )}
    </div>
  );
}
