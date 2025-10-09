// frontend/src/pages/scenario/components/CapexTable.tsx
import React, { useEffect, useMemo, useState } from "react";
import { apiGet, apiPost, apiPut, apiDelete } from "../../../lib/api";

type OpenKey = number | "draft";

/* ---------- Types ---------- */
type Props = {
  scenarioId: number;
  onChanged?: () => void;
  onMarkedReady?: () => void;
};

type CapexRow = {
  id?: number;
  scenario_id?: number;
  year: number;
  month: number; // 1..12 – CAPEX spend month (cash out)
  amount: number;
  notes?: string | null;

  // Basic
  asset_name?: string | null;
  category?: string | null;
  service_start_year?: number | null;
  service_start_month?: number | null;
  useful_life_months?: number | null;
  depr_method?: string | null;
  is_active?: boolean | null;

  // Advanced
  salvage_value?: number | null;
  disposal_year?: number | null;
  disposal_month?: number | null;
  disposal_proceeds?: number | null;
  replace_at_end?: boolean | null;
  per_unit_cost?: number | null;
  quantity?: number | null;
  contingency_pct?: number | null;
  partial_month_policy?: string | null;

  // ====== Excel-parity: Return (Reward) controls ======
  reward_enabled?: boolean | null;           // toggle
  reward_pct?: number | null;                // % as 0..100 (e.g., 15 for 15%)
  reward_spread_kind?: string | null;        // e.g., "even"
  term_months_override?: number | null;      // optional override for spread term

  // Links created by generators
  linked_boq_item_id?: number | null;
  linked_service_id?: number | null;
};

type ScenarioLite = {
  id: number;
  default_capex_reward_pct?: number | null;
};

