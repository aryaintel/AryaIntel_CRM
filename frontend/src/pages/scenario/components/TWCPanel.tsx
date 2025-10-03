// frontend/src/pages/scenario/tabs/TWCTab.tsx
import type React from "react";
import { useEffect, useMemo, useState } from "react";
import { apiGet, apiPut, apiPost } from "../../../lib/api";

type Props = {
  scenarioId: number;
  onMarkedReady?: () => void; // workflow ilerletildiğinde çağrılır
};

type TWCIn = {
  twc_dso_days?: number | string | null;
  twc_dpo_days?: number | string | null;
  twc_dio_days?: number | string | null;
  twc_freight_pct_of_sales?: number | string | null;
  twc_safety_stock_pct_cogs?: number | string | null;
  twc_other_wc_fixed?: number | string | null;
};
type TWCOut = TWCIn & { scenario_id: number };

type TWCBucket = {
  year: number;
  month: number;
  revenue: number;
  cogs: number;
  freight: number;
  ar: number;
  ap: number;
  inv: number;
  nwc: number;
};
type TWCPreview = {
  scenario_id: number;
  assumptions: TWCOut;
  monthly: TWCBucket[];
  totals: Record<string, number>;
};

function numOrNull(v: any): number | null {
  if (v === "" || v === null || v === undefined) return null;
  const n = Number(v);
  return Number.isFinite(n) ? n : null;
}
function clamp(v: number | null, min: number, max: number): number | null {
  if (v === null) return null;
  return Math.max(min, Math.min(max, v));
}
function cls(...a: (string | false | undefined)[]) {
  return a.filter(Boolean).join(" ");
}

// null güvenli birleştirme — state yoksa default’la başlatır
function mergeTWC(current: TWCOut | null, patch: Partial<TWCOut>, scenarioId: number): TWCOut {
  const base: TWCOut = {
    scenario_id: scenarioId,
    twc_dso_days: 45,
    twc_dpo_days: 30,
    twc_dio_days: 20,
    twc_freight_pct_of_sales: 0,
    twc_safety_stock_pct_cogs: 0,
    twc_other_wc_fixed: 0,
  };
  return { ...(current ?? base), ...patch };
}

