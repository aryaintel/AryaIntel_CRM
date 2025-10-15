import React, { useMemo } from "react";
import { useEngineFacts, type Row } from "./useEngineFacts";

type Props = {
  scenarioId: number;
  category?: string; // default "AN"
  sheets?: string[]; // default common AN sheets
  yyyymmFrom?: number;
  yyyymmTo?: number;
  className?: string;
};

/**
 * Displays persisted engine base series (no escalation/FX/tax) in a compact grid.
 */
export default function EngineFactsGrid({
  scenarioId,
  category = "AN",
  sheets = ["c.Sales-AN","oA.Finance-AN.Revenue","oA.Finance-AN.COGS","oA.Finance-AN.GP"],
  yyyymmFrom,
  yyyymmTo,
  className
}: Props) {
  const { data, loading, error } = useEngineFacts({ scenarioId, category, sheets, yyyymmFrom, yyyymmTo });

  const months = useMemo(() => {
    const set = new Set<number>();
    const dict = data?.sheets ?? {};
    Object.values(dict).forEach((rows: Row[]) => {
      rows.forEach((r: Row) => set.add(r.yyyymm));
    });
    return Array.from(set).sort((a, b) => a - b);
  }, [data?.sheets]);

  if (loading) return <div className={className}>Loading engine facts…</div>;
  if (error)   return <div className={className}>Error: {String(error)}</div>;
  if (!data || !data.sheets || Object.keys(data.sheets).length === 0) {
    return <div className={className}>No engine facts found (persist first).</div>;
  }

  return (
    <div className={`overflow-auto rounded-xl border p-3 ${className ?? ""}`}>
      <table className="min-w-full text-sm">
        <thead>
          <tr>
            <th className="text-left sticky left-0 bg-white">Sheet</th>
            {months.map((m) => (
              <th key={m} className="text-right px-2">{formatYM(m)}</th>
            ))}
          </tr>
        </thead>
        <tbody>
          {Object.entries(data.sheets).map(([sheet, rows]) => {
            const map = new Map<number, number>();
            (rows as Row[]).forEach((r) => map.set(r.yyyymm, r.value));
            return (
              <tr key={sheet} className="border-t">
                <td className="font-medium sticky left-0 bg-white pr-3">{sheet}</td>
                {months.map((m) => (
                  <td key={m} className="text-right px-2">{formatNumber(map.get(m))}</td>
                ))}
              </tr>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}

function formatNumber(v?: number) {
  if (v == null) return "—";
  try { return new Intl.NumberFormat(undefined, { maximumFractionDigits: 2 }).format(v); }
  catch { return String(v); }
}
function formatYM(yyyymm: number) {
  const y = Math.floor(yyyymm / 100), m = yyyymm % 100;
  const d = new Date(y, m - 1, 1);
  return d.toLocaleDateString(undefined, { year: "numeric", month: "2-digit" });
}
