// src/pages/Leads.tsx
import { useEffect, useMemo, useState } from "react";
import { Link } from "react-router-dom";
import { apiGet, apiPost, apiPatch, apiDelete, ApiError } from "../lib/api";

type Lead = {
  id: number | string;
  name: string;
  company?: string | null;
  title?: string | null;
  email?: string | null;
  phone?: string | null;
  website?: string | null;
  address?: string | null;
  source?: string | null;
  status?: string | null;
  notes?: string | null;
  owner_email?: string | null;
};

type LeadsPayload = {
  items: Lead[];
  meta?: {
    page?: number;
    size?: number;
    total?: number;
    pages?: number;
    has_next?: boolean;
    has_prev?: boolean;
  };
};

const STATUS_OPTIONS = ["New", "Working", "Nurturing", "Qualified", "Unqualified"];

type ConvertMode = "acc_opp" | "acc_only" | "contact_only";

export default function LeadsPage() {
  const [items, setItems] = useState<Lead[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const [q, setQ] = useState("");
  const [page, setPage] = useState(1);
  const [pageSize] = useState(10);

  const [total, setTotal] = useState<number | undefined>();
  const [hasNext, setHasNext] = useState<boolean | undefined>();
  const [hasPrev, setHasPrev] = useState<boolean | undefined>();
  const [pages, setPages] = useState<number | undefined>();

  // modal state
  const [open, setOpen] = useState(false);
  const [editing, setEditing] = useState<Lead | null>(null);
  const [form, setForm] = useState({
    name: "",
    company: "",
    title: "",
    email: "",
    phone: "",
    website: "",
    address: "",
    source: "",
    status: "New",
    notes: "",
  });

  // Convert modal state
  const [convertOpen, setConvertOpen] = useState(false);
  const [convertLead, setConvertLead] = useState<Lead | null>(null);
  const [convertMode, setConvertMode] = useState<ConvertMode>("acc_opp");
  const [convertSaving, setConvertSaving] = useState(false);

  const isValid = useMemo(() => (form.name || "").trim().length > 1, [form]);

  const byIdUrl = (id: number | string) => `/leads/${id}/`;
  const byIdUrlNoSlash = (id: number | string) => `/leads/${id}`;

  const fetchLeads = async () => {
    setLoading(true);
    setError(null);
    try {
      const qs = new URLSearchParams({
        page: String(page),
        size: String(pageSize),
      });
      if (q.trim()) qs.set("q", q.trim());

      const payload = await apiGet<LeadsPayload>(`/leads/?${qs.toString()}`);

      setItems(payload.items ?? []);
      setTotal(payload.meta?.total);
      setPages(payload.meta?.pages);

      if (typeof payload.meta?.has_next === "boolean") {
        setHasNext(payload.meta.has_next);
      } else if (payload.meta?.pages) {
        setHasNext(page < (payload.meta.pages ?? 1));
      } else if (payload.meta?.total != null) {
        setHasNext(page * pageSize < (payload.meta.total ?? 0));
      } else {
        setHasNext(undefined);
      }
      setHasPrev(typeof payload.meta?.has_prev === "boolean" ? payload.meta.has_prev : page > 1);
    } catch (e: any) {
      const msg =
        (e instanceof ApiError && e.message) ||
        e?.response?.data?.detail ||
        e?.message ||
        "Unknown error";
      setError(String(msg));
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    fetchLeads();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [page, pageSize]);

  const onSearch = (e: React.FormEvent) => {
    e.preventDefault();
    setPage(1);
    fetchLeads();
  };

  const onNew = () => {
    setEditing(null);
    setForm({
      name: "",
      company: "",
      title: "",
      email: "",
      phone: "",
      website: "",
      address: "",
      source: "",
      status: "New",
      notes: "",
    });
    setOpen(true);
  };

  const onEdit = (row: Lead) => {
    setEditing(row);
    setForm({
      name: row.name || "",
      company: row.company || "",
      title: row.title || "",
      email: row.email || "",
      phone: row.phone || "",
      website: row.website || "",
      address: row.address || "",
      source: row.source || "",
      status: row.status || "New",
      notes: row.notes || "",
    });
    setOpen(true);
  };

  const onDelete = async (row: Lead) => {
    if (!confirm(`Delete lead "${row.name}"?`)) return;
    try {
      try {
        await apiDelete(byIdUrl(row.id));
      } catch {
        await apiDelete(byIdUrlNoSlash(row.id));
      }
      await fetchLeads();
      alert("Deleted.");
    } catch (e: any) {
      const msg =
        (e instanceof ApiError && e.message) ||
        e?.response?.data?.detail ||
        e?.message ||
        "Delete failed";
      alert(String(msg));
    }
  };

  const onSave = async () => {
    if (!isValid) return;

    const base = {
      name: form.name.trim(),
      company: form.company.trim() || null,
      title: form.title.trim() || null,
      email: form.email.trim() || null,
      phone: form.phone.trim() || null,
      website: form.website.trim() || null,
      address: form.address.trim() || null,
      source: form.source.trim() || null,
      status: form.status.trim() || null,
      notes: form.notes.trim() || null,
    };

    try {
      if (editing) {
        try {
          await apiPatch(byIdUrl(editing.id), base);
        } catch {
          await apiPatch(byIdUrlNoSlash(editing.id), base);
        }
      } else {
        await apiPost("/leads/", base);
      }
      setOpen(false);
      await fetchLeads();
    } catch (e: any) {
      const msg =
        (e instanceof ApiError && e.message) ||
        e?.response?.data?.detail ||
        e?.message ||
        "Save failed";
      alert(String(msg));
    }
  };

  // ---- Convert flow (with modal) ----
  const openConvert = (row: Lead) => {
    setConvertLead(row);
    setConvertMode("acc_opp");
    setConvertOpen(true);
  };

  const doConvert = async () => {
    if (!convertLead) return;
    setConvertSaving(true);
    try {
      let payload: any;
      if (convertMode === "acc_opp") {
        payload = { create_account: true, create_opportunity: true };
      } else if (convertMode === "acc_only") {
        payload = { create_account: true, create_opportunity: false };
      } else {
        // contact_only – backend’i bir sonraki adımda bu alanla güncelleyeceğiz
        payload = { create_account: false, create_opportunity: false, create_contact_only: true };
      }
      await apiPost(`/leads/${convertLead.id}/convert`, payload);
      setConvertOpen(false);
      await fetchLeads();
      alert("Converted.");
    } catch (e: any) {
      const msg =
        (e instanceof ApiError && e.message) ||
        e?.response?.data?.detail ||
        e?.message ||
        "Convert failed";
      alert(String(msg));
    } finally {
      setConvertSaving(false);
    }
  };

  return (
    <div className="bg-white rounded-xl shadow p-6">
      {/* header */}
      <div className="flex flex-col sm:flex-row sm:items-center sm:justify-between gap-3 mb-4">
        <h2 className="text-lg font-medium">Leads</h2>
        <form onSubmit={onSearch} className="flex gap-2">
          <input
            value={q}
            onChange={(e) => setQ(e.target.value)}
            placeholder="Search name, company, email, phone…"
            className="px-3 py-1.5 rounded-md border text-sm w-64"
          />
          <button type="submit" className="px-3 py-1.5 rounded-md border text-sm hover:bg-gray-50">
            Search
          </button>
          <button
            type="button"
            onClick={fetchLeads}
            className="px-3 py-1.5 rounded-md border text-sm hover:bg-gray-50"
          >
            Refresh
          </button>
          <button
            type="button"
            onClick={onNew}
            className="px-3 py-1.5 rounded-md bg-indigo-600 text-white text-sm hover:bg-indigo-500"
          >
            + New
          </button>
        </form>
      </div>

      {/* states */}
      {loading && <div className="text-sm text-gray-500">Loading leads…</div>}
      {error && <div className="text-sm text-red-600">Error: {error}</div>}
      {!loading && !error && items.length === 0 && (
        <div className="text-sm text-gray-500">
          No leads yet. Add one and click <b>Refresh</b>.
        </div>
      )}

      {/* list */}
      {!loading && !error && items.length > 0 && (
        <>
          <div className="overflow-x-auto">
            <table className="min-w-full text-sm">
              <thead>
                <tr className="text-left border-b">
                  <th className="py-2 pr-4">Name</th>
                  <th className="py-2 pr-4">Company</th>
                  <th className="py-2 pr-4">Email</th>
                  <th className="py-2 pr-4">Phone</th>
                  <th className="py-2 pr-4">Status</th>
                  <th className="py-2 pr-4">Owner</th>
                  <th className="py-2 pr-4 w-56 text-right">Actions</th>
                </tr>
              </thead>
              <tbody>
                {items.map((l) => (
                  <tr key={l.id} className="border-b last:border-0">
                    <td className="py-2 pr-4 font-medium">
                      <Link to={`/leads/${l.id}`} className="text-indigo-600 hover:underline">
                        {l.name}
                      </Link>
                    </td>
                    <td className="py-2 pr-4">{l.company ?? "—"}</td>
                    <td className="py-2 pr-4">{l.email ?? "—"}</td>
                    <td className="py-2 pr-4">{l.phone ?? "—"}</td>
                    <td className="py-2 pr-4">{l.status ?? "—"}</td>
                    <td className="py-2 pr-4">{l.owner_email ?? "—"}</td>
                    <td className="py-2 pr-4 text-right">
                      <button
                        onClick={() => openConvert(l)}
                        className="px-2 py-1 rounded border mr-2 hover:bg-gray-50"
                        title="Convert"
                      >
                        Convert
                      </button>
                      <button
                        onClick={() => onEdit(l)}
                        className="px-2 py-1 rounded border mr-2 hover:bg-gray-50"
                      >
                        Edit
                      </button>
                      <button
                        onClick={() => onDelete(l)}
                        className="px-2 py-1 rounded border hover:bg-gray-50"
                      >
                        Delete
                      </button>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>

          {/* pager */}
          <div className="flex items-center justify-between mt-4 text-sm">
            <div className="text-gray-500">
              Page {page}
              {typeof pages === "number" ? <> / {pages}</> : null}
              {typeof total === "number" ? <> • Total: {total}</> : null}
            </div>
            <div className="flex gap-2">
              <button
                disabled={hasPrev === false || page === 1}
                onClick={() => setPage((p) => Math.max(1, p - 1))}
                className="px-3 py-1.5 rounded-md border hover:bg-gray-50 disabled:opacity-50"
              >
                ‹ Prev
              </button>
              <button
                disabled={hasNext === false}
                onClick={() => setPage((p) => p + 1)}
                className="px-3 py-1.5 rounded-md border hover:bg-gray-50 disabled:opacity-50"
              >
                Next ›
              </button>
            </div>
          </div>
        </>
      )}

      {/* create/edit modal */}
      {open && (
        <div className="fixed inset-0 bg-black/30 flex items-center justify-center z-50">
          <div className="bg-white w-[760px] max-w-[95vw] rounded-xl shadow p-5">
            <div className="text-lg font-semibold mb-4">
              {editing ? "Edit Lead" : "New Lead"}
            </div>

            <div className="space-y-3">
              <Field label="Name">
                <input
                  value={form.name}
                  onChange={(e) => setForm((f) => ({ ...f, name: e.target.value }))}
                  className="w-full px-3 py-2 rounded-md border text-sm"
                  placeholder="John Doe"
                />
              </Field>

              <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
                <Field label="Company">
                  <input
                    value={form.company}
                    onChange={(e) => setForm((f) => ({ ...f, company: e.target.value }))}
                    className="w-full px-3 py-2 rounded-md border text-sm"
                    placeholder="Acme Inc."
                  />
                </Field>
                <Field label="Title">
                  <input
                    value={form.title}
                    onChange={(e) => setForm((f) => ({ ...f, title: e.target.value }))}
                    className="w-full px-3 py-2 rounded-md border text-sm"
                    placeholder="CTO"
                  />
                </Field>
              </div>

              <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
                <Field label="Email">
                  <input
                    value={form.email}
                    onChange={(e) => setForm((f) => ({ ...f, email: e.target.value }))}
                    className="w-full px-3 py-2 rounded-md border text-sm"
                    placeholder="john@example.com"
                  />
                </Field>
                <Field label="Phone">
                  <input
                    value={form.phone}
                    onChange={(e) => setForm((f) => ({ ...f, phone: e.target.value }))}
                    className="w-full px-3 py-2 rounded-md border text-sm"
                    placeholder="+90 555 000 00 00"
                  />
                </Field>
              </div>

              <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
                <Field label="Website">
                  <input
                    value={form.website}
                    onChange={(e) => setForm((f) => ({ ...f, website: e.target.value }))}
                    className="w-full px-3 py-2 rounded-md border text-sm"
                    placeholder="https://example.com"
                  />
                </Field>
                <Field label="Address">
                  <input
                    value={form.address}
                    onChange={(e) => setForm((f) => ({ ...f, address: e.target.value }))}
                    className="w-full px-3 py-2 rounded-md border text-sm"
                    placeholder="Street, City, Zip, Country"
                  />
                </Field>
              </div>

              <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
                <Field label="Source">
                  <input
                    value={form.source}
                    onChange={(e) => setForm((f) => ({ ...f, source: e.target.value }))}
                    className="w-full px-3 py-2 rounded-md border text-sm"
                    placeholder="Web, Referral, Event…"
                  />
                </Field>
                <Field label="Status">
                  <select
                    value={form.status}
                    onChange={(e) => setForm((f) => ({ ...f, status: e.target.value }))}
                    className="w-full px-3 py-2 rounded-md border text-sm bg-white"
                  >
                    {STATUS_OPTIONS.map((s) => (
                      <option key={s} value={s}>
                        {s}
                      </option>
                    ))}
                  </select>
                </Field>
              </div>

              <Field label="Notes">
                <textarea
                  value={form.notes}
                  onChange={(e) => setForm((f) => ({ ...f, notes: e.target.value }))}
                  className="w-full px-3 py-2 rounded-md border text-sm"
                  placeholder="Background, interests, objections…"
                  rows={3}
                />
              </Field>

              <div className="text-xs text-gray-500">
                {editing ? (
                  <>Owner: <b>{editing.owner_email ?? "—"}</b></>
                ) : (
                  <>Owner: <b>bu kaydı oluşturan kullanıcı</b> olacaktır.</>
                )}
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
                onClick={onSave}
                className="px-3 py-1.5 rounded-md bg-indigo-600 text-white disabled:opacity-50"
              >
                Save
              </button>
            </div>
          </div>
        </div>
      )}

      {/* Convert modal */}
      {convertOpen && convertLead && (
        <div className="fixed inset-0 bg-black/30 flex items-center justify-center z-50">
          <div className="bg-white w-[520px] max-w-[95vw] rounded-xl shadow p-5">
            <div className="text-lg font-semibold mb-2">Convert Lead</div>
            <div className="text-sm text-gray-600 mb-4">
              <b>{convertLead.name}</b> için dönüşüm seçeneğini belirleyin:
            </div>

            <div className="space-y-3 text-sm">
              <label className="flex items-center gap-3">
                <input
                  type="radio"
                  name="convertMode"
                  checked={convertMode === "acc_opp"}
                  onChange={() => setConvertMode("acc_opp")}
                />
                <span>Create <b>Account &amp; Opportunity</b></span>
              </label>

              <label className="flex items-center gap-3">
                <input
                  type="radio"
                  name="convertMode"
                  checked={convertMode === "acc_only"}
                  onChange={() => setConvertMode("acc_only")}
                />
                <span>Create <b>Account only</b> (no Opportunity)</span>
              </label>

              <label className="flex items-center gap-3">
                <input
                  type="radio"
                  name="convertMode"
                  checked={convertMode === "contact_only"}
                  onChange={() => setConvertMode("contact_only")}
                />
                <span>Create <b>Contact only</b> (no Account, no Opportunity)</span>
              </label>
            </div>

            <div className="mt-5 flex justify-end gap-2">
              <button
                onClick={() => setConvertOpen(false)}
                className="px-3 py-1.5 rounded-md border hover:bg-gray-50"
                disabled={convertSaving}
              >
                Cancel
              </button>
              <button
                onClick={doConvert}
                disabled={convertSaving}
                className="px-3 py-1.5 rounded-md bg-indigo-600 text-white disabled:opacity-50"
              >
                {convertSaving ? "Converting…" : "Convert"}
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}

function Field({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <label className="block">
      <div className="text-xs text-gray-500 mb-1">{label}</div>
      {children}
    </label>
  );
}
