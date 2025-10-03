// frontend/src/pages/scenario/tabs/TWCTab.tsx
import type React from "react";
import { useEffect, useMemo, useState } from "react";
import { apiGet, apiPut, apiPost } from "../../../lib/api";

type Props = {
  scenarioId: number;
  onMarkedReady?: () => void; // workflow ilerletildiğinde çağrılır
};

type TWCIn = {
  twc_dso_days?: number | string;
  twc_dpo_days?: number | string;
  twc_dio_days?: number | string;
  twc_freight_pct_of_sales?: number | string;
  twc_safety_stock_pct_cogs?: number | string;
  twc_other_wc_fixed?: number | string;
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

function num(v: any): number {
  const n = Number(v);
  return Number.isFinite(n) ? n : 0;
}
function cls(...a: (string | false | undefined)[]) {
  return a.filter(Boolean).join(" ");
}

// Number formatter: en-US locale, 2 decimals
const fmt2 = new Intl.NumberFormat("en-US", {
  minimumFractionDigits: 2,
  maximumFractionDigits: 2,
});
const f2 = (x: any): string => {
  const n = Number(x);
  return Number.isFinite(n) ? fmt2.format(n) : "0.00";
};

// null güvenli birleştirme — TWC state’i yoksa default’la başlatır
function mergeTWC(
  current: TWCOut | null,
  patch: Partial<TWCOut>,
  scenarioId: number
): TWCOut {
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

  async function load() {
    setLoading(true);
    setErr(null);
    try {
      const data = await apiGet<TWCOut>(`/scenarios/${scenarioId}/twc`);
      setTwc(data);
    } catch (e: any) {
      setErr(e?.message || "Failed to load TWC.");
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
      const payload: TWCIn = {
        twc_dso_days: num(twc.twc_dso_days),
        twc_dpo_days: num(twc.twc_dpo_days),
        twc_dio_days: num(twc.twc_dio_days),
        twc_freight_pct_of_sales: num(twc.twc_freight_pct_of_sales),
        twc_safety_stock_pct_cogs: num(twc.twc_safety_stock_pct_cogs),
        twc_other_wc_fixed: num(twc.twc_other_wc_fixed),
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
      const res = await apiPost<TWCPreview>(`/scenarios/${scenarioId}/twc/preview`, {});
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
    return {
      revenue: f2(t["revenue"]),
      cogs: f2(t["cogs"]),
      freight: f2(t["freight"]),
      ar: f2(t["ar"]),
      ap: f2(t["ap"]),
      inv: f2(t["inv"]),
      nwc: f2(t["nwc"]),
    };
  }, [pv]);

  return (
    <div className="space-y-3">
      <div className="flex items-center justify-between">
        <h3 className="font-semibold text-lg">TWC Assumptions</h3>
        <div className="flex gap-2">
          <button
            onClick={load}
            className="px-3 py-1.5 rounded-md border text-sm hover:bg-gray-50"
          >
            Refresh
          </button>
          <button
            onClick={save}
            disabled={saving}
            className="px-3 py-1.5 rounded-md bg-indigo-600 text-white text-sm hover:bg-indigo-500 disabled:opacity-50"
          >
            Save
          </button>
          <button
            onClick={preview}
            className="px-3 py-1.5 rounded-md border text-sm hover:bg-gray-50"
          >
            Preview NWC
          </button>
          <button
            onClick={markReady}
            className="px-3 py-1.5 rounded-md bg-indigo-600 text-white text-sm hover:bg-indigo-500"
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
                lang="en-US"
                value={twc?.twc_dso_days ?? 45}
                onChange={(e: React.ChangeEvent<HTMLInputElement>) =>
                  setTwc((p) => mergeTWC(p, { twc_dso_days: e.target.value }, scenarioId))
                }
              />
            </Field>
            <Field label="DPO (days)">
              <Input
                type="number"
                lang="en-US"
                value={twc?.twc_dpo_days ?? 30}
                onChange={(e: React.ChangeEvent<HTMLInputElement>) =>
                  setTwc((p) => mergeTWC(p, { twc_dpo_days: e.target.value }, scenarioId))
                }
              />
            </Field>
            <Field label="DIO (days)">
              <Input
                type="number"
                lang="en-US"
                value={twc?.twc_dio_days ?? 20}
                onChange={(e: React.ChangeEvent<HTMLInputElement>) =>
                  setTwc((p) => mergeTWC(p, { twc_dio_days: e.target.value }, scenarioId))
                }
              />
            </Field>

            <Field label="Freight (% of sales)">
              <Input
                type="number"
                lang="en-US"
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
                lang="en-US"
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
                lang="en-US"
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
                        <td className="px-3 py-2 text-right">{f2(b.revenue)}</td>
                        <td className="px-3 py-2 text-right">{f2(b.cogs)}</td>
                        <td className="px-3 py-2 text-right">{f2(b.freight)}</td>
                        <td className="px-3 py-2 text-right">{f2(b.ar)}</td>
                        <td className="px-3 py-2 text-right">{f2(b.ap)}</td>
                        <td className="px-3 py-2 text-right">{f2(b.inv)}</td>
                        <td className="px-3 py-2 text-right">{f2(b.nwc)}</td>
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