/* ---------- Utils ---------- */
function num(v: any): number {
  const n = Number(v);
  return Number.isFinite(n) ? n : 0;
}
function parseLocaleNumber(v: any): number {
  if (v == null) return 0;
  if (typeof v === "number" && Number.isFinite(v)) return v;
  if (typeof v !== "string") return Number(v) || 0;
  // normalize "12 345,67" / "12.345,67" / "12,345.67"
  const s = v.trim().replace(/\s+/g, "");
  // if there are both separators, assume last non-digit is decimal
  const decMatch = s.match(/[^0-9](\d{1,2})$/);
  if (decMatch) {
    const decSepIndex = s.length - decMatch[0].length;
    const intPart = s.slice(0, decSepIndex).replace(/[^0-9]/g, "");
    const decPart = s.slice(decSepIndex + 1).replace(/[^0-9]/g, "");
    return Number(`${intPart}.${decPart}`) || 0;
  }
  // otherwise strip all non-digits except dot and parse
  const cleaned = s.replace(/[^0-9.]/g, "");
  return Number(cleaned) || 0;
}
function toNum(v: any): number {
  const n = parseLocaleNumber(v);
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

/* ---------- Category presets ---------- */
const TENDER_CATEGORY_PRESETS = [
  "Emulsion Storage",
  "Ammonium Nitrate Handling",
  "Tiltframe",
  "Wallaby Bins 34T per Bin",
  "Conveyors",
  "Electrical & Controls",
  "Civil Works",
  "Foundations",
  "Buildings & Shelters",
  "Site Works & Roads",
  "Utilities & Services",
  "Water System",
  "Air/Compressor System",
  "Power Distribution",
  "Lighting",
  "Safety & Fire",
  "Commissioning & Training",
  "Spares & Consumables",
  "Miscellaneous / Contingency",
];

/* ---------- Component ---------- */
export default function CapexTable({ scenarioId, onChanged, onMarkedReady }: Props) {
  const apiBase = `/api/scenarios/${scenarioId}`;

  const [rows, setRows] = useState<CapexRow[]>([]);
  const [draft, setDraft] = useState<CapexRow | null>(null);
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [err, setErr] = useState<string | null>(null);
  const [openAdv, setOpenAdv] = useState<Partial<Record<OpenKey, boolean>>>({});

  // Scenario defaults (prefill reward_pct)
  const [scenario, setScenario] = useState<ScenarioLite | null>(null);

  async function loadScenario() {
    try {
      const sc = await apiGet<ScenarioLite>(`${apiBase}`);
      setScenario(sc || null);
    } catch {
      // non-blocking
    }
  }

  async function load() {
    setLoading(true);
    setErr(null);
    try {
      const data = await apiGet<CapexRow[]>(`${apiBase}/capex`);
      setRows(data || []);
    } catch (e: any) {
      setErr(e?.message || "Failed to load CAPEX.");
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    if (scenarioId) {
      loadScenario();
      load();
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [scenarioId]);

  function startAdd() {
    const today = new Date();
    const y = today.getFullYear();
    const m = today.getMonth() + 1;
    setDraft({
      year: y,
      month: m,
      amount: 0,
      asset_name: "",
      category: "",
      service_start_year: y,
      service_start_month: m,
      useful_life_months: 60,
      depr_method: "straight_line",
      is_active: true,
      salvage_value: 0,
      disposal_year: null,
      disposal_month: null,
      disposal_proceeds: 0,
      replace_at_end: false,
      per_unit_cost: null,
      quantity: null,
      contingency_pct: 0,
      partial_month_policy: "full_month",
      notes: "",
      // Reward defaults
      reward_enabled: false,
      reward_pct: scenario?.default_capex_reward_pct ?? null,
      reward_spread_kind: "even",
      term_months_override: null,
      linked_boq_item_id: null,
      linked_service_id: null,
    });
    setOpenAdv((p) => ({ ...p, draft: false }));
  }

  function cancelAdd() {
    setDraft(null);
    setOpenAdv((p) => {
      const cp = { ...p };
      delete cp["draft"];
      return cp;
    });
  }

  function normalizeForSave<T extends CapexRow>(row: T): T {
    const body: T = {
      ...row,
      year: num(row.year),
      month: num(row.month),
      amount: num(row.amount),
      useful_life_months:
        row.useful_life_months == null ? null : num(row.useful_life_months),
      salvage_value: row.salvage_value == null ? null : num(row.salvage_value),
      disposal_year: row.disposal_year == null ? null : num(row.disposal_year),
      disposal_month: row.disposal_month == null ? null : num(row.disposal_month),
      disposal_proceeds:
        row.disposal_proceeds == null ? null : num(row.disposal_proceeds),
      per_unit_cost: row.per_unit_cost == null ? null : num(row.per_unit_cost),
      quantity: row.quantity == null ? null : num(row.quantity),
      contingency_pct: row.contingency_pct == null ? null : num(row.contingency_pct),
      reward_pct: row.reward_pct == null ? null : num(row.reward_pct),
      term_months_override:
        row.term_months_override == null ? null : num(row.term_months_override),
    };
    return body;
  }

  async function saveNew() {
    if (!draft) return;
    setSaving(true);
    try {
      const created = await apiPost<CapexRow>(`${apiBase}/capex`, normalizeForSave(draft));
      setRows((p) => [...p, created]);
      setDraft(null);
      onChanged?.();
    } catch (e: any) {
      alert(e?.response?.data?.detail || e?.message || "CAPEX save failed.");
    } finally {
      setSaving(false);
    }
  }

  async function saveRow(r: CapexRow) {
    if (!r.id) return;
    setSaving(true);
    try {
      const upd = await apiPut<CapexRow>(`${apiBase}/capex/${r.id}`, normalizeForSave(r));
      setRows((p) => p.map((x) => (x.id === r.id ? upd : x)));
      onChanged?.();
    } catch (e: any) {
      alert(e?.response?.data?.detail || e?.message || "CAPEX update failed.");
    } finally {
      setSaving(false);
    }
  }

  async function delRow(r: CapexRow) {
    if (!r.id) return;
    if (!confirm("Delete CAPEX item?")) return;
    try {
      await apiDelete(`${apiBase}/capex/${r.id}`);
      setRows((p) => p.filter((x) => x.id !== r.id));
      onChanged?.();
    } catch (e: any) {
      alert(e?.response?.data?.detail || e?.message || "CAPEX delete failed.");
    }
  }

  // ==== Generators: CAPEX → BOQ / Service (server is source of truth) ====
  async function generateWithAttempts(urls: Array<{ url: string; body?: any }>) {
    let lastErr: any = null;
    for (const u of urls) {
      try {
        const res = await apiPost<any>(u.url, u.body ?? {});
        return res;
      } catch (e: any) {
        lastErr = e;
        const st = e?.response?.status;
        if (![404, 405].includes(st)) break; // other errors: stop trying
      }
    }
    throw lastErr;
  }

  async function generateBoqFromCapex(r: CapexRow) {
    if (!r.id) return alert("Please save the CAPEX row first.");
    if (!(r.reward_enabled && num(r.reward_pct) > 0))
      return alert("Enable Reward and set Return % > 0 in Details.");

    try {
      setSaving(true);
      const attempts = [
        { url: `${apiBase}/capex/${r.id}/generate/boq` },
        { url: `${apiBase}/capex/${r.id}/generate-boq` },
        { url: `${apiBase}/capex/${r.id}/generate`, body: { target: "boq" } },
      ];
      const out = await generateWithAttempts(attempts);

      const linkId = out?.linked_boq_item_id ?? out?.boq_id ?? out?.id ?? null;
      if (linkId) {
        setRows((p) =>
          p.map((x) => (x.id === r.id ? { ...x, linked_boq_item_id: linkId } : x))
        );
      }
      await load();
      onChanged?.();
      alert("Generated BOQ line from CAPEX.");
    } catch (e: any) {
      alert(
        e?.response?.data?.detail ||
          e?.message ||
          "Could not generate BOQ from CAPEX. Please ensure backend generate endpoint exists."
      );
    } finally {
      setSaving(false);
    }
  }

  async function generateServiceFromCapex(r: CapexRow) {
    if (!r.id) return alert("Please save the CAPEX row first.");
    if (!(r.reward_enabled && num(r.reward_pct) > 0))
      return alert("Enable Reward and set Return % > 0 in Details.");

    try {
      setSaving(true);
      const attempts = [
        { url: `${apiBase}/capex/${r.id}/generate/service` },
        { url: `${apiBase}/capex/${r.id}/generate-service` },
        { url: `${apiBase}/capex/${r.id}/generate`, body: { target: "service" } },
      ];
      const out = await generateWithAttempts(attempts);

      const linkId = out?.linked_service_id ?? out?.service_id ?? out?.id ?? null;
      if (linkId) {
        setRows((p) =>
          p.map((x) => (x.id === r.id ? { ...x, linked_service_id: linkId } : x))
        );
      }
      await load();
      onChanged?.();
      alert("Generated Service from CAPEX.");
    } catch (e: any) {
      alert(
        e?.response?.data?.detail ||
          e?.message ||
          "Could not generate Service from CAPEX. Please ensure backend generate endpoint exists."
      );
    } finally {
      setSaving(false);
    }
  }

  async function markReady() {
    if (!confirm("Mark CAPEX as ready and move to READY (P&L)?")) return;

    const attempts: Array<() => Promise<any>> = [
      () => apiPost(`${apiBase}/workflow/mark-capex-ready`, {}),
      () => apiPut(`${apiBase}/workflow/mark-capex-ready`, {}),
    ];

    let lastErr: any = null;
    for (const run of attempts) {
      try {
        await run();
        onMarkedReady?.();
        alert("Workflow moved to READY.");
        return;
      } catch (e: any) {
        lastErr = e;
        const st = e?.response?.status;
        if (![404, 405].includes(st)) break;
      }
    }
    alert(lastErr?.response?.data?.detail || lastErr?.message || "Cannot mark CAPEX as ready.");
  }

  const total = useMemo(
    () => rows.reduce((s, r) => s + (Number(r.amount) || 0), 0),
    [rows]
  );

  /* ---------- UI bits ---------- */
  const labelCls = "text-xs text-gray-600 mb-1";
  const inputCls =
    "w-full px-2 py-1 rounded border border-gray-300 focus:outline-none focus:ring";
  const inputRight = cls(inputCls, "text-right");
  const badgeCls =
    "inline-flex items-center rounded-full px-2 py-0.5 text-xs font-medium";

  // Category öneri listesi: preset + satırlardan gelen benzersizler
  const categoryOptions = useMemo(() => {
    const set = new Set<string>(TENDER_CATEGORY_PRESETS.map((s) => s.trim()));
    for (const r of rows) {
      if (r.category && r.category.trim()) set.add(r.category.trim());
    }
    if (draft?.category && draft.category.trim()) set.add(draft.category.trim());
    return Array.from(set.values());
  }, [rows, draft]);

  /* ====== Row component (memo'lu) ====== */
  const BasicRow = React.memo(function BasicRow({
    value,
    onChange,
    isDraft,
  }: {
    value: CapexRow;
    onChange: (next: CapexRow) => void;
    isDraft?: boolean;
  }) {
    const key: OpenKey = isDraft ? "draft" : (value.id as number);
    const advOpen = !!openAdv[key];

    // ---- LOCAL text state’ler (caret kaymasını engeller) ----
    const [localAsset, setLocalAsset] = useState<string>(value.asset_name ?? "");
    const [localCategory, setLocalCategory] = useState<string>(value.category ?? "");
    const [localNotes, setLocalNotes] = useState<string>(value.notes ?? "");

    // numeric locals
    const [localAmount, setLocalAmount] = useState<string>(String(value.amount ?? 0));
    const [localULife, setLocalULife] = useState<string>(String(value.useful_life_months ?? ""));
    const [localDispProc, setLocalDispProc] = useState<string>(String(value.disposal_proceeds ?? ""));
    const [localPerUnit, setLocalPerUnit] = useState<string>(String(value.per_unit_cost ?? ""));
    const [localQty, setLocalQty] = useState<string>(String(value.quantity ?? ""));
    const [localSalvage, setLocalSalvage] = useState<string>(String(value.salvage_value ?? ""));
    const [localContPct, setLocalContPct] = useState<string>(String(value.contingency_pct ?? ""));

    // Reward locals
    const [localRewardPct, setLocalRewardPct] = useState<string>(
      value.reward_pct == null ? "" : String(value.reward_pct)
    );
    const [localTermOverride, setLocalTermOverride] = useState<string>(
      value.term_months_override == null ? "" : String(value.term_months_override)
    );

    // Satır kimliği değişince lokal state’i senkle
    useEffect(() => {
      setLocalAsset(value.asset_name ?? "");
      setLocalCategory(value.category ?? "");
      setLocalNotes(value.notes ?? "");
      setLocalAmount(String(value.amount ?? 0));
      setLocalULife(value.useful_life_months == null ? "" : String(value.useful_life_months));
      setLocalDispProc(value.disposal_proceeds == null ? "" : String(value.disposal_proceeds));
      setLocalPerUnit(value.per_unit_cost == null ? "" : String(value.per_unit_cost));
      setLocalQty(value.quantity == null ? "" : String(value.quantity));
      setLocalSalvage(value.salvage_value == null ? "" : String(value.salvage_value));
      setLocalContPct(value.contingency_pct == null ? "" : String(value.contingency_pct));
      setLocalRewardPct(value.reward_pct == null ? "" : String(value.reward_pct));
      setLocalTermOverride(value.term_months_override == null ? "" : String(value.term_months_override));
      // eslint-disable-next-line react-hooks/exhaustive-deps
    }, [value.id]);

    // Commit helpers
    const commitField = (field: "asset_name" | "category" | "notes", v: string) => {
      if (field === "asset_name" && v !== (value.asset_name ?? "")) {
        onChange({ ...value, asset_name: v });
      } else if (field === "category" && v !== (value.category ?? "")) {
        onChange({ ...value, category: v });
      } else if (field === "notes" && v !== (value.notes ?? "")) {
        onChange({ ...value, notes: v });
      }
    };

    const commitNum = (field: keyof CapexRow, raw: string) => {
      const next = { ...value } as any;
      next[field] = numOrNull(raw);
      if (field === "amount" && next[field] == null) next[field] = 0;
      onChange(next);
    };

    const commitOnEnter =
      (cb: () => void) =>
      (e: React.KeyboardEvent<HTMLInputElement>) => {
        if (e.key === "Enter") {
          cb();
          (e.target as HTMLInputElement).blur();
        }
      };

    const LinkPill = ({ id, color, label }: { id?: number | null; color: "emerald" | "indigo"; label: string }) =>
      id ? (
        <span
          className={cls(
            badgeCls,
            color === "emerald"
              ? "bg-emerald-50 text-emerald-700 border border-emerald-200"
              : "bg-indigo-50 text-indigo-700 border border-indigo-200"
          )}
        >
          {label} #{id}
        </span>
      ) : null;

    const canGenerate = !!value.reward_enabled && num(value.reward_pct) > 0;

    return (
      <>
        <tr className="odd:bg-white even:bg-gray-50 align-top">
          {/* Asset Name */}
          <td className="px-3 py-2">
            <label className={labelCls}>Asset Name</label>
            <input
              value={localAsset}
              onChange={(e) => setLocalAsset(e.target.value)}
              onBlur={() => commitField("asset_name", localAsset)}
              onKeyDown={commitOnEnter(() => commitField("asset_name", localAsset))}
              className={inputCls}
              autoComplete="off"
              spellCheck={false}
            />
            <div className="mt-1 space-x-2">
              <LinkPill id={value.linked_service_id} color="emerald" label="Linked Service" />
              <LinkPill id={value.linked_boq_item_id} color="indigo" label="Linked BOQ" />
            </div>
          </td>

          {/* Category */}
          <td className="px-3 py-2">
            <label className={labelCls}>Category</label>
            <input
              list="capex-category-options"
              value={localCategory}
              onChange={(e) => setLocalCategory(e.target.value)}
              onBlur={() => commitField("category", localCategory)}
              onKeyDown={commitOnEnter(() => commitField("category", localCategory))}
              className={inputCls}
              placeholder="Select or type…"
              autoComplete="off"
              spellCheck={false}
            />
          </td>

          {/* Spend (Y/M) */}
          <td className="px-3 py-2">
            <label className={labelCls}>Spend (Y/M)</label>
            <input
              type="month"
              lang="en"
              value={ymToInput(value.year, value.month)}
              onChange={(e) => {
                const { year, month } = inputToYM(e.target.value);
                onChange({ ...value, year, month });
              }}
              className={inputCls}
            />
          </td>

          {/* Amount (local string) */}
          <td className="px-3 py-2">
            <label className={labelCls}>Amount</label>
            <input
              type="text"
              inputMode="decimal"
              pattern="[0-9.,]*"
              value={localAmount}
              onChange={(e) => setLocalAmount(e.target.value)}
              onBlur={() => commitNum("amount", localAmount)}
              onKeyDown={commitOnEnter(() => commitNum("amount", localAmount))}
              className={inputRight}
              autoComplete="off"
            />
          </td>

          {/* Active */}
          <td className="px-3 py-2">
            <label className={labelCls}>Active</label>
            <div className="flex items-center h-[34px]">
              <input
                type="checkbox"
                checked={!!value.is_active}
                onChange={(e) => onChange({ ...value, is_active: e.target.checked })}
              />
            </div>
          </td>

          {/* Service Start */}
          <td className="px-3 py-2">
            <label className={labelCls}>Service Start (Y/M)</label>
            <input
              type="month"
              lang="en"
              value={ymToInput(
                value.service_start_year ?? null,
                value.service_start_month ?? null
              )}
              onChange={(e) => {
                const { year, month } = inputToYM(e.target.value);
                onChange({
                  ...value,
                  service_start_year: year,
                  service_start_month: month,
                });
              }}
              className={inputCls}
            />
          </td>

          {/* Useful Life */}
          <td className="px-3 py-2">
            <label className={labelCls}>Useful Life (months)</label>
            <input
              type="text"
              inputMode="numeric"
              pattern="[0-9]*"
              value={localULife}
              onChange={(e) => setLocalULife(e.target.value)}
              onBlur={() => commitNum("useful_life_months", localULife)}
              onKeyDown={commitOnEnter(() => commitNum("useful_life_months", localULife))}
              className={inputRight}
              autoComplete="off"
            />
          </td>

          {/* Depreciation Method */}
          <td className="px-3 py-2">
            <label className={labelCls}>Depreciation</label>
            <select
              value={value.depr_method || "straight_line"}
              onChange={(e) => onChange({ ...value, depr_method: e.target.value })}
              className={inputCls}
            >
              <option value="straight_line">Straight-line</option>
              <option value="declining_balance">Declining balance</option>
            </select>
          </td>

          {/* Actions */}
          <td className="px-3 py-2 w-80">
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

                  <div className="ml-1 h-5 w-px bg-gray-300" />

                  <button
                    onClick={() => generateServiceFromCapex(value)}
                    disabled={saving || !value.id || !canGenerate}
                    title={!canGenerate ? "Enable Reward and set Return % > 0 first" : "Generate Service from CAPEX"}
                    className={cls(
                      "px-3 py-1 rounded text-white",
                      saving || !canGenerate
                        ? "bg-emerald-300"
                        : "bg-emerald-600 hover:bg-emerald-700"
                    )}
                  >
                    Generate → Service
                  </button>

                  <button
                    onClick={() => generateBoqFromCapex(value)}
                    disabled={saving || !value.id || !canGenerate}
                    title={!canGenerate ? "Enable Reward and set Return % > 0 first" : "Generate BOQ from CAPEX"}
                    className={cls(
                      "px-3 py-1 rounded text-white",
                      saving || !canGenerate
                        ? "bg-sky-300"
                        : "bg-sky-600 hover:bg-sky-700"
                    )}
                  >
                    Generate → BOQ
                  </button>
                </>
              )}
              <button
                onClick={() => setOpenAdv((p) => ({ ...p, [key]: !advOpen }))}
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
            <td colSpan={9} className="px-3 pb-4">
              <div className="grid grid-cols-1 md:grid-cols-3 gap-3 mt-2">
                {/* ====== Reward (Return) panel ====== */}
                <div className="md:col-span-3 border rounded p-3 bg-indigo-50/40">
                  <div className="flex items-center justify-between mb-2">
                    <div className="font-medium text-indigo-900">Return (Reward)</div>
                    <label className="flex items-center gap-2 text-sm text-indigo-900">
                      <input
                        type="checkbox"
                        checked={!!value.reward_enabled}
                        onChange={(e) => {
                          const enabled = e.target.checked;
                          let next: CapexRow = { ...value, reward_enabled: enabled };
                          if (enabled && (next.reward_pct == null || next.reward_pct === 0)) {
                            next = {
                              ...next,
                              reward_pct: scenario?.default_capex_reward_pct ?? next.reward_pct ?? null,
                            };
                            setLocalRewardPct(
                              next.reward_pct == null ? "" : String(next.reward_pct)
                            );
                          }
                          onChange(next);
                        }}
                      />
                      <span>Enable Reward</span>
                    </label>
                  </div>

                  <div className="grid grid-cols-1 md:grid-cols-4 gap-3">
                    <div>
                      <div className={labelCls}>Return Ratio (%)</div>
                      <input
                        type="text"
                        inputMode="decimal"
                        pattern="[0-9.,]*"
                        value={localRewardPct}
                        onChange={(e) => setLocalRewardPct(e.target.value)}
                        onBlur={() => commitNum("reward_pct", localRewardPct)}
                        onKeyDown={commitOnEnter(() => commitNum("reward_pct", localRewardPct))}
                        className={inputRight}
                        autoComplete="off"
                        disabled={!value.reward_enabled}
                        placeholder={
                          scenario?.default_capex_reward_pct != null
                            ? `Default ${scenario.default_capex_reward_pct}`
                            : "e.g. 15"
                        }
                      />
                    </div>

                    <div>
                      <div className={labelCls}>Spread</div>
                      <select
                        value={value.reward_spread_kind || "even"}
                        onChange={(e) => onChange({ ...value, reward_spread_kind: e.target.value })}
                        className={inputCls}
                        disabled={!value.reward_enabled}
                      >
                        <option value="even">Even</option>
                        {/* place for future kinds; backend validates */}
                      </select>
                    </div>

                    <div>
                      <div className={labelCls}>Term (months, override)</div>
                      <input
                        type="text"
                        inputMode="numeric"
                        pattern="[0-9]*"
                        value={localTermOverride}
                        onChange={(e) => setLocalTermOverride(e.target.value)}
                        onBlur={() => commitNum("term_months_override", localTermOverride)}
                        onKeyDown={commitOnEnter(() =>
                          commitNum("term_months_override", localTermOverride)
                        )}
                        className={inputRight}
                        autoComplete="off"
                        disabled={!value.reward_enabled}
                        placeholder="Optional"
                      />
                    </div>

                    <div className="flex items-end">
                      <div className="text-xs text-gray-600">
                        When enabled, backend converts CAPEX into a monthly revenue stream
                        (Excel parity). No FE math — server is the source of truth.
                      </div>
                    </div>
                  </div>
                </div>

                {/* ====== Regular Advanced fields ====== */}
                <div>
                  <div className={labelCls}>Disposal (Y/M)</div>
                  <input
                    type="month"
                    lang="en"
                    value={ymToInput(value.disposal_year ?? null, value.disposal_month ?? null)}
                    onChange={(e) => {
                      const { year, month } = inputToYM(e.target.value);
                      onChange({ ...value, disposal_year: year, disposal_month: month });
                    }}
                    className={inputCls}
                  />
                </div>

                <div>
                  <div className={labelCls}>Disposal Proceeds</div>
                  <input
                    type="text"
                    inputMode="decimal"
                    pattern="[0-9.,]*"
                    value={localDispProc}
                    onChange={(e) => setLocalDispProc(e.target.value)}
                    onBlur={() => commitNum("disposal_proceeds", localDispProc)}
                    onKeyDown={commitOnEnter(() => commitNum("disposal_proceeds", localDispProc))}
                    className={inputRight}
                    autoComplete="off"
                  />
                </div>

                <div className="flex items-end gap-2">
                  <input
                    type="checkbox"
                    checked={!!value.replace_at_end}
                    onChange={(e) => onChange({ ...value, replace_at_end: e.target.checked })}
                  />
                  <span className="text-sm text-gray-700">Replace at end</span>
                </div>

                <div>
                  <div className={labelCls}>Per Unit Cost</div>
                  <input
                    type="text"
                    inputMode="decimal"
                    pattern="[0-9.,]*"
                    value={localPerUnit}
                    onChange={(e) => setLocalPerUnit(e.target.value)}
                    onBlur={() => commitNum("per_unit_cost", localPerUnit)}
                    onKeyDown={commitOnEnter(() => commitNum("per_unit_cost", localPerUnit))}
                    className={inputRight}
                    autoComplete="off"
                  />
                </div>

                <div>
                  <div className={labelCls}>Quantity</div>
                  <input
                    type="text"
                    inputMode="numeric"
                    pattern="[0-9]*"
                    value={localQty}
                    onChange={(e) => setLocalQty(e.target.value)}
                    onBlur={() => commitNum("quantity", localQty)}
                    onKeyDown={commitOnEnter(() => commitNum("quantity", localQty))}
                    className={inputRight}
                    autoComplete="off"
                  />
                </div>

                <div>
                  <div className={labelCls}>Salvage Value</div>
                  <input
                    type="text"
                    inputMode="decimal"
                    pattern="[0-9.,]*"
                    value={localSalvage}
                    onChange={(e) => setLocalSalvage(e.target.value)}
                    onBlur={() => commitNum("salvage_value", localSalvage)}
                    onKeyDown={commitOnEnter(() => commitNum("salvage_value", localSalvage))}
                    className={inputRight}
                    autoComplete="off"
                  />
                </div>

                <div>
                  <div className={labelCls}>Contingency (%)</div>
                  <input
                    type="text"
                    inputMode="decimal"
                    pattern="[0-9.,]*"
                    value={localContPct}
                    onChange={(e) => setLocalContPct(e.target.value)}
                    onBlur={() => commitNum("contingency_pct", localContPct)}
                    onKeyDown={commitOnEnter(() => commitNum("contingency_pct", localContPct))}
                    className={inputRight}
                    autoComplete="off"
                  />
                </div>

                <div>
                  <div className={labelCls}>Partial Month Policy</div>
                  <select
                    value={value.partial_month_policy || "full_month"}
                    onChange={(e) =>
                      onChange({ ...value, partial_month_policy: e.target.value })
                    }
                    className={inputCls}
                  >
                    <option value="full_month">Full month</option>
                    <option value="half_month">Half month</option>
                    {/* backend expects "actual_days" for prorate */}
                    <option value="actual_days">Prorate (actual days)</option>
                  </select>
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
        <h3 className="font-semibold text-lg">CAPEX</h3>
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
            Mark CAPEX Ready → READY
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
          {/* Category öneri listesi */}
          <datalist id="capex-category-options">
            {categoryOptions.map((opt) => (
              <option key={opt} value={opt} />
            ))}
          </datalist>

          <table className="min-w-full text-sm">
            <thead className="bg-gray-50">
              <tr>
                <th className="px-3 py-2">Asset Name</th>
                <th className="px-3 py-2">Category</th>
                <th className="px-3 py-2 w-36">Spend (Y/M)</th>
                <th className="px-3 py-2 w-28 text-right">Amount</th>
                <th className="px-3 py-2 w-20">Active</th>
                <th className="px-3 py-2 w-36">Service Start</th>
                <th className="px-3 py-2 w-36 text-right">Useful Life</th>
                <th className="px-3 py-2 w-40">Depreciation</th>
                <th className="px-3 py-2 w-80">Actions</th>
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
            <tfoot>
              <tr className="bg-gray-100 font-semibold">
                <td className="px-3 py-2">Totals</td>
                <td className="px-3 py-2" colSpan={2} />
                <td className="px-3 py-2 text-right">
                  {total.toLocaleString(undefined, { maximumFractionDigits: 2 })}
                </td>
                <td className="px-3 py-2" colSpan={5} />
              </tr>
            </tfoot>
          </table>
        </div>
      )}
    </div>
  );
}