export default function TWCTab({ scenarioId, onMarkedReady }: Props) {
  const [twc, setTwc] = useState<TWCOut | null>(null);
  const [pv, setPv] = useState<TWCPreview | null>(null);
  const [loading, setLoading] = useState(true);
  const [err, setErr] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);
  const [useBoqFreight, setUseBoqFreight] = useState(true);

  async function load() {
    setLoading(true);
    setErr(null);
    try {
      const data = await apiGet<TWCOut>(`/scenarios/${scenarioId}/twc`);
      setTwc(data);
    } catch (e: any) {
      // Eğer 404 ise default değerlerle ekranda başlat (backend ilk PUT ile oluşturacak)
      if (e?.response?.status === 404) {
        setTwc(mergeTWC(null, {}, scenarioId));
      } else {
        setErr(e?.message || "Failed to load TWC.");
      }
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    if (scenarioId) load();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [scenarioId]);

  async function save() {
    if (!twc) return;
    setSaving(true);
    setErr(null);
    try {
      // günler 0–365, yüzdeler 0–100, other_wc_fixed ≥ 0
      const payload: TWCIn = {
        twc_dso_days: clamp(numOrNull(twc.twc_dso_days), 0, 365),
        twc_dpo_days: clamp(numOrNull(twc.twc_dpo_days), 0, 365),
        twc_dio_days: clamp(numOrNull(twc.twc_dio_days), 0, 365),
        twc_freight_pct_of_sales: clamp(numOrNull(twc.twc_freight_pct_of_sales), 0, 100),
        twc_safety_stock_pct_cogs: clamp(numOrNull(twc.twc_safety_stock_pct_cogs), 0, 100),
        twc_other_wc_fixed: Math.max(0, numOrNull(twc.twc_other_wc_fixed) ?? 0),
      };
      const res = await apiPut<TWCOut>(`/scenarios/${scenarioId}/twc`, payload);
      setTwc(res);
      alert("TWC saved.");
    } catch (e: any) {
      setErr(e?.response?.data?.detail || e?.message || "Save failed.");
    } finally {
      setSaving(false);
    }
  }

  async function preview() {
    setErr(null);
    try {
      const res = await apiPost<TWCPreview>(
        `/scenarios/${scenarioId}/twc/preview?use_boq_freight=${useBoqFreight ? "true" : "false"}`,
        {}
      );
      setPv(res);
    } catch (e: any) {
      setPv(null);
      setErr(e?.response?.data?.detail || e?.message || "Preview failed.");
    }
  }

  async function markReady() {
    if (!confirm("Mark TWC as ready and move to CAPEX?")) return;
    try {
      await apiPost(`/scenarios/${scenarioId}/workflow/mark-twc-ready`, {});
      alert("Workflow moved to CAPEX.");
      onMarkedReady?.();
    } catch (e: any) {
      alert(e?.response?.data?.detail || e?.message || "Cannot mark TWC as ready.");
    }
  }

  const totalsFmt = useMemo(() => {
    const t = pv?.totals || {};
    const f = (x: any) => (typeof x === "number" ? x.toLocaleString() : (x ?? 0));
    return {
      revenue: f(t["revenue"]),
      cogs: f(t["cogs"]),
      freight: f(t["freight"]),
      ar: f(t["ar"]),
      ap: f(t["ap"]),
      inv: f(t["inv"]),
      nwc: f(t["nwc"]),
    };
  }, [pv]);

  return (
    <div className="space-y-3">
      <div className="flex items-center justify-between">
        <h3 className="font-semibold text-lg">TWC Assumptions</h3>
        <div className="flex flex-wrap gap-2 items-center">
          <label className="flex items-center gap-2 text-sm mr-2">
            <input
              type="checkbox"
              checked={useBoqFreight}
              onChange={(e) => setUseBoqFreight(e.target.checked)}
            />
            Use BOQ freight in preview
          </label>
          <button onClick={load} className="px-3 py-1 rounded bg-gray-100 hover:bg-gray-200">
            Refresh
          </button>
          <button
            onClick={save}
            disabled={saving}
            className="px-3 py-1 rounded bg-indigo-600 text-white hover:bg-indigo-700 disabled:opacity-50"
          >
            {saving ? "Saving…" : "Save"}
          </button>
          <button onClick={preview} className="px-3 py-1 rounded bg-gray-100 hover:bg-gray-200">
            Preview NWC
          </button>
          <button
            onClick={markReady}
            className="px-3 py-1 rounded bg-emerald-600 text-white hover:bg-emerald-700"
          >
            Mark TWC Ready → CAPEX
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
        <>
          {/* Inputs */}
          <div className="grid grid-cols-2 md:grid-cols-3 gap-3">
            <Field label="DSO (days)">
              <Input
                type="number"
                min={0}
                max={365}
                value={twc?.twc_dso_days ?? 45}
                onChange={(e: React.ChangeEvent<HTMLInputElement>) =>
                  setTwc((p) => mergeTWC(p, { twc_dso_days: e.target.value }, scenarioId))
                }
              />
            </Field>
            <Field label="DPO (days)">
              <Input
                type="number"
                min={0}
                max={365}
                value={twc?.twc_dpo_days ?? 30}
                onChange={(e: React.ChangeEvent<HTMLInputElement>) =>
                  setTwc((p) => mergeTWC(p, { twc_dpo_days: e.target.value }, scenarioId))
                }
              />
            </Field>
            <Field label="DIO (days)">
              <Input
                type="number"
                min={0}
                max={365}
                value={twc?.twc_dio_days ?? 20}
                onChange={(e: React.ChangeEvent<HTMLInputElement>) =>
                  setTwc((p) => mergeTWC(p, { twc_dio_days: e.target.value }, scenarioId))
                }
              />
            </Field>

            <Field label="Freight (% of sales)">
              <Input
                type="number"
                min={0}
                max={100}
                step="0.01"
                value={twc?.twc_freight_pct_of_sales ?? 0}
                onChange={(e: React.ChangeEvent<HTMLInputElement>) =>
                  setTwc((p) =>
                    mergeTWC(p, { twc_freight_pct_of_sales: e.target.value }, scenarioId)
                  )
                }
              />
            </Field>
            <Field label="Safety Stock (% of COGS)">
              <Input
                type="number"
                min={0}
                max={100}
                step="0.01"
                value={twc?.twc_safety_stock_pct_cogs ?? 0}
                onChange={(e: React.ChangeEvent<HTMLInputElement>) =>
                  setTwc((p) =>
                    mergeTWC(p, { twc_safety_stock_pct_cogs: e.target.value }, scenarioId)
                  )
                }
              />
            </Field>
            <Field label="Other WC (fixed)">
              <Input
                type="number"
                min={0}
                step="0.01"
                value={twc?.twc_other_wc_fixed ?? 0}
                onChange={(e: React.ChangeEvent<HTMLInputElement>) =>
                  setTwc((p) => mergeTWC(p, { twc_other_wc_fixed: e.target.value }, scenarioId))
                }
              />
            </Field>
          </div>

          {/* Preview */}
          {pv && (
            <div className="mt-3">
              <h4 className="font-medium mb-2">Preview (Monthly)</h4>
              <div className="overflow-x-auto border rounded">
                <table className="min-w-full text-sm">
                  <thead className="bg-gray-50">
                    <tr>
                      <th className="px-3 py-2">Y/M</th>
                      <th className="px-3 py-2 text-right">Revenue</th>
                      <th className="px-3 py-2 text-right">COGS</th>
                      <th className="px-3 py-2 text-right">Freight</th>
                      <th className="px-3 py-2 text-right">AR</th>
                      <th className="px-3 py-2 text-right">AP</th>
                      <th className="px-3 py-2 text-right">INV</th>
                      <th className="px-3 py-2 text-right">NWC</th>
                    </tr>
                  </thead>
                  <tbody>
                    {pv.monthly.map((b, i) => (
                      <tr key={i} className="odd:bg-white even:bg-gray-50">
                        <td className="px-3 py-2">
                          {b.year}/{String(b.month).padStart(2, "0")}
                        </td>
                        <td className="px-3 py-2 text-right">{b.revenue.toLocaleString()}</td>
                        <td className="px-3 py-2 text-right">{b.cogs.toLocaleString()}</td>
                        <td className="px-3 py-2 text-right">{b.freight.toLocaleString()}</td>
                        <td className="px-3 py-2 text-right">{b.ar.toLocaleString()}</td>
                        <td className="px-3 py-2 text-right">{b.ap.toLocaleString()}</td>
                        <td className="px-3 py-2 text-right">{b.inv.toLocaleString()}</td>
                        <td className="px-3 py-2 text-right">{b.nwc.toLocaleString()}</td>
                      </tr>
                    ))}
                  </tbody>
                  <tfoot>
                    <tr className="bg-gray-100 font-semibold">
                      <td className="px-3 py-2">Totals</td>
                      <td className="px-3 py-2 text-right">{totalsFmt.revenue}</td>
                      <td className="px-3 py-2 text-right">{totalsFmt.cogs}</td>
                      <td className="px-3 py-2 text-right">{totalsFmt.freight}</td>
                      <td className="px-3 py-2 text-right">{totalsFmt.ar}</td>
                      <td className="px-3 py-2 text-right">{totalsFmt.ap}</td>
                      <td className="px-3 py-2 text-right">{totalsFmt.inv}</td>
                      <td className="px-3 py-2 text-right">{totalsFmt.nwc}</td>
                    </tr>
                  </tfoot>
                </table>
              </div>
            </div>
          )}
        </>
      )}
    </div>
  );
}

/* ---- Small UI bits ---- */
function Field({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <label className="text-sm">
      <div className="text-gray-600 mb-1">{label}</div>
      {children}
    </label>
  );
}
function Input(props: any) {
  return (
    <input
      {...props}
      className={cls(
        "w-full px-2 py-1 rounded border border-gray-300 focus:outline-none focus:ring",
        props.className
      )}
    />
  );
}
