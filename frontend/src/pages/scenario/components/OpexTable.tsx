// C:/Dev/AryaIntel_CRM/frontend/src/pages/scenario/components/OpexTable.tsx
import React, { useEffect, useMemo, useRef, useState } from "react";
import { apiGet, apiPost, apiPut, apiDelete } from "../../../lib/api";

type OpenKey = number | "draft";
type OpenMap = Partial<Record<OpenKey, boolean>>;

/* ---------- Types ---------- */
type Props = {
  scenarioId: number;
  onChanged?: () => void;
  onMarkedReady?: () => void; // only navigate – OPEX'in workflow flag'i yok
};

/** OPEX header (BE: scenario_opex) */
type OpexRow = {
  id?: number;
  scenario_id?: number;

  name: string;
  category?: string | null;
  currency?: string | null;

  allocation_mode?: "none" | "fixed" | "percent" | "driver";
  periodicity?: "monthly" | "annual";

  start_year?: number | null;
  start_month?: number | null;
  end_year?: number | null;
  end_month?: number | null;

  notes?: string | null;

  created_at?: string;
  updated_at?: string;
};

/** Allocation satırı (BE: scenario_opex_alloc) */
type AllocationRow = {
  id?: number;
  opex_id?: number;
  service_id: number;
  weight_pct: number;
  basis?: "percent" | "revenue" | "volume" | "gross_margin";
};

/** Servis opsiyonları (ad ile seçim için) */
type ServiceOption = {
  id: number;
  name: string;
  code?: string | null;
};

/* ---------- Utils ---------- */
function num(v: any): number {
  const n = Number(v);
  return Number.isFinite(n) ? n : 0;
}
function numOrNull(v: string | number | null | undefined): number | null {
  if (v === null || v === undefined) return null;
  const s = String(v).trim();
  if (s === "") return null;
  const n = Number(s);
  return Number.isFinite(n) ? n : null;
}
function cls(...a: (string | false | undefined)[]) {
  return a.filter(Boolean).join(" ");
}
function ymToInput(year?: number | null, month?: number | null): string {
  if (!year || !month) return "";
  return `${year}-${String(month).padStart(2, "0")}`;
}
function inputToYM(value: string): { year: number; month: number } {
  const [y, m] = value.split("-").map((x) => Number(x));
  return { year: y || new Date().getFullYear(), month: m || 1 };
}
const fmtSvc = (s: ServiceOption) => `${s.name}${s.code ? " · " + s.code : ""}  (#${s.id})`;

