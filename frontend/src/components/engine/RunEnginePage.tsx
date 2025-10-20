// frontend/src/components/engine/RunEnginePage.tsx
import React, { useEffect, useMemo, useState, type ReactNode } from "react";
import { runEngine, DEFAULT_OPTIONS, checkBoqCoverage } from "../../api/engine";

/**
 * Run Engine — All-in-One (Single File)
 * ----------------------------------------------------------------
 * • Üst   : Kategori & Opsiyonlar + Run / Persist / Coverage (sticky)
 * • Orta  : Excel paralelli P&L Pivot (Monthly / Quarterly / Annual)
 * • Alt   : Persisted Facts (oA.Finance-*) — series pivot
 *
 * NOT — Kritik düzeltmeler:
 * 1) series paramı: yalnızca TEK seri seçiliyken gönderilir. Çoklu seçimde server'a gönderilmez,
 *    ya da 'series_str' ile "," ayrılmış olarak gönderilir (backend destekli). (bkz. fetchFacts)
 * 2) facts yanıtı: { rows: [...] } yapısından okunur; dizi dönerse de desteklenir.
 * 3) sheet filtreleme: server'a sheet gönderME, client-side prefix eşleme + fallback uygula.
 *    Böylece DB'de oA.* dursa bile Monthly görünüm boş kalmaz.
 */

// ==== Türler & Yardımcılar ===================================================
const CATS = ["AN", "EM", "IE", "Services"] as const; // HMR: export yok
type EngineCategoryCode = typeof CATS[number];

type EngineCategory = { code: EngineCategoryCode; enabled: boolean };
type EngineRunRequest = {
  categories: EngineCategory[];
  options: any;
  persist: boolean;
  include_facts?: boolean;
};
type EngineRunResult = {
  scenario_id: number;
  run_id?: number | null;
  locks?: { rise_and_fall?: boolean };
  notes?: string | null;
  persisted?: boolean;
  persisted_rows?: number;
  generated?: { name: string; months: string[]; values: number[] }[];
};

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
  yyyymm: string;        // "YYYY-MM"
  series: SeriesKey;     // revenue | cogs | gp
  value: number;
  sheet_code: string;    // c.Sales-AN, oA.Finance-Services, ...
  category_code?: string | null;
};

