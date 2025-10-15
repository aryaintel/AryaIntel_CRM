// frontend/src/components/engine/useEngineFacts.ts
import { useEffect, useState } from "react";
import { getEngineFacts, type EngineFactsResponse } from "../../api/engine";

export type Row = { yyyymm: number; value: number };

export type UseFactsData = {
  scenario_id: number;
  category?: string | null;
  sheets: Record<string, Row[]>;
};

type Args = {
  scenarioId: number;
  category?: string;
  sheets?: string[];
  yyyymmFrom?: number;
  yyyymmTo?: number;
};

export function useEngineFacts({
  scenarioId,
  category,
  sheets = [],
  yyyymmFrom,
  yyyymmTo,
}: Args) {
  const [data, setData] = useState<UseFactsData | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<unknown>(null);

  useEffect(() => {
    let abort = false;

    async function run() {
      setLoading(true);
      setError(null);
      const out: UseFactsData = { scenario_id: scenarioId, category, sheets: {} };

      try {
        for (const sheet of sheets) {
          try {
            const res: EngineFactsResponse = await getEngineFacts({
              scenario_id: scenarioId,
              sheet,
              category,
              latest: true,
              yyyymm_from: yyyymmFrom,
              yyyymm_to: yyyymmTo,
            });
            out.sheets[sheet] = (res.rows || []).map((r) => ({
              yyyymm: r.yyyymm,
              value: r.value,
            }));
          } catch (e: any) {
            // 404: "No data found to resolve latest run" => boş say
            if (e instanceof Error && e.message.startsWith("API 404")) {
              out.sheets[sheet] = [];
              continue;
            }
            // diğer hatalar: gerçekten error
            throw e;
          }
        }

        if (!abort) setData(out);
      } catch (e) {
        if (!abort) setError(e);
      } finally {
        if (!abort) setLoading(false);
      }
    }

    if (sheets.length > 0) run();
    else setData({ scenario_id: scenarioId, category, sheets: {} });

    return () => {
      abort = true;
    };
  }, [scenarioId, category, yyyymmFrom, yyyymmTo, JSON.stringify(sheets)]);

  return { data, loading, error };
}