/* ---------- Component ---------- */
export default function OpexTable({ scenarioId, onChanged, onMarkedReady }: Props) {
  const apiScenarioBase = `/api/scenarios/${scenarioId}`;
  const apiOpexBase = `/api/opex`;

  const [rows, setRows] = useState<OpexRow[]>([]);
  const [draft, setDraft] = useState<OpexRow | null>(null);
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [err, setErr] = useState<string | null>(null);
  const [open, setOpen] = useState<OpenMap>({});

  // Allocations per opex_id (lazy load when details opened)
  const [alloc, setAlloc] = useState<Record<number, AllocationRow[]>>({});
  const [allocDirty, setAllocDirty] = useState<Record<number, boolean>>({});

  // Service options for user-friendly selection
  const [svcOpts, setSvcOpts] = useState<ServiceOption[]>([]);
  const [svcErr, setSvcErr] = useState<string | null>(null);

  async function load() {
    setLoading(true);
    setErr(null);
    try {
      const data = await apiGet<OpexRow[]>(`${apiScenarioBase}/opex`);
      setRows(data || []);
    } catch (e: any) {
      setErr(e?.response?.data?.detail || e?.message || "Failed to load OPEX.");
    } finally {
      setLoading(false);
    }
  }

  // Load service options once (best-effort; page still usable without)
  async function loadServices() {
    setSvcErr(null);
    try {
      const data = await apiGet<any>(`${apiScenarioBase}/services`);
      if (Array.isArray(data)) {
        const norm: ServiceOption[] = data.map((s: any) => ({
          id: Number(s.id),
          name: String(s.name ?? s.service_name ?? `Service #${s.id}`),
          code: s.code ?? s.sku ?? s.short_code ?? null,
        }));
        setSvcOpts(norm);
      }
    } catch (e: any) {
      setSvcErr(e?.response?.data?.detail || e?.message || null);
      setSvcOpts([]);
    }
  }

  useEffect(() => {
    if (scenarioId) {
      load();
      loadServices();
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [scenarioId]);

  /* ---------- Header CRUD ---------- */

  function startAdd() {
    const today = new Date();
    const y = today.getFullYear();
    const m = today.getMonth() + 1;
    setDraft({
      name: "",
      category: "",
      currency: "TRY",
      allocation_mode: "percent",
      periodicity: "monthly",
      start_year: y,
      start_month: m,
      end_year: null,
      end_month: null,
      notes: "",
    });
    setOpen((p) => ({ ...p, draft: true }));
  }

  function cancelAdd() {
    setDraft(null);
    setOpen((p) => {
      const cp: OpenMap = { ...p };
      delete cp["draft"];
      return cp;
    });
  }

  function normalizeForSave<T extends OpexRow>(row: T): T {
    const body: T = {
      ...row,
      start_year: row.start_year == null ? null : num(row.start_year),
      start_month: row.start_month == null ? null : num(row.start_month),
      end_year: row.end_year == null ? null : num(row.end_year),
      end_month: row.end_month == null ? null : num(row.end_month),
    };
    return body;
  }

  async function saveNew() {
    if (!draft) return;
    setSaving(true);
    try {
      const created = await apiPost<OpexRow>(`${apiScenarioBase}/opex`, normalizeForSave(draft));
      setRows((p) => [created, ...p]);
      setDraft(null);
      onChanged?.();
    } catch (e: any) {
      alert(e?.response?.data?.detail || e?.message || "OPEX create failed.");
    } finally {
      setSaving(false);
    }
  }

  async function saveRow(r: OpexRow) {
    if (!r.id) return;
    setSaving(true);
    try {
      const upd = await apiPut<OpexRow>(`${apiOpexBase}/${r.id}`, normalizeForSave(r));
      setRows((p) => p.map((x) => (x.id === r.id ? upd : x)));
      onChanged?.();
    } catch (e: any) {
      alert(e?.response?.data?.detail || e?.message || "OPEX update failed.");
    } finally {
      setSaving(false);
    }
  }

  async function delRow(r: OpexRow) {
    if (!r.id) return;
    if (!confirm("Delete OPEX header and its details?")) return;
    try {
      await apiDelete(`${apiOpexBase}/${r.id}`);
      setRows((p) => p.filter((x) => x.id !== r.id));
      setAlloc((p) => {
        const cp = { ...p };
        delete cp[r.id!];
        return cp;
      });
      onChanged?.();
    } catch (e: any) {
      alert(e?.response?.data?.detail || e?.message || "OPEX delete failed.");
    }
  }

  // No workflow endpoint for OPEX → just navigate (optional confirmation)
  async function markReady() {
    if (!confirm("Go to Summary? (OPEX has no workflow flag)")) return;
    onMarkedReady?.();
  }

  /* ---------- Allocations (per header) ---------- */

  async function loadAlloc(opexId: number) {
    try {
      const data = await apiGet<AllocationRow[]>(`${apiOpexBase}/${opexId}/allocations`);
      setAlloc((p) => ({ ...p, [opexId]: data || [] }));
      setAllocDirty((p) => ({ ...p, [opexId]: false }));
    } catch (e: any) {
      alert(e?.response?.data?.detail || e?.message || "Failed to load allocations.");
    }
  }

  async function saveAlloc(opexId: number) {
    try {
      const rows = alloc[opexId] || [];
      const payload = rows.map((r) => ({
        service_id: Number(r.service_id),
        weight_pct: Number(r.weight_pct) || 0,
        basis: (r.basis || "percent").toLowerCase(),
      }));
      const saved = await apiPut<AllocationRow[]>(`${apiOpexBase}/${opexId}/allocations`, payload);
      setAlloc((p) => ({ ...p, [opexId]: saved || [] }));
      setAllocDirty((p) => ({ ...p, [opexId]: false }));
    } catch (e: any) {
      alert(e?.response?.data?.detail || e?.message || "Allocations save failed.");
    }
  }

  async function deleteAlloc(allocId: number, opexId: number) {
    if (!confirm("Delete this allocation row?")) return;
    try {
      await apiDelete(`${apiOpexBase}/allocations/${allocId}`);
      await loadAlloc(opexId);
    } catch (e: any) {
      alert(e?.response?.data?.detail || e?.message || "Allocation delete failed.");
    }
  }

  /* ---------- UI bits ---------- */
  const labelCls = "text-xs text-gray-600 mb-1";
  const inputCls =
    "w-full px-2 py-1 rounded border border-gray-300 focus:outline-none focus:ring";
  const inputRight = cls(inputCls, "text-right");

  const currencyOptions = useMemo(() => {
    const set = new Set<string>();
    rows.forEach((r) => r.currency && set.add(r.currency));
    draft?.currency && set.add(draft.currency);
    if (!set.size) set.add("TRY");
    return Array.from(set.values());
  }, [rows, draft]);

  /* ====== Row component (memo) ====== */
  const BasicRow = React.memo(function BasicRow({
    value,
    onChange,
    isDraft,
  }: {
    value: OpexRow;
    onChange: (next: OpexRow) => void;
    isDraft?: boolean;
  }) {
    const key: OpenKey = isDraft ? "draft" : (value.id as number);
    const advOpen = !!open[key];

    // locals for text inputs
    const [localName, setLocalName] = useState<string>(value.name ?? "");
    const [localCategory, setLocalCategory] = useState<string>(value.category ?? "");
    const [localNotes, setLocalNotes] = useState<string>(value.notes ?? "");
    // Month locals
    const [startYM, setStartYM] = useState<string>(
      ymToInput(value.start_year ?? null, value.start_month ?? null)
    );
    const [endYM, setEndYM] = useState<string>(
      ymToInput(value.end_year ?? null, value.end_month ?? null)
    );

    // Allocations local state
    const opexId = value.id!;
    const arows = alloc[opexId] || [];

    useEffect(() => {
      setLocalName(value.name ?? "");
      setLocalCategory(value.category ?? "");
      setLocalNotes(value.notes ?? "");
      setStartYM(ymToInput(value.start_year ?? null, value.start_month ?? null));
      setEndYM(ymToInput(value.end_year ?? null, value.end_month ?? null));
      // eslint-disable-next-line react-hooks/exhaustive-deps
    }, [value.id]);

    useEffect(() => {
      if (advOpen && value.id && alloc[value.id] === undefined) {
        loadAlloc(value.id);
      }
      // eslint-disable-next-line react-hooks/exhaustive-deps
    }, [advOpen]);

    const commitField = (field: keyof OpexRow, v: any) => {
      if ((value as any)[field] !== v) onChange({ ...value, [field]: v });
    };

    const commitOnEnter =
      (cb: () => void) =>
      (e: React.KeyboardEvent<HTMLInputElement>) => {
        if (e.key === "Enter") {
          cb();
          (e.target as HTMLInputElement).blur();
        }
      };

    const addAllocRow = () => {
      if (!value.id) return;
      const next: AllocationRow = {
        opex_id: value.id,
        service_id: 0,
        weight_pct: 0,
        basis: "percent",
      };
      setAlloc((p) => ({ ...p, [value.id!]: [...(p[value.id!] || []), next] }));
      setAllocDirty((p) => ({ ...p, [value.id!]: true }));
    };

    // ---------- Typeahead (service selector) ----------
    function ServiceTypeahead({
      idx,
      row,
    }: {
      idx: number;
      row: AllocationRow;
    }) {
      const [query, setQuery] = useState<string>(() => {
        const curr = svcOpts.find((s) => s.id === row.service_id);
        if (curr) return fmtSvc(curr);
        return row.service_id ? `#${row.service_id}` : "";
      });
      const [openDD, setOpenDD] = useState(false);
      const wrapRef = useRef<HTMLDivElement | null>(null);

      useEffect(() => {
        function onDocClick(e: MouseEvent) {
          if (!wrapRef.current) return;
          if (!wrapRef.current.contains(e.target as Node)) setOpenDD(false);
        }
        document.addEventListener("mousedown", onDocClick);
        return () => document.removeEventListener("mousedown", onDocClick);
      }, []);

      const items = useMemo(() => {
        const q = query.trim().toLowerCase();
        if (!q) return svcOpts.slice(0, 10);
        const asNum = /^\d+$/.test(q) ? Number(q) : null;
        return svcOpts
          .filter((s) => {
            if (asNum && s.id === asNum) return true;
            const blob = `${s.name} ${s.code ?? ""} ${s.id}`.toLowerCase();
            return blob.includes(q);
          })
          .slice(0, 10);
      }, [query, svcOpts]);

      const pick = (s: ServiceOption) => {
        setQuery(fmtSvc(s));
        setOpenDD(false);
        setAlloc((p) => {
          const list = [...(p[opexId] || [])];
          list[idx] = { ...list[idx], service_id: s.id };
          return { ...p, [opexId]: list };
        });
        setAllocDirty((p) => ({ ...p, [opexId]: true }));
      };

      const onBlurToIdFallback = () => {
        // if user typed pure number, accept as ID
        const onlyDigits = query.replace(/[^\d]/g, "");
        if (onlyDigits && /^\d+$/.test(onlyDigits)) {
          const id = Number(onlyDigits);
          setAlloc((p) => {
            const list = [...(p[opexId] || [])];
            list[idx] = { ...list[idx], service_id: id };
            return { ...p, [opexId]: list };
          });
          setAllocDirty((p) => ({ ...p, [opexId]: true }));
        }
      };

      return (
        <div className="relative" ref={wrapRef}>
          <input
            value={query}
            onChange={(e) => {
              setQuery(e.target.value);
              setOpenDD(true);
            }}
            onFocus={() => setOpenDD(true)}
            onBlur={onBlurToIdFallback}
            placeholder="Search service…"
            className={inputCls}
            autoComplete="off"
            spellCheck={false}
            title={
              svcErr
                ? `Service list unavailable (${svcErr}). You can still enter a numeric ID.`
                : "Search by name/code or enter ID"
            }
          />
          {openDD && items.length > 0 && (
            <div className="absolute z-10 mt-1 w-full bg-white border rounded shadow max-h-56 overflow-auto">
              {items.map((s) => (
                <button
                  key={s.id}
                  className="w-full text-left px-3 py-2 hover:bg-gray-100"
                  onMouseDown={(e) => e.preventDefault()}
                  onClick={() => pick(s)}
                >
                  <div className="font-medium">{s.name}</div>
                  <div className="text-xs text-gray-600">
                    {(s.code || "").toString()} #{s.id}
                  </div>
                </button>
              ))}
            </div>
          )}
        </div>
      );
    }

    // ----------- Helpers: percent tools -----------
    const totalPct = (arows || []).reduce((s, a) => s + (Number(a.weight_pct) || 0), 0);
    const normalizeTo100 = () => {
      const rowsLocal = [...(alloc[opexId] || [])];
      const sum = rowsLocal.reduce((s, r) => s + (Number(r.weight_pct) || 0), 0);
      if (sum <= 0) return;
      const scaled = rowsLocal.map((r) => ({
        ...r,
        weight_pct: (Number(r.weight_pct) || 0) * (100 / sum),
      }));
      setAlloc((p) => ({ ...p, [opexId]: scaled }));
      setAllocDirty((p) => ({ ...p, [opexId]: true }));
    };
    const distributeEqually = () => {
      const n = (alloc[opexId] || []).length || 1;
      const each = 100 / n;
      const eq = (alloc[opexId] || []).map((r) => ({ ...r, weight_pct: each }));
      setAlloc((p) => ({ ...p, [opexId]: eq }));
      setAllocDirty((p) => ({ ...p, [opexId]: true }));
    };

    return (
      <>
        <tr className="odd:bg-white even:bg-gray-50 align-top">
          {/* Name */}
          <td className="px-3 py-2">
            <label className={labelCls}>Name</label>
            <input
              value={localName}
              onChange={(e) => setLocalName(e.target.value)}
              onBlur={() => commitField("name", localName)}
              onKeyDown={commitOnEnter(() => commitField("name", localName))}
              className={inputCls}
              autoComplete="off"
              spellCheck={false}
            />
          </td>

          {/* Category */}
          <td className="px-3 py-2">
            <label className={labelCls}>Category</label>
            <input
              value={localCategory}
              onChange={(e) => setLocalCategory(e.target.value)}
              onBlur={() => commitField("category", localCategory)}
              onKeyDown={commitOnEnter(() => commitField("category", localCategory))}
              className={inputCls}
              autoComplete="off"
              spellCheck={false}
            />
          </td>

          {/* Currency */}
          <td className="px-3 py-2">
            <label className={labelCls}>Currency</label>
            <input
              list="opex-currency-options"
              value={value.currency || "TRY"}
              onChange={(e) => commitField("currency", e.target.value.toUpperCase())}
              className={inputCls}
              maxLength={3}
            />
          </td>

          {/* Start (month picker) */}
          <td className="px-3 py-2">
            <label className={labelCls}>Start</label>
            <input
              type="month"
              lang="en"
              value={startYM}
              onChange={(e) => {
                setStartYM(e.target.value);
                const { year, month } = inputToYM(e.target.value);
                onChange({ ...value, start_year: year, start_month: month });
              }}
              className={inputCls}
            />
          </td>

          {/* Periodicity */}
          <td className="px-3 py-2">
            <label className={labelCls}>Periodicity</label>
            <select
              value={value.periodicity || "monthly"}
              onChange={(e) =>
                commitField("periodicity", e.target.value as OpexRow["periodicity"])
              }
              className={inputCls}
            >
              <option value="monthly">Monthly</option>
              <option value="annual">Annual</option>
            </select>
          </td>

          {/* Allocation mode */}
          <td className="px-3 py-2">
            <label className={labelCls}>Alloc. Mode</label>
            <select
              value={value.allocation_mode || "percent"}
              onChange={(e) =>
                commitField("allocation_mode", e.target.value as OpexRow["allocation_mode"])
              }
              className={inputCls}
            >
              <option value="none">None</option>
              <option value="fixed">Fixed</option>
              <option value="percent">Percent</option>
              <option value="driver">Driver</option>
            </select>
          </td>

          {/* Actions */}
          <td className="px-3 py-2 w-[360px]">
            <div className={labelCls}>&nbsp;</div>
            <div className="flex flex-wrap items-center gap-2">
              {isDraft ? (
                <>
                  <button
                    onClick={saveNew}
                    disabled={saving}
                    className={cls(
                      "px-3 py-1 rounded text-white",
                      saving ? "bg-indigo-400" : "bg-indigo-600 hover:bg-indigo-700"
                    )}
                  >
                    Save
                  </button>
                  <button
                    onClick={cancelAdd}
                    className="px-3 py-1 rounded bg-gray-200 hover:bg-gray-300"
                  >
                    Cancel
                  </button>
                </>
              ) : (
                <>
                  <button
                    onClick={() => saveRow(value)}
                    disabled={saving}
                    className={cls(
                      "px-3 py-1 rounded text-white",
                      saving ? "bg-indigo-400" : "bg-indigo-600 hover:bg-indigo-700"
                    )}
                    title="Save row"
                  >
                    Save
                  </button>
                  <button
                    onClick={() => delRow(value)}
                    className="px-3 py-1 rounded bg-gray-200 hover:bg-gray-300"
                    title="Delete row"
                  >
                    Delete
                  </button>
                </>
              )}
              <button
                onClick={() =>
                  setOpen((p) => {
                    const isOpen = !!p[key];
                    const np = { ...p, [key]: !isOpen };
                    return np;
                  })
                }
                className="px-3 py-1 rounded bg-gray-100 hover:bg-gray-200"
              >
                {advOpen ? "Hide" : "Details"}
              </button>
            </div>
          </td>
        </tr>

        {/* Advanced row */}
        {advOpen && (
          <tr className="bg-white border-t">
            <td colSpan={7} className="px-3 pb-4">
              {/* Dates + Notes */}
              <div className="grid grid-cols-1 md:grid-cols-4 gap-3 mt-2">
                <div>
                  <div className={labelCls}>End</div>
                  <div className="flex gap-2">
                    <input
                      type="month"
                      lang="en"
                      value={endYM}
                      onChange={(e) => {
                        setEndYM(e.target.value);
                        const { year, month } = inputToYM(e.target.value);
                        onChange({ ...value, end_year: year, end_month: month });
                      }}
                      className={inputCls}
                    />
                    {endYM && (
                      <button
                        onClick={() => {
                          setEndYM("");
                          onChange({ ...value, end_year: null, end_month: null });
                        }}
                        className="px-2 rounded bg-gray-100 hover:bg-gray-200"
                        title="Clear end date"
                      >
                        Clear
                      </button>
                    )}
                  </div>
                </div>
                <div className="md:col-span-3">
                  <div className={labelCls}>Notes</div>
                  <input
                    value={localNotes}
                    onChange={(e) => setLocalNotes(e.target.value)}
                    onBlur={() => commitField("notes", localNotes)}
                    onKeyDown={commitOnEnter(() => commitField("notes", localNotes))}
                    className={inputCls}
                    autoComplete="off"
                    spellCheck={false}
                  />
                </div>
              </div>

              {/* Allocations */}
              <div className="mt-4 border-t pt-3">
                <div className="flex items-center justify-between mb-2">
                  <div className="font-medium text-gray-800">Allocations</div>
                  <div className="flex items-center gap-3">
                    {/* Total badge */}
                    <span
                      className={cls(
                        "text-xs rounded px-2 py-1",
                        Math.round(totalPct) === 100
                          ? "bg-green-100 text-green-800 border border-green-200"
                          : "bg-yellow-100 text-yellow-800 border border-yellow-200"
                      )}
                      title="Sum of Weight % (for Percent basis)"
                    >
                      Total %: {totalPct.toFixed(2)}
                    </span>
                    <button
                      onClick={distributeEqually}
                      className="px-3 py-1 rounded bg-gray-100 hover:bg-gray-200"
                      title="Set equal weights that sum to 100%"
                    >
                      Equalize
                    </button>
                    <button
                      onClick={normalizeTo100}
                      className="px-3 py-1 rounded bg-gray-100 hover:bg-gray-200"
                      title="Scale current weights to sum to 100%"
                    >
                      Normalize
                    </button>
                    <button
                      onClick={() => loadAlloc(opexId)}
                      className="px-3 py-1 rounded bg-gray-100 hover:bg-gray-200"
                    >
                      Refresh
                    </button>
                    <button
                      onClick={addAllocRow}
                      className="px-3 py-1 rounded text-white bg-indigo-600 hover:bg-indigo-700"
                    >
                      + Add
                    </button>
                    <button
                      onClick={() => saveAlloc(opexId)}
                      disabled={!allocDirty[opexId]}
                      className={cls(
                        "px-3 py-1 rounded text-white",
                        allocDirty[opexId]
                          ? "bg-indigo-600 hover:bg-indigo-700"
                          : "bg-indigo-300 cursor-not-allowed"
                      )}
                      title={!allocDirty[opexId] ? "No changes" : "Save allocations"}
                    >
                      Save Allocations
                    </button>
                  </div>
                </div>

                <div className="overflow-x-auto">
                  <table className="min-w-full text-sm">
                    <thead className="bg-gray-50">
                      <tr>
                        <th className="px-3 py-2 w-80">Service</th>
                        <th className="px-3 py-2 w-32 text-right">Weight %</th>
                        <th className="px-3 py-2 w-40">Basis</th>
                        <th className="px-3 py-2 w-32">Actions</th>
                      </tr>
                    </thead>
                    <tbody>
                      {(arows || []).map((a, idx) => (
                        <tr key={a.id ?? `new-${idx}`} className="odd:bg-white even:bg-gray-50">
                          <td className="px-3 py-2">
                            <ServiceTypeahead idx={idx} row={a} />
                          </td>
                          <td className="px-3 py-2">
                            <input
                              type="text"
                              inputMode="decimal"
                              pattern="[0-9.,]*"
                              value={String(a.weight_pct ?? 0)}
                              onChange={(e) => {
                                const v = Number(e.target.value || 0);
                                setAlloc((p) => {
                                  const list = [...(p[opexId] || [])];
                                  list[idx] = { ...list[idx], weight_pct: v };
                                  return { ...p, [opexId]: list };
                                });
                                setAllocDirty((p) => ({ ...p, [opexId]: true }));
                              }}
                              className={inputRight}
                            />
                          </td>
                          <td className="px-3 py-2">
                            <select
                              value={a.basis || "percent"}
                              onChange={(e) => {
                                const v = e.target.value as AllocationRow["basis"];
                                setAlloc((p) => {
                                  const list = [...(p[opexId] || [])];
                                  list[idx] = { ...list[idx], basis: v };
                                  return { ...p, [opexId]: list };
                                });
                                setAllocDirty((p) => ({ ...p, [opexId]: true }));
                              }}
                              className={inputCls}
                            >
                              <option value="percent">Percent</option>
                              <option value="revenue">Revenue</option>
                              <option value="volume">Volume</option>
                              <option value="gross_margin">Gross margin</option>
                            </select>
                          </td>
                          <td className="px-3 py-2">
                            {a.id ? (
                              <button
                                onClick={() => deleteAlloc(a.id!, opexId)}
                                className="px-3 py-1 rounded bg-gray-200 hover:bg-gray-300"
                              >
                                Delete
                              </button>
                            ) : (
                              <span className="text-xs text-gray-500">new</span>
                            )}
                          </td>
                        </tr>
                      ))}

                      {!arows?.length && (
                        <tr>
                          <td className="px-3 py-3 text-sm text-gray-500" colSpan={4}>
                            No allocations yet. Click <b>+ Add</b> to start.
                          </td>
                        </tr>
                      )}
                    </tbody>
                  </table>
                </div>

                {Math.round(totalPct) !== 100 && (value.allocation_mode ?? "percent") === "percent" && (
                  <div className="mt-2 text-xs text-yellow-800 bg-yellow-50 border border-yellow-200 rounded px-2 py-1 inline-block">
                    Hint: For <b>Percent</b> basis it’s ideal if weights sum to 100%. Use
                    <span className="mx-1 font-medium">Normalize</span> or
                    <span className="mx-1 font-medium">Equalize</span>.
                  </div>
                )}
              </div>
            </td>
          </tr>
        )}
      </>
    );
  });

  /* ---------- Render ---------- */
  return (
    <div className="space-y-3">
      <div className="flex items-center justify-between">
        <h3 className="font-semibold text-lg">OPEX</h3>
        <div className="flex gap-2">
          <button
            onClick={load}
            className="px-3 py-1 rounded bg-gray-100 hover:bg-gray-200"
          >
            Refresh
          </button>
          <button
            onClick={startAdd}
            className="px-3 py-1 rounded text-white bg-indigo-600 hover:bg-indigo-700"
          >
            + Add
          </button>
          <button
            onClick={markReady}
            className="px-3 py-1 rounded text-white bg-indigo-600 hover:bg-indigo-700"
          >
            Go to Summary
          </button>
        </div>
      </div>

      {err && (
        <div className="text-sm text-red-600 bg-red-50 border border-red-200 p-2 rounded">
          {err}
        </div>
      )}

      {loading ? (
        <div className="text-sm text-gray-500">Loading…</div>
      ) : (
        <div className="overflow-x-auto border rounded bg-white">
          {/* datalist: currency */}
          <datalist id="opex-currency-options">
            {currencyOptions.map((opt) => (
              <option key={opt} value={opt} />
            ))}
          </datalist>

          <table className="min-w-full text-sm">
            <thead className="bg-gray-50">
              <tr>
                <th className="px-3 py-2">Name</th>
                <th className="px-3 py-2">Category</th>
                <th className="px-3 py-2 w-24">Curr.</th>
                <th className="px-3 py-2 w-36">Start</th>
                <th className="px-3 py-2 w-32">Period</th>
                <th className="px-3 py-2 w-36">Alloc. Mode</th>
                <th className="px-3 py-2 w-[360px]">Actions</th>
              </tr>
            </thead>
            <tbody>
              {draft && (
                <BasicRow
                  key="draft"
                  value={draft}
                  onChange={(next) => setDraft(next)}
                  isDraft
                />
              )}

              {rows.map((r) => (
                <BasicRow
                  key={r.id}
                  value={r}
                  onChange={(next) =>
                    setRows((p) => p.map((x) => (x.id === r.id ? next : x)))
                  }
                />
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}