// Excel-parite: İstenen sheet İSİMLERİ
const SHEET_BY_MODE: Record<Mode, { AN: string; Services: string }> = {
  month:   { AN: "c.Sales-AN",       Services: "c.Sales-Services" },
  quarter: { AN: "oQ.Finance-AN",    Services: "oQ.Finance-Services" },
  year:    { AN: "oA.Finance-AN",    Services: "oA.Finance-Services" },
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

// ---------- Yardımcılar ----------
function normalizeRows(rows: any[]): FactRow[] {
  return rows.map((r) => {
    const ym = String(r.yyyymm ?? "");
    const y = ym.slice(0, 4), m = ym.slice(4, 6);
    const sheet = String(r.sheet_code ?? "");
    const sRaw = String(r.series ?? "").toLowerCase();
    let sNorm: SeriesKey;
    if (sRaw === "revenue" || sRaw === "cogs" || sRaw === "gp") {
      sNorm = sRaw as SeriesKey;
    } else {
      const sc = sheet.toLowerCase();
      if (sc.includes(".cogs")) sNorm = "cogs";
      else if (sc.includes(".gp")) sNorm = "gp";
      else sNorm = "revenue";
    }
    const val = Number(r.value ?? 0);
    return {
      yyyymm: ym && ym.length === 6 ? `${y}-${m}` : (r.yyyymm ?? ""),
      series: sNorm,
      value: Number.isFinite(val) ? val : 0,
      sheet_code: sheet,
      category_code: r.category_code ?? null,
    };
  });
}
function pickRowsBySheet(all: FactRow[], desired: string): FactRow[] {
  // 1) Tam eşleşme veya prefix (desired.*)
  let out = all.filter(r => r.sheet_code === desired || r.sheet_code?.startsWith(desired + "."));
  if (out.length) return out;
  // 2) Akıllı fallback (aynı tail ile farklı family)
  const tail = desired.split("-").slice(1).join("-"); // AN | Services
  const families = ["c.Sales", "oQ.Finance", "oA.Finance"];
  for (const f of families) {
    const cand = `${f}-${tail}`;
    out = all.filter(r => r.sheet_code === cand || r.sheet_code?.startsWith(cand + "."));
    if (out.length) return out;
  }
  return [];
}

// ==== Sayfa ==================================================================
export default function RunEnginePage({
  scenarioId: scenarioIdProp,
  defaultCategories,
  className,
}: Props) {
  const [scenarioIdLocal, setScenarioIdLocal] = useState<number>(scenarioIdProp ?? 1);
  const scenarioId = scenarioIdProp ?? scenarioIdLocal;

  // Seçimler
  const [cats, setCats] = useState<CatState>({
    AN: defaultCategories?.AN ?? true,
    EM: defaultCategories?.EM ?? false,
    IE: defaultCategories?.IE ?? false,
    Services: defaultCategories?.Services ?? true,
  });
  const [opts, setOpts] = useState<any>(DEFAULT_OPTIONS);

  // Çalıştırma durumu
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [result, setResult] = useState<EngineRunResult | null>(null);

  // P&L görünümü
  const [mode, setMode] = useState<Mode>("month");
  const [seriesSel, setSeriesSel] = useState<SeriesKey[]>(["revenue", "cogs", "gp"]);
  const [catsSel, setCatsSel] = useState<CategoryKey[]>(["AN", "Services"]);

  // BOQ coverage kısa notlar
  const [coverage, setCoverage] = useState<{ AN: string[]; EM: string[]; IE: string[] }>({ AN: [], EM: [], IE: [] });

  // ---------- RUN & COVERAGE ----------
  const run = async (persist: boolean) => {
    setBusy(true);
    setError(null);
    try {
      const body = buildRequest(cats, opts, persist);
      const data = await runEngine(scenarioId, body as any);
      setOpts((o: any) => ({ ...o, rise_and_fall: (data as any)?.locks?.rise_and_fall ? true : o.rise_and_fall }));
      setResult(data as EngineRunResult);
    } catch (e: any) {
      setError(e?.message || "Run failed");
    } finally {
      setBusy(false);
    }
  };

  const checkCoverage = async () => {
    const sections = (["AN", "EM", "IE"] as const).filter((c) => cats[c]);
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

  // ---------- Pivot veri (API: /api/engine/facts + category) ----------
  async function fetchFacts(opts: {
    scenarioId: number;
    sheet: string;                 // istenen sheet prefix (örn. c.Sales-AN)
    series: ("revenue" | "cogs" | "gp")[];
    category: "AN" | "Services";
  }) {
    const qs = new URLSearchParams();
    qs.set("scenario_id", String(opts.scenarioId));
    qs.set("category_code", opts.category); qs.set("category", opts.category);
    qs.set("latest", "true");

    if (opts.series.length === 1) {
      qs.set("series", opts.series[0] as string);
    } else if (opts.series.length > 1) {
      // Backend 'series_str' virgüllü stringi destekliyor; 'series' paramını göndermiyoruz.
      qs.set("series_str", opts.series.join(","));
    }
    const res = await fetch(`/api/engine/facts?${qs.toString()}`);
    if (!res.ok) throw new Error(`HTTP ${res.status}`);
    const payload = await res.json();
    const rows = Array.isArray(payload) ? payload : (payload?.rows || []);
    const all = normalizeRows(rows);
    return pickRowsBySheet(all, opts.sheet);
  }

  // ---------- AN & Services Pivot State ----------
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
  }, [scenarioId, mode, seriesSel]);

  // ---------- Persisted Facts (oA.Finance-*) ----------
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
          out[entry.sheet] = await fetchFacts({
            scenarioId,
            sheet: entry.sheet,
            series: ["revenue", "cogs", "gp"],
            category: entry.category,
          });
        }
      } catch {
        // ignore
      } finally {
        if (mounted) { setPersisted(out); setLoadingPersisted(false); }
      }
    })();
    return () => { mounted = false; };
  }, [scenarioId]);

  // ---------- Ortak grid üretimi ----------
  function buildHeaders(rows: FactRow[]) {
    return Array.from(new Set(rows.map((r) => r.yyyymm))).sort((a, b) => a.localeCompare(b));
  }
  function buildIndex(rows: FactRow[]) {
    return rows.reduce((acc, r) => {
      (acc[r.series] = acc[r.series] || {})[r.yyyymm] = r.value;
      return acc;
    }, {} as Record<SeriesKey, Record<string, number>>);
  }

  const headersAN  = useMemo(() => buildHeaders(rowsAN),  [rowsAN]);
  const headersSVC = useMemo(() => buildHeaders(rowsSVC), [rowsSVC]);
  const idxAN      = useMemo(() => buildIndex(rowsAN),   [rowsAN]);
  const idxSVC     = useMemo(() => buildIndex(rowsSVC),  [rowsSVC]);

  // ============================ RENDER =======================================
  return (
    <div className={className ?? ""}>

      {/* ÜST KONTROLLER — sticky (tablolar aşağıda kalır) */}
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
                    onClick={checkCoverage} disabled={busy}>
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
                    setSeriesSel((prev) => prev.includes(s) ? prev.filter((x)=>x!==s) : [...prev, s])}
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
                  onClick={() => setCatsSel((prev)=> prev.includes(c)? prev.filter((x)=>x!==c):[...prev,c])}
                  className={"px-2 py-1 text-xs rounded border " + (on ? "bg-emerald-700 text-white border-emerald-700" :
                    "bg-white text-gray-700 border-gray-300 hover:bg-gray-50")}>
                  {c}
                </button>
              );
            })}
          </div>
          {loadingPivot && <span className="text-xs text-gray-500">Loading…</span>}
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
                  {(["revenue","cogs","gp"] as SeriesKey[])
                    .filter((s)=>seriesSel.includes(s))
                    .map((s)=>(
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
                  {(["revenue","cogs","gp"] as SeriesKey[])
                    .filter((s)=>seriesSel.includes(s))
                    .map((s)=>(
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

      {/* Persisted */}
      <Box title="Finance Facts (persisted)">
        {loadingPersisted && <div className="text-xs text-gray-500">Loading…</div>}
        {!loadingPersisted && (
          <div className="space-y-6">
            {Object.entries(persisted).map(([sheet, rows]) => {
              const headers = Array.from(new Set(rows.map((r) => r.yyyymm))).sort((a, b) => a.localeCompare(b));
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
        )}
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
