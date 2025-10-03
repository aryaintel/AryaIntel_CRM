// src/pages/LeadDetail.tsx
import { useEffect, useMemo, useState } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";
import { apiGet, ApiError } from "../lib/api";

type Lead = {
  id: number;
  tenant_id: number;

  // temel alanlar (backend LeadOut ile uyumlu)
  name: string;
  company?: string | null;
  email?: string | null;
  phone?: string | null;
  title?: string | null;

  status?: string | null;     // "New" | "Working" | "Qualified" | "Converted" | ...
  source?: string | null;
  rating?: string | null;
  notes?: string | null;

  owner_id: number;
  owner_email?: string | null;

  // meta
  created_at?: string | null;
  updated_at?: string | null;

  // dönüşüm bilgileri (opsiyonel)
  converted_account_id?: number | null;
  converted_opportunity_id?: number | null;
  converted_at?: string | null; // opsiyonel gösterim
};

const STATUSES = ["New", "Working", "Qualified", "Converted"] as const;

export default function LeadDetailPage() {
  const { id } = useParams<{ id: string }>();
  const navigate = useNavigate();

  const [lead, setLead] = useState<Lead | null>(null);
  const [loading, setLoading] = useState(true);
  const [err, setErr] = useState<string | null>(null);

  const currentIndex = useMemo(() => {
    if (!lead?.status) return -1;
    const idx = STATUSES.findIndex(
      (s) => s.toLowerCase() === String(lead.status).toLowerCase()
    );
    return idx;
  }, [lead?.status]);

  const fetchOne = async () => {
    if (!id) return;
    setLoading(true);
    setErr(null);
    try {
      const data = await apiGet<Lead>(`/leads/${id}`);
      setLead(data);
    } catch (e: any) {
      const msg =
        (e instanceof ApiError && e.message) ||
        e?.response?.data?.detail ||
        e?.message ||
        "Failed to load lead";
      setErr(String(msg));
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    fetchOne();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [id]);

  return (
    <div className="space-y-4">
      {/* Header */}
      <div className="flex items-center justify-between">
        <div className="space-y-1">
          <div className="text-xs text-gray-500">
            <Link to="/leads" className="hover:underline">Leads</Link> / <span>Detail</span>
          </div>
          <h1 className="text-xl font-semibold">
            {lead?.name ?? (loading ? "Loading…" : "Lead")}
          </h1>
        </div>
        <div className="flex gap-2">
          <button
            onClick={() => navigate("/leads")}
            className="px-3 py-1.5 rounded-md border text-sm hover:bg-gray-50"
          >
            Back to list
          </button>
        </div>
      </div>

      {/* States */}
      {loading && <div className="text-sm text-gray-500">Loading lead…</div>}
      {err && <div className="text-sm text-red-600">Error: {err}</div>}

      {/* Converted banner */}
      {!loading && !err && lead && (lead.converted_account_id || lead.converted_opportunity_id) && (
        <div className="bg-indigo-50 border border-indigo-200 rounded-lg p-4 flex flex-col md:flex-row md:items-center md:justify-between gap-3">
          <div className="text-sm">
            <b className="text-indigo-700">This lead is converted.</b>{" "}
            {lead.converted_at ? (
              <span className="text-indigo-700/80">
                ({new Date(lead.converted_at).toLocaleString()})
              </span>
            ) : null}
          </div>
          <div className="flex flex-wrap gap-2">
            {lead.converted_account_id ? (
              <Link
                to={`/accounts/${lead.converted_account_id}`}
                className="px-3 py-1.5 rounded-md border border-indigo-300 text-indigo-700 hover:bg-indigo-100 text-sm"
              >
                View Account
              </Link>
            ) : null}
            {lead.converted_opportunity_id ? (
              <Link
                to={`/deals/${lead.converted_opportunity_id}`}
                className="px-3 py-1.5 rounded-md border border-indigo-300 text-indigo-700 hover:bg-indigo-100 text-sm"
              >
                View Opportunity
              </Link>
            ) : null}
          </div>
        </div>
      )}

      {/* Content */}
      {!loading && !err && lead && (
        <div className="grid grid-cols-1 lg:grid-cols-3 gap-4">
          {/* LEFT — Pipeline + Overview */}
          <div className="lg:col-span-2 space-y-4">
            {/* Pipeline */}
            <div className="bg-white rounded-xl shadow p-5">
              <div className="text-lg font-medium mb-4">Lead Status</div>
              <PipelineArrows
                stages={STATUSES as unknown as string[]}
                currentIndex={currentIndex}
                lastLabel="Converted"
              />
            </div>

            {/* Overview */}
            <div className="bg-white rounded-xl shadow p-5">
              <div className="text-lg font-medium mb-4">Overview</div>
              <div className="grid grid-cols-1 md:grid-cols-2 gap-4 text-sm">
                <KV label="Name" value={lead.name} />
                <KV label="Company" value={lead.company ?? "—"} />
                <KV label="Email" value={lead.email ?? "—"} />
                <KV label="Phone" value={lead.phone ?? "—"} />
                <KV label="Title" value={lead.title ?? "—"} />
                <KV label="Source" value={lead.source ?? "—"} />
                <KV label="Rating" value={lead.rating ?? "—"} />
                <KV label="Owner" value={lead.owner_email ?? lead.owner_id} />
                <KV label="Notes" value={lead.notes ?? "—"} />
              </div>
            </div>
          </div>

          {/* RIGHT — Meta */}
          <div className="bg-white rounded-xl shadow p-5">
            <div className="text-lg font-medium mb-4">Lead Info</div>
            <div className="text-sm space-y-2">
              <KV label="Status" value={lead.status ?? "—"} />
              <KV label="Created" value={lead.created_at ? new Date(lead.created_at).toLocaleString() : "—"} />
              <KV label="Updated" value={lead.updated_at ? new Date(lead.updated_at).toLocaleString() : "—"} />
              <KV label="Lead ID" value={String(lead.id)} />
              {lead.converted_account_id ? (
                <KV label="Converted Account ID" value={
                  <Link to={`/accounts/${lead.converted_account_id}`} className="text-indigo-600 hover:underline">
                    {lead.converted_account_id}
                  </Link>
                } />
              ) : null}
              {lead.converted_opportunity_id ? (
                <KV label="Converted Opportunity ID" value={
                  <Link to={`/deals/${lead.converted_opportunity_id}`} className="text-indigo-600 hover:underline">
                    {lead.converted_opportunity_id}
                  </Link>
                } />
              ) : null}
            </div>
          </div>
        </div>
      )}
    </div>
  );
}

/** Opportunities’teki ile aynı oklar – yalnızca aktif adım siyah konturlu; diğerleri tek renk */
function PipelineArrows({
  stages,
  currentIndex,
  lastLabel = "Converted",
}: {
  stages: string[];
  currentIndex: number; // 0-based; -1 ise hiçbirini vurgulama
  lastLabel?: string;
}) {
  if (!stages.length) return <div className="text-sm text-gray-500">No statuses.</div>;

  const colorFor = (idx: number) => {
    const total = stages.length;
    const startL = 78;
    const endL = 45;
    const L = startL - ((startL - endL) * idx) / Math.max(1, total - 1);
    return `hsl(214 70% ${L}%)`;
  };

  const shape =
    "polygon(0 0, calc(100% - 24px) 0, 100% 50%, calc(100% - 24px) 100%, 0 100%, 24px 50%)";

  return (
    <div className="w-full flex items-stretch overflow-hidden select-none">
      {stages.map((name, idx) => {
        const isActive = idx === currentIndex;
        const bg = colorFor(idx);
        const label = idx === stages.length - 1 ? lastLabel : name;

        return (
          <div
            key={name}
            className="relative flex-1 min-w-0 h-16 flex items-center justify-center"
            style={{ marginLeft: idx === 0 ? 0 : -24 }}
          >
            {isActive && <div className="absolute inset-0" style={{ clipPath: shape, background: "#000" }} />}
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
  const display = value == null || value === "" ? <span className="text-gray-500">—</span> : value;
  return (
    <div>
      <div className="text-gray-500 text-xs mb-1">{label}</div>
      <div>{display}</div>
    </div>
  );
}
