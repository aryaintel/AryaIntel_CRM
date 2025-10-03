// src/pages/OpportunityDetail.tsx
import { useEffect, useMemo, useState } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";
import { apiGet, apiPost, ApiError } from "../lib/api";

type Opportunity = {
  id: number;
  tenant_id: number;
  account_id: number;
  account_name?: string | null;
  owner_id: number;
  owner_email?: string | null;

  name: string;
  amount?: number | null;
  currency?: string | null;
  stage_id: number;

  expected_close_date?: string | null;
  source?: string | null;

  created_at?: string | null;
  updated_at?: string | null;

  /** 1:1 Business Case bağı (bazı kayıtlarda null dönebilir) */
  business_case_id?: number | null;
};

// /deals/stages -> { id, no, name }
type StageRow = { id: number; no: number; name: string };

type ScenarioRow = {
  id: number;
  name: string;
  months: number;
  start_date: string; // ISO
};

type BusinessCaseOut = {
  id: number;
  opportunity_id: number;
  name: string;
  scenarios?: ScenarioRow[];
};

export default function OpportunityDetailPage() {
  const { id } = useParams<{ id: string }>();
  const navigate = useNavigate();

  const [opp, setOpp] = useState<Opportunity | null>(null);
  const [stages, setStages] = useState<StageRow[]>([]);
  const [loading, setLoading] = useState(true);
  const [err, setErr] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  // Business Case + senaryolar
  const [bc, setBc] = useState<BusinessCaseOut | null>(null);
  const [bcLoading, setBcLoading] = useState(false);

  // NEW — Scenario create modal state
  const [openScenario, setOpenScenario] = useState(false);
  const [savingScenario, setSavingScenario] = useState(false);
  const [scenarioForm, setScenarioForm] = useState<{ name: string; months: string; start_date: string }>(() => ({
    name: "",
    months: "36",
    start_date: firstDayOfThisMonthISO(),
  }));
  const scenarioValid =
    scenarioForm.name.trim().length > 0 &&
    Number(scenarioForm.months) > 0 &&
    !!scenarioForm.start_date;

  const currentStage = useMemo(
    () => (opp ? stages.find((s) => s.id === opp.stage_id) : undefined),
    [opp, stages]
  );

  // BC detayını id ile çek
  const fetchBC = async (bcId: number) => {
    setBcLoading(true);
    try {
      const data = await apiGet<BusinessCaseOut>(`/business-cases/${bcId}`);
      setBc(data ?? null);
    } catch {
      setBc(null);
    } finally {
      setBcLoading(false);
    }
  };

  // Opp üzerinden BC bul (opp.business_case_id gelmese bile)
  const fetchBCByOpp = async (oppId: number) => {
    setBcLoading(true);
    try {
      const data = await apiGet<BusinessCaseOut>(
        `/business-cases/by-opportunity/${oppId}`
      );
      setBc(data ?? null);
      // Opp objesini bc id ile zenginleştir
      setOpp((prev) =>
        prev ? { ...prev, business_case_id: data.id } : prev
      );
    } catch {
      setBc(null);
    } finally {
      setBcLoading(false);
    }
  };

  const fetchAll = async () => {
    if (!id) return;
    setLoading(true);
    setErr(null);
    try {
      const [data, st] = await Promise.all([
        apiGet<Opportunity>(`/deals/${id}`),
        apiGet<StageRow[]>(`/deals/stages`),
      ]);
      setOpp(data);
      setStages(Array.isArray(st) ? st : []);

      // Önce opp üzerinde bcId varsa onunla çek, yoksa opp'tan dene
      if (data?.business_case_id) {
        await fetchBC(Number(data.business_case_id));
      } else {
        await fetchBCByOpp(data.id).catch(() => setBc(null));
      }
    } catch (e: any) {
      const msg =
        (e instanceof ApiError && e.message) ||
        e?.response?.data?.detail ||
        e?.message ||
        "Failed to load opportunity";
      setErr(String(msg));
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    fetchAll();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [id]);

  /** Create Business Case — varsa 409'u sessizce karşıla, mevcut BC'yi yükle */
  const onCreateBusinessCase = async () => {
    if (!opp) return;
    try {
      setBusy(true);

      // Zaten biliyorsak bu sayfada güncelleyelim
      if (opp.business_case_id) {
        await fetchBC(Number(opp.business_case_id));
        return;
      }

      // Oluşturmayı dene
      await apiPost<BusinessCaseOut>("/business-cases/", {
        opportunity_id: opp.id,
        name: `${opp.name} BC`,
      });

      // Oluşturuldu -> bu sayfada gösterelim
      await fetchBCByOpp(opp.id);
    } catch (e) {
      // 409: zaten var -> mevcut BC'yi çek ve göster
      if (e instanceof ApiError && e.status === 409) {
        await fetchBCByOpp(opp.id);
        return;
      }
      alert(
        (e instanceof ApiError && e.message) ||
          (e as any)?.response?.data?.detail ||
          (e as any)?.message ||
          "Failed to create Business Case"
      );
    } finally {
      setBusy(false);
    }
  };

  // NEW — open scenario modal
  const onNewScenario = () => {
    setScenarioForm({ name: "", months: "36", start_date: firstDayOfThisMonthISO() });
    setOpenScenario(true);
  };

  // NEW — save scenario for current BC
  const onSaveScenario = async () => {
    if (!bc?.id || !scenarioValid || savingScenario) return;
    const body = {
      business_case_id: bc.id,
      name: scenarioForm.name.trim(),
      months: Number(scenarioForm.months),
      start_date: scenarioForm.start_date, // "YYYY-MM-DD"
    };
    try {
      setSavingScenario(true);
      await apiPost("/business-cases/scenarios", body);
      setOpenScenario(false);
      await fetchBC(bc.id); // listeyi tazele
    } catch (e: any) {
      if (e instanceof ApiError && e.status === 409) {
        alert("Scenario name must be unique per business case.");
      } else {
        alert(
          (e instanceof ApiError && e.message) ||
            e?.response?.data?.detail ||
            e?.message ||
            "Failed to create scenario"
        );
      }
    } finally {
      setSavingScenario(false);
    }
  };

  const onViewBC = () => {
    if (bc?.id) navigate(`/business-cases/${bc.id}`);
  };
  const onEditBC = () => {
    if (bc?.id) navigate(`/business-cases/${bc.id}?edit=1`);
  };

  const shownBusinessCaseId = bc?.id ?? opp?.business_case_id ?? null;

  return (
    <div className="space-y-4">
      {/* Header (sadece navigasyon + geri dön) */}
      <div className="flex items-center justify-between">
        <div className="space-y-1">
          <div className="text-xs text-gray-500">
            <Link to="/deals" className="hover:underline">
              Opportunities
            </Link>{" "}
            / <span>Detail</span>
          </div>
          <h1 className="text-xl font-semibold">
            {opp?.name ?? (loading ? "Loading…" : "Opportunity")}
          </h1>
        </div>
        <div className="flex gap-2">
          <button
            onClick={() => navigate("/deals")}
            className="px-3 py-1.5 rounded-md border text-sm hover:bg-gray-50"
          >
            Back to list
          </button>
        </div>
      </div>

      {/* States */}
      {loading && <div className="text-sm text-gray-500">Loading opportunity…</div>}
      {err && <div className="text-sm text-red-600">Error: {err}</div>}

      {/* Üst detaylar */}
      {!loading && !err && opp && (
        <>
          <div className="grid grid-cols-1 lg:grid-cols-3 gap-4">
            {/* LEFT — Pipeline + Overview */}
            <div className="lg:col-span-2 space-y-4">
              {/* Pipeline */}
              <div className="bg-white rounded-xl shadow p-5">
                <div className="text-lg font-medium mb-4">Pipeline</div>
                <PipelineArrows stages={stages} currentStageId={opp.stage_id} />
              </div>

              {/* Overview */}
              <div className="bg-white rounded-xl shadow p-5">
                <div className="text-lg font-medium mb-4">Overview</div>

                <div className="grid grid-cols-1 md:grid-cols-2 gap-4 text-sm">
                  <KV label="Account" value={opp.account_name ?? opp.account_id} />
                  <KV label="Owner" value={opp.owner_email ?? opp.owner_id} />
                  <KV
                    label="Amount"
                    value={
                      opp.amount != null
                        ? `${opp.currency ? `${opp.currency} ` : ""}${opp.amount.toLocaleString()}`
                        : "—"
                    }
                  />
                  <KV label="Currency" value={opp.currency ?? "—"} />
                  <KV
                    label="Expected Close"
                    value={
                      opp.expected_close_date
                        ? new Date(opp.expected_close_date).toLocaleDateString()
                        : "—"
                    }
                  />
                  <KV label="Source" value={opp.source ?? "—"} />
                </div>
              </div>
            </div>

            {/* RIGHT — Opportunity Info */}
            <div className="bg-white rounded-xl shadow p-5">
              <div className="text-lg font-medium mb-4">Opportunity Info</div>
              <div className="text-sm space-y-2">
                <KV label="Stage" value={currentStage?.name ?? "—"} />
                <KV
                  label="Created"
                  value={opp.created_at ? new Date(opp.created_at).toLocaleString() : "—"}
                />
                <KV
                  label="Updated"
                  value={opp.updated_at ? new Date(opp.updated_at).toLocaleString() : "—"}
                />
                <KV label="Opportunity ID" value={String(opp.id)} />
                <KV
                  label="Business Case"
                  value={
                    shownBusinessCaseId ? (
                      <Link
                        to={`/business-cases/${shownBusinessCaseId}`}
                        className="text-indigo-600 hover:underline"
                      >
                        #{shownBusinessCaseId}
                      </Link>
                    ) : (
                      "—"
                    )
                  }
                />
              </div>
            </div>
          </div>

          {/* ALT — Business Case & Scenarios */}
          <div className="bg-white rounded-xl shadow p-5">
            <div className="flex items-center justify-between mb-3">
              <div className="text-lg font-medium">
                Business Case &amp; Scenarios{" "}
                {bc ? <span className="text-gray-500">— {bc.name}</span> : null}
              </div>
              <div className="flex gap-2">
                {/* CREATE yalnızca BC YOKSA görünür */}
                {!bc?.id && (
                  <button
                    onClick={onCreateBusinessCase}
                    disabled={busy || !opp}
                    className="px-3 py-1.5 rounded-md bg-indigo-600 text-white text-sm hover:bg-indigo-500 disabled:opacity-50"
                  >
                    Create Business Case
                  </button>
                )}
                {/* BC varsa View / Edit / NEW SCENARIO */}
                {bc?.id && (
                  <>
                    <button
                      onClick={onViewBC}
                      className="px-3 py-1.5 rounded-md border text-sm hover:bg-gray-50"
                    >
                      View Business Case
                    </button>
                    <button
                      onClick={onEditBC}
                      className="px-3 py-1.5 rounded-md border text-sm hover:bg-gray-50"
                    >
                      Edit Business Case
                    </button>
                    <button
                      onClick={onNewScenario}
                      className="px-3 py-1.5 rounded-md bg-indigo-600 text-white text-sm hover:bg-indigo-500"
                    >
                      + New Scenario
                    </button>
                  </>
                )}
              </div>
            </div>

            {/* İçerik */}
            {!bc?.id ? (
              <div className="text-sm text-gray-500">
                There is no business case for this opportunity yet. Use{" "}
                <b>Create Business Case</b> to create one.
              </div>
            ) : bcLoading ? (
              <div className="text-sm text-gray-500">Loading scenarios…</div>
            ) : !bc.scenarios || bc.scenarios.length === 0 ? (
              <div className="text-sm text-gray-500">No scenarios yet. Use <b>+ New Scenario</b>.</div>
            ) : (
              <div className="overflow-x-auto">
                <table className="min-w-full text-sm">
                  <thead>
                    <tr className="text-left border-b">
                      <th className="py-2 pr-4">Name</th>
                      <th className="py-2 pr-4">Start</th>
                      <th className="py-2 pr-4">Months</th>
                      <th className="py-2 pr-4 w-48 text-right">Actions</th>
                    </tr>
                  </thead>
                  <tbody>
                    {bc.scenarios.map((s) => (
                      <tr key={s.id} className="border-b last:border-0">
                        <td className="py-2 pr-4 font-medium">{s.name}</td>
                        <td className="py-2 pr-4">{formatDate(s.start_date)}</td>
                        <td className="py-2 pr-4">{s.months}</td>
                        <td className="py-2 pr-4 text-right">
                          <Link
                            to={`/scenarios/${s.id}`}
                            className="px-2 py-1 rounded border mr-2 hover:bg-gray-50"
                          >
                            View
                          </Link>
                          <Link
                            to={`/scenarios/${s.id}?edit=1`}
                            className="px-2 py-1 rounded border hover:bg-gray-50"
                          >
                            Edit
                          </Link>
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}
          </div>
        </>
      )}

      {/* NEW — Scenario Create Modal */}
      {openScenario && (
        <Modal
          title="New Scenario"
          onClose={() => setOpenScenario(false)}
        >
          <div className="space-y-3">
            <Field label="Name">
              <input
                value={scenarioForm.name}
                onChange={(e) => setScenarioForm((f) => ({ ...f, name: e.target.value }))}
                className="w-full px-3 py-2 rounded-md border text-sm"
                placeholder="Base Case"
              />
            </Field>

            <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
              <Field label="Months">
                <input
                  type="number"
                  value={scenarioForm.months}
                  min={1}
                  onChange={(e) => setScenarioForm((f) => ({ ...f, months: e.target.value }))}
                  className="w-full px-3 py-2 rounded-md border text-sm"
                  placeholder="36"
                />
              </Field>
              <Field label="Start Date">
                <input
                  type="date"
                  value={scenarioForm.start_date}
                  onChange={(e) => setScenarioForm((f) => ({ ...f, start_date: e.target.value }))}
                  className="w-full px-3 py-2 rounded-md border text-sm"
                />
              </Field>
            </div>
          </div>

          <div className="mt-5 flex justify-end gap-2">
            <button
              onClick={() => setOpenScenario(false)}
              className="px-3 py-1.5 rounded-md border hover:bg-gray-50"
            >
              Cancel
            </button>
            <button
              disabled={!scenarioValid || savingScenario}
              onClick={onSaveScenario}
              className="px-3 py-1.5 rounded-md bg-indigo-600 text-white disabled:opacity-50"
            >
              {savingScenario ? "Saving…" : "Save"}
            </button>
          </div>
        </Modal>
      )}
    </div>
  );
}

/** Büyük, tek renkli, birbirine giren oklar — stage ilerledikçe koyulaşır; aktif stage daha vurgulu */
function PipelineArrows({
  stages,
  currentStageId,
}: {
  stages: { id: number; no: number; name: string }[];
  currentStageId: number;
}) {
  if (!stages.length) return <div className="text-sm text-gray-500">No stages.</div>;

  // soldan sağa koyulaşan mavi tonlar
  const colorFor = (idx: number) => {
    const total = stages.length;
    const startL = 78; // açık
    const endL = 45; // koyu
    const L = startL - ((startL - endL) * idx) / Math.max(1, total - 1);
    return `hsl(214 70% ${L}%)`;
  };

  // tüm aşamalar için aynı ok şekli
  const shape =
    "polygon(0 0, calc(100% - 24px) 0, 100% 50%, calc(100% - 24px) 100%, 0 100%, 24px 50%)";

  return (
    <div className="w-full flex items-stretch overflow-hidden select-none">
      {stages.map((s, idx) => {
        const isActive = s.id === currentStageId;
        const bg = colorFor(idx);
        const label = idx === stages.length - 1 ? "Won / Lost" : s.name;

        return (
          <div
            key={s.id}
            className="relative flex-1 min-w-0 h-16 flex items-center justify-center"
            style={{ marginLeft: idx === 0 ? 0 : -24 }}
          >
            {/* Kontur SADECE aktif aşamada çizilir */}
            {isActive && (
              <div className="absolute inset-0" style={{ clipPath: shape, background: "#000" }} />
            )}

            {/* İç dolgu */}
            <div
              className="absolute flex items-center justify-center px-6 text-white font-semibold text-sm truncate"
              style={{
                clipPath: shape,
                top: isActive ? 6 : 0,
                bottom: isActive ? 6 : 0,
                left: isActive ? 6 : 0,
                right: isActive ? 6 : 0,
                background: bg,
              }}
            >
              {label}
            </div>
          </div>
        );
      })}
    </div>
  );
}

function KV({ label, value }: { label: string; value?: React.ReactNode | string | null }) {
  const display =
    value == null || value === "" ? <span className="text-gray-500">—</span> : value;
  return (
    <div>
      <div className="text-gray-500 text-xs mb-1">{label}</div>
      <div>{display}</div>
    </div>
  );
}

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

/* ---- small UI helpers (Modal/Field) borrowed from other pages for consistency ---- */
function Field({ label, children }: { label: string; children: React.ReactNode }) {
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
  children: React.ReactNode;
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
