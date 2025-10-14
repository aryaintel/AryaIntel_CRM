// Pathway: C:/Dev/AryaIntel_CRM/frontend/src/pages/engine/RunEnginePage.tsx
import React, { useMemo, useState } from "react";
import {
  runEngine,
  DEFAULT_OPTIONS,
  type EngineCategory,
  type EngineCategoryCode,
  type RunEngineRequest,
  type RunEngineResult,
  checkBoqCoverage,
  format1,
} from "../../api/engine";

type CatState = Record<EngineCategoryCode, boolean>;

const CATS: EngineCategoryCode[] = ["AN", "EM", "IE", "Services"];

function buildRequest(selected: CatState, opts: typeof DEFAULT_OPTIONS, persist: boolean): RunEngineRequest {
  const categories: EngineCategory[] = CATS.map((c) => ({
    code: c,
    enabled: !!selected[c],
  }));
  return { categories, options: opts, persist };
}

const Label = ({ htmlFor, children }: { htmlFor?: string; children?: React.ReactNode }) => (
  <label htmlFor={htmlFor} className="text-sm font-medium text-gray-700">{children}</label>
);

const Box = ({ title, children }: { title: string; children?: React.ReactNode }) => (
  <div className="rounded-xl border border-gray-200 bg-white shadow-sm">
    <div className="px-4 py-3 border-b text-sm font-semibold">{title}</div>
    <div className="p-4">{children}</div>
  </div>
);

/** Local checkbox toggle (avoid any design-system Toggle prop conflicts) */
function EngineOptionToggle(props: {
  id?: string;
  checked: boolean;
  disabled?: boolean;
  onChange: (v: boolean) => void;
  children?: React.ReactNode;
}) {
  const { id, checked, disabled, onChange, children } = props;
  return (
    <div className="flex items-center gap-2">
      <input
        id={id}
        type="checkbox"
        className="h-4 w-4"
        checked={checked}
        disabled={disabled}
        onChange={(e) => onChange(e.target.checked)}
      />
      <Label htmlFor={id}>{children}</Label>
    </div>
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
                <td key={i} className="px-2 py-1 border-b border-r text-right">{format1(v)}</td>
              ))}
            </tr>
          </tbody>
        </table>
      </div>
    </div>
  );
}

function Notes({ items }: { items: string[] }) {
  if (!items || items.length === 0) return null;
  return (
    <ul className="list-disc pl-6 text-xs text-gray-600">
      {items.map((x, i) => <li key={i}>{x}</li>)}
    </ul>
  );
}

function SectionDivider({ title }: { title: string }) {
  return <div className="text-xs uppercase tracking-wider text-gray-500 font-semibold mt-6 mb-2">{title}</div>;
}

export default function RunEnginePage() {
  const [scenarioId, setScenarioId] = useState<number>(1);
  const [cats, setCats] = useState<CatState>({ AN: true, EM: false, IE: false, Services: true });
  const [opts, setOpts] = useState(DEFAULT_OPTIONS);
  const [persist, setPersist] = useState<boolean>(false);
  const [busy, setBusy] = useState<boolean>(false);
  const [error, setError] = useState<string | null>(null);
  const [result, setResult] = useState<RunEngineResult | null>(null);
  const [coverage, setCoverage] = useState<{ AN: string[]; EM: string[]; IE: string[]; }>({ AN: [], EM: [], IE: [] });

  const selectedList = useMemo(() => CATS.filter((c) => cats[c]), [cats]);

  const run = async (doPersist: boolean) => {
    setBusy(true); setError(null);
    try {
      const body = buildRequest(cats, opts, doPersist);
      const data = await runEngine(scenarioId, body);
      // R&F locked ise UI kilitle
      setOpts((o) => ({ ...o, rise_and_fall: data.locks.rise_and_fall ? true : o.rise_and_fall }));
      setResult(data);
    } catch (e: any) {
      setError(e?.message || "Run failed");
    } finally {
      setBusy(false);
    }
  };

  const checkCoverage = async () => {
    const sections: ("AN" | "EM" | "IE")[] = ["AN", "EM", "IE"].filter((c) => cats[c as keyof CatState]) as any;
    const notes: { AN: string[]; EM: string[]; IE: string[] } = { AN: [], EM: [], IE: [] };
    for (const s of sections) {
      try {
        const res = await checkBoqCoverage(scenarioId, s);
        (notes as any)[s] = res.notes || [];
      } catch {
        (notes as any)[s] = ["error"];
      }
    }
    setCoverage(notes);
  };

  return (
    <div className="p-4 space-y-4">
      <h1 className="text-xl font-semibold">Run Engine</h1>

      <Box title="Scenario & Categories">
        <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
          <div>
            <Label htmlFor="scenarioId">Scenario ID</Label>
            <input
              id="scenarioId"
              type="number"
              className="mt-1 w-full rounded-md border px-3 py-2"
              value={scenarioId}
              min={1}
              onChange={(e) => setScenarioId(parseInt(e.target.value || "1", 10))}
            />
          </div>

          <div className="col-span-2 grid grid-cols-2 gap-2">
            {CATS.map((c) => (
              <EngineOptionToggle key={c} checked={cats[c]} onChange={(v) => setCats((s) => ({ ...s, [c]: v }))}>
                {c}
              </EngineOptionToggle>
            ))}
          </div>
        </div>
      </Box>

      <Box title="Options">
        <div className="grid grid-cols-2 md:grid-cols-5 gap-3">
          <EngineOptionToggle
            checked={opts.rise_and_fall === true}
            disabled={result?.locks?.rise_and_fall === true}
            onChange={(v) => setOpts((s) => ({ ...s, rise_and_fall: v }))}
          >
            Rise &amp; Fall {result?.locks?.rise_and_fall ? "(locked)" : ""}
          </EngineOptionToggle>
          <EngineOptionToggle checked={opts.fx_apply} onChange={(v) => setOpts((s) => ({ ...s, fx_apply: v }))}>
            FX Apply
          </EngineOptionToggle>
          <EngineOptionToggle checked={opts.tax_apply} onChange={(v) => setOpts((s) => ({ ...s, tax_apply: v }))}>
            Tax Apply
          </EngineOptionToggle>
          <EngineOptionToggle checked={opts.rebates_apply} onChange={(v) => setOpts((s) => ({ ...s, rebates_apply: v }))}>
            Rebates Apply
          </EngineOptionToggle>
          <EngineOptionToggle checked={opts.twc_apply} onChange={(v) => setOpts((s) => ({ ...s, twc_apply: v }))}>
            TWC Apply
          </EngineOptionToggle>
        </div>

        <SectionDivider title="Actions" />
        <div className="flex flex-wrap items-center gap-3">
          <button
            className="rounded-md bg-blue-600 text-white px-4 py-2 disabled:opacity-50"
            onClick={() => run(false)}
            disabled={busy}
          >
            {busy ? "Running..." : "Preview"}
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
          <div className="ml-auto flex items-center gap-2">
            <EngineOptionToggle checked={persist} onChange={setPersist}>
              Persist flag (request) — Not used; use buttons above
            </EngineOptionToggle>
          </div>
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
          <SectionDivider title="Coverage notes" />
          <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
            {(["AN","EM","IE"] as ("AN"|"EM"|"IE")[]).map((s) => (
              <div key={s}>
                <div className="text-xs font-semibold mb-1">{s}</div>
                <Notes items={coverage[s]} />
              </div>
            ))}
          </div>
        </Box>
      )}

      {result && (
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
    </div>
  );
}
