// src/pages/BusinessCase.tsx
import { useCallback, useEffect, useMemo, useState, type ReactNode } from "react";
import { Link, useParams, useNavigate } from "react-router-dom";
import { apiGet, apiPost, ApiError } from "../lib/api";

/** ------------ Backend ile uyumlu tipler ------------ */
type ScenarioRow = {
  id: number;
  name: string;
  months: number;
  start_date: string; // ISO
};

type BusinessCaseDetail = {
  id: number;
  opportunity_id: number;
  name: string;
  scenarios: ScenarioRow[];
};

/** ------------ Sayfa ------------ */
export default function BusinessCasePage() {
  const { businessCaseId } = useParams<{ businessCaseId: string }>();
  const bcId = Number(businessCaseId);
  const navigate = useNavigate();

  const [data, setData] = useState<BusinessCaseDetail | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  // scenario modal
  const [open, setOpen] = useState(false);
  const [form, setForm] = useState<{ name: string; months: string; start_date: string }>(() => ({
    name: "",
    months: "36",
    start_date: firstDayOfThisMonthISO(),
  }));

  const isValid = useMemo(() => {
    const m = Number(form.months);
    return form.name.trim().length > 0 && Number.isFinite(m) && m > 0 && !!form.start_date;
  }, [form]);

  const fetchBC = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      // ✅ backend: /api/business-cases/{id}
      const payload = await apiGet<BusinessCaseDetail>(`/api/business-cases/${bcId}`);
      setData(payload);
    } catch (e: any) {
      const msg =
        (e instanceof ApiError && e.message) ||
        e?.response?.data?.detail ||
        e?.message ||
        "Load failed";
      setError(String(msg));
    } finally {
      setLoading(false);
    }
  }, [bcId]);

  useEffect(() => {
    if (!bcId || Number.isNaN(bcId)) {
      setError("Invalid business case id");
      setLoading(false);
      return;
    }
    fetchBC();
  }, [bcId, fetchBC]);

  const onNewScenario = () => {
    setForm({ name: "", months: "36", start_date: firstDayOfThisMonthISO() });
    setOpen(true);
  };

  const onSaveScenario = async () => {
    if (!data || !isValid) return;
    const body = {
      business_case_id: data.id,
      name: form.name.trim(),
      months: Number(form.months),
      start_date: form.start_date, // "YYYY-MM-DD"
    };
    try {
      // ✅ backend: POST /api/business-cases/scenarios
      await apiPost("/api/business-cases/scenarios", body);
      setOpen(false);
      await fetchBC(); // sadece listeyi yenile
    } catch (e: any) {
      alert(
        (e instanceof ApiError && e.message) ||
          e?.response?.data?.detail ||
          e?.message ||
          "Save failed",
      );
    }
  };

  const scenarios = useMemo(
    () => (data?.scenarios ?? []).slice().sort((a, b) => a.id - b.id),
    [data?.scenarios],
  );

  return (
    <div className="bg-white rounded-xl shadow p-6">
      {/* header */}
      <div className="flex flex-col sm:flex-row sm:items-center sm:justify-between gap-3 mb-4">
        <div>
          <h2 className="text-lg font-medium">Business Case</h2>
          <div className="text-sm text-gray-500">
            {businessCaseId ? (
              <>
                ID: <b>{businessCaseId}</b>
              </>
            ) : null}
            {data ? (
              <>
                {" "}
                • Name: <b>{data.name}</b> • Opportunity:{" "}
                <Link
                  to={`/deals/${data.opportunity_id}`}
                  className="text-indigo-600 hover:underline"
                >
                  #{data.opportunity_id}
                </Link>
              </>
            ) : null}
          </div>
        </div>
        <div className="flex flex-wrap gap-2">
          <button
            onClick={() => data && navigate(`/deals/${data.opportunity_id}`)}
            disabled={!data || loading}
            className="px-3 py-1.5 rounded-md border text-sm hover:bg-gray-50 disabled:opacity-50"
            title={data ? "Back to Opportunity" : "Loading…"}
          >
            Back to Opportunity
          </button>

          <button
            onClick={fetchBC}
            disabled={loading}
            className="px-3 py-1.5 rounded-md border text-sm hover:bg-gray-50 disabled:opacity-50"
          >
            Refresh
          </button>
          <button
            onClick={onNewScenario}
            disabled={loading}
            className="px-3 py-1.5 rounded-md bg-indigo-600 text-white text-sm hover:bg-indigo-500 disabled:opacity-50"
          >
            + New Scenario
          </button>
        </div>
      </div>

      {/* states */}
      {loading && <div className="text-sm text-gray-500">Loading business case…</div>}
      {error && <div className="text-sm text-red-600">Error: {error}</div>}

      {!loading && !error && data && (
        <>
          <SectionHeader title={`Scenarios (${scenarios.length})`} />
          {scenarios.length === 0 ? (
            <div className="text-sm text-gray-500">No scenarios yet. Add one.</div>
          ) : (
            <div className="overflow-x-auto">
              <table className="min-w-full text-sm">
                <thead>
                  <tr className="text-left border-b">
                    <th className="py-2 pr-4">Name</th>
                    <th className="py-2 pr-4">Months</th>
                    <th className="py-2 pr-4">Start Date</th>
                    <th className="py-2 pr-4 w-40 text-right">Actions</th>
                  </tr>
                </thead>
                <tbody>
                  {scenarios.map((s) => (
                    <tr key={s.id} className="border-b last:border-0">
                      <td className="py-2 pr-4 font-medium">{s.name}</td>
                      <td className="py-2 pr-4">{s.months}</td>
                      <td className="py-2 pr-4">{formatDate(s.start_date)}</td>
                      <td className="py-2 pr-4 text-right">
                        <Link
                          to={`/scenarios/${s.id}`}
                          className="px-2 py-1 rounded border hover:bg-gray-50"
                        >
                          Open
                        </Link>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </>
      )}

      {/* modal */}
      {open && (
        <Modal onClose={() => setOpen(false)} title="New Scenario">
          <div className="space-y-3">
            <Field label="Name">
              <input
                value={form.name}
                onChange={(e) => setForm((f) => ({ ...f, name: e.target.value }))}
                className="w-full px-3 py-2 rounded-md border text-sm"
                placeholder="Base Case"
                autoFocus
              />
            </Field>

            <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
              <Field label="Months">
                <input
                  type="number"
                  inputMode="numeric"
                  min={1}
                  step={1}
                  value={form.months}
                  onChange={(e) => setForm((f) => ({ ...f, months: e.target.value }))}
                  className="w-full px-3 py-2 rounded-md border text-sm"
                  placeholder="36"
                />
              </Field>
              <Field label="Start Date">
                <input
                  type="date"
                  value={form.start_date}
                  onChange={(e) => setForm((f) => ({ ...f, start_date: e.target.value }))}
                  className="w-full px-3 py-2 rounded-md border text-sm"
                />
              </Field>
            </div>
          </div>

          <div className="mt-5 flex justify-end gap-2">
            <button
              onClick={() => setOpen(false)}
              className="px-3 py-1.5 rounded-md border hover:bg-gray-50"
            >
              Cancel
            </button>
            <button
              disabled={!isValid}
              onClick={onSaveScenario}
              className="px-3 py-1.5 rounded-md bg-indigo-600 text-white disabled:opacity-50"
            >
              Save
            </button>
          </div>
        </Modal>
      )}
    </div>
  );
}

/** ------------ küçük UI yardımcıları ------------ */
function SectionHeader({ title, right }: { title: string; right?: ReactNode }) {
  return (
    <div className="flex items-center justify-between mt-6 mb-2">
      <h3 className="font-medium">{title}</h3>
      {right}
    </div>
  );
}

function Field({ label, children }: { label: string; children: ReactNode }) {
  return (
    <label className="block">
      <div className="text-xs text-gray-500 mb-1">{label}</div>
      {children}
    </label>
  );
}

function Modal({
  title,
  children,
  onClose,
}: {
  title: string;
  children: ReactNode;
  onClose: () => void;
}) {
  return (
    <div className="fixed inset-0 bg-black/30 flex items-center justify-center z-50">
      <div className="bg-white w-[760px] max-w-[95vw] rounded-xl shadow p-5 relative">
        <div className="text-lg font-semibold mb-4">{title}</div>
        {children}
        <button
          onClick={onClose}
          className="absolute top-2 right-2 rounded-md px-2 py-1 text-sm text-gray-500 hover:bg-gray-100"
          aria-label="Close"
        >
          ✕
        </button>
      </div>
    </div>
  );
}

/** ------------ utils ------------ */
function formatDate(iso: string) {
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return iso;
  return d.toISOString().slice(0, 10);
}

function firstDayOfThisMonthISO() {
  const now = new Date();
  const d = new Date(Date.UTC(now.getFullYear(), now.getMonth(), 1));
  return d.toISOString().slice(0, 10);
}
