// src/pages/AccountDetail.tsx
import { useEffect, useMemo, useState } from "react";
import { useParams, Link, useNavigate } from "react-router-dom";
import { apiGet, apiPatch, apiDelete, ApiError } from "../lib/api";

type Account = {
  id: number;
  name: string;
  industry?: string | null;
  type?: string | null;
  website?: string | null;
  phone?: string | null;
  billing_address?: string | null;
  shipping_address?: string | null;

  // SF-like fields
  account_number?: string | null;
  employees?: number | null;
  annual_revenue?: number | null;
  rating?: string | null;
  ownership?: string | null;
  description?: string | null;

  owner_id?: number | null;
  owner_email?: string | null;
  created_at?: string | null;
};

export default function AccountDetailPage() {
  const { id } = useParams<{ id: string }>();
  const navigate = useNavigate();
  const [data, setData] = useState<Account | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [modalOpen, setModalOpen] = useState(false);
  const [saving, setSaving] = useState(false);
  const [form, setForm] = useState({
    name: "",
    industry: "",
    type: "",
    website: "",
    phone: "",
    billing_address: "",
    shipping_address: "",

    account_number: "",
    employees: "",
    annual_revenue: "",
    rating: "",
    ownership: "",
    description: "",
  });

  const isValid = useMemo(() => form.name.trim().length > 1, [form.name]);

  const byIdUrl = (value: number | string) => `/accounts/${value}/`;
  const byIdUrlNoSlash = (value: number | string) => `/accounts/${value}`;

  const fetchAccount = async () => {
    if (!id) return;
    setLoading(true);
    setError(null);
    try {
      const acc = await apiGet<Account>(`/accounts/${id}`);
      setData(acc);
    } catch (e: any) {
      const msg =
        (e instanceof ApiError && e.message) ||
        e?.response?.data?.detail ||
        e?.message ||
        "Failed to load account";
      setError(String(msg));
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    fetchAccount();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [id]);

    const openEditModal = () => {
    if (!data) return;
    setForm({
      name: data.name || "",
      industry: data.industry || "",
      type: data.type || "",
      website: data.website || "",
      phone: data.phone || "",
      billing_address: data.billing_address || "",
      shipping_address: data.shipping_address || "",
      account_number: data.account_number || "",
      employees: data.employees != null ? String(data.employees) : "",
      annual_revenue: data.annual_revenue != null ? String(data.annual_revenue) : "",
      rating: data.rating || "",
      ownership: data.ownership || "",
      description: data.description || "",
    });
    setModalOpen(true);
  };

  const onSave = async () => {
    if (!data || !isValid) return;
    setSaving(true);

    const base = {
      name: form.name.trim(),
      industry: form.industry.trim() || null,
      type: form.type.trim() || null,
      website: form.website.trim() || null,
      phone: form.phone.trim() || null,
      billing_address: form.billing_address.trim() || null,
      shipping_address: form.shipping_address.trim() || null,

      account_number: form.account_number.trim() || null,
      employees: form.employees.trim() === "" ? null : Number(form.employees),
      annual_revenue: form.annual_revenue.trim() === "" ? null : Number(form.annual_revenue),
      rating: form.rating.trim() || null,
      ownership: form.ownership.trim() || null,
      description: form.description.trim() || null,
    };

    try {
      try {
        await apiPatch(byIdUrl(data.id), base);
      } catch {
        await apiPatch(byIdUrlNoSlash(data.id), base);
      }
      setModalOpen(false);
      await fetchAccount();
    } catch (e: any) {
      const msg =
        (e instanceof ApiError && e.message) ||
        e?.response?.data?.detail ||
        e?.message ||
        "Save failed";
      alert(String(msg));
    } finally {
      setSaving(false);
    }
  };

  const onDelete = async () => {
    if (!data) return;
    if (!confirm(`Delete account "${data.name}"?`)) return;
    try {
      try {
        await apiDelete(byIdUrl(data.id));
      } catch {
        await apiDelete(byIdUrlNoSlash(data.id));
      }
      alert("Deleted.");
      navigate("/accounts");
    } catch (e: any) {
      const msg =
        (e instanceof ApiError && e.message) ||
        e?.response?.data?.detail ||
        e?.message ||
        "Delete failed";
      alert(String(msg));
    }
  };

  return (
    <div className="space-y-4">
      {/* Header / Breadcrumbs */}
      <div className="flex items-center justify-between">
        <div className="space-y-1">
          <div className="text-xs text-gray-500">
            <Link to="/accounts" className="hover:underline">
              Accounts
            </Link>{" "}
            / <span>Detail</span>
          </div>
          <h1 className="text-xl font-semibold">
            {data?.name ?? (loading ? "Loading…" : "Account")}
          </h1>
        </div>
        <div className="flex gap-2 bg-white rounded-md border px-3 py-2 shadow-sm">
          <button
            onClick={() => navigate("/accounts")}
            className="px-3 py-1.5 rounded-md border text-sm hover:bg-gray-50"
          >
            Back to list
          </button>
         <button
            type="button"
            disabled={!data}
            onClick={openEditModal}
            className="px-2 py-1 rounded border hover:bg-gray-50 text-sm disabled:opacity-50"
          >
            Edit
          </button>
          <button
            type="button"
            disabled={!data}
            onClick={onDelete}
            className="px-2 py-1 rounded border hover:bg-gray-50 text-sm disabled:opacity-50"
          >
            Delete
          </button>
        </div>
      </div>

      {/* States */}
      {loading && <div className="text-sm text-gray-500">Loading account…</div>}
      {error && <div className="text-sm text-red-600">Error: {error}</div>}

      {/* Content */}
      {!loading && !error && data && (
        <div className="grid grid-cols-1 lg:grid-cols-3 gap-4">
          {/* Overview card (2/3) */}
          <div className="lg:col-span-2 bg-white rounded-xl shadow p-5">
            <div className="text-lg font-medium mb-4">Overview</div>

            <div className="grid grid-cols-1 md:grid-cols-2 gap-4 text-sm">
              <KV label="Industry" value={data.industry} />
              <KV label="Type" value={data.type} />
              <KV
                label="Website"
                value={
                  data.website ? (
                    <a
                      href={data.website}
                      target="_blank"
                      rel="noreferrer"
                      className="text-indigo-600 hover:underline"
                    >
                      {data.website}
                    </a>
                  ) : (
                    "—"
                  )
                }
              />
              <KV label="Phone" value={data.phone} />

              <KV label="Account Number" value={data.account_number} />
              <KV
                label="Employees"
                value={
                  data.employees != null ? data.employees.toLocaleString() : "—"
                }
              />
              <KV
                label="Annual Revenue"
                value={
                  data.annual_revenue != null
                    ? data.annual_revenue.toLocaleString()
                    : "—"
                }
              />
              <KV label="Rating" value={data.rating} />
              <KV label="Ownership" value={data.ownership} />

              <div className="md:col-span-2">
                <KV label="Billing Address" value={data.billing_address} />
              </div>
              <div className="md:col-span-2">
                <KV label="Shipping Address" value={data.shipping_address} />
              </div>
              <div className="md:col-span-2">
                <KV label="Description" value={data.description} multiline />
              </div>
            </div>
          </div>

          {/* Side meta (1/3) */}
          <div className="bg-white rounded-xl shadow p-5">
            <div className="text-lg font-medium mb-4">Account Info</div>
            <div className="text-sm space-y-2">
              <KV label="Owner" value={data.owner_email} />
              <KV
                label="Created"
                value={
                  data.created_at
                    ? new Date(data.created_at).toLocaleString()
                    : "—"
                }
              />
              <KV label="Account ID" value={String(data.id)} />
            </div>
          </div>

          {/* İlerisi: Tabs (Contacts / Opportunities / Activity) */}
        </div>
      )}
      {modalOpen && (
        <div className="fixed inset-0 bg-black/30 flex items-center justify-center z-50">
          <div className="bg-white w-[760px] max-w-[95vw] rounded-xl shadow p-5">
            <div className="text-lg font-semibold mb-4">Edit Account</div>

            <div className="space-y-3">
              <Field label="Name">
                <input
                  value={form.name}
                  onChange={(e) => setForm((f) => ({ ...f, name: e.target.value }))}
                  className="w-full px-3 py-2 rounded-md border text-sm"
                  placeholder="Acme Corp"
                />
              </Field>

              <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
                <Field label="Industry">
                  <input
                    value={form.industry}
                    onChange={(e) => setForm((f) => ({ ...f, industry: e.target.value }))}
                    className="w-full px-3 py-2 rounded-md border text-sm"
                    placeholder="Manufacturing"
                  />
                </Field>
                <Field label="Type">
                  <input
                    value={form.type}
                    onChange={(e) => setForm((f) => ({ ...f, type: e.target.value }))}
                    className="w-full px-3 py-2 rounded-md border text-sm"
                    placeholder="Customer / Partner…"
                  />
                </Field>
              </div>

              <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
                <Field label="Website">
                  <input
                    value={form.website}
                    onChange={(e) => setForm((f) => ({ ...f, website: e.target.value }))}
                    className="w-full px-3 py-2 rounded-md border text-sm"
                    placeholder="https://acme.example"
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

              <div className="grid grid-cols-1 md:grid-cols-3 gap-3">
                <Field label="Account Number">
                  <input
                    value={form.account_number}
                    onChange={(e) => setForm((f) => ({ ...f, account_number: e.target.value }))}
                    className="w-full px-3 py-2 rounded-md border text-sm"
                    placeholder="AC-00123"
                  />
                </Field>
                <Field label="Employees">
                  <input
                    type="number"
                    value={form.employees}
                    onChange={(e) => setForm((f) => ({ ...f, employees: e.target.value }))}
                    className="w-full px-3 py-2 rounded-md border text-sm"
                    placeholder="250"
                  />
                </Field>
                <Field label="Annual Revenue">
                  <input
                    type="number"
                    value={form.annual_revenue}
                    onChange={(e) => setForm((f) => ({ ...f, annual_revenue: e.target.value }))}
                    className="w-full px-3 py-2 rounded-md border text-sm"
                    placeholder="1000000"
                  />
                </Field>
              </div>

              <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
                <Field label="Rating">
                  <input
                    value={form.rating}
                    onChange={(e) => setForm((f) => ({ ...f, rating: e.target.value }))}
                    className="w-full px-3 py-2 rounded-md border text-sm"
                    placeholder="Hot / Warm / Cold"
                  />
                </Field>
                <Field label="Ownership">
                  <input
                    value={form.ownership}
                    onChange={(e) => setForm((f) => ({ ...f, ownership: e.target.value }))}
                    className="w-full px-3 py-2 rounded-md border text-sm"
                    placeholder="Public / Private / Other"
                  />
                </Field>
              </div>

              <Field label="Billing Address">
                <textarea
                  value={form.billing_address}
                  onChange={(e) => setForm((f) => ({ ...f, billing_address: e.target.value }))}
                  className="w-full px-3 py-2 rounded-md border text-sm"
                  placeholder="Street, City, Zip, Country"
                  rows={2}
                />
              </Field>

              <Field label="Shipping Address">
                <textarea
                  value={form.shipping_address}
                  onChange={(e) => setForm((f) => ({ ...f, shipping_address: e.target.value }))}
                  className="w-full px-3 py-2 rounded-md border text-sm"
                  placeholder="Street, City, Zip, Country"
                  rows={2}
                />
              </Field>

              <Field label="Description">
                <textarea
                  value={form.description}
                  onChange={(e) => setForm((f) => ({ ...f, description: e.target.value }))}
                  className="w-full px-3 py-2 rounded-md border text-sm"
                  placeholder="Notes / background…"
                  rows={3}
                />
              </Field>

              <div className="text-xs text-gray-500">
                Owner: <b>{data?.owner_email ?? "—"}</b>
              </div>
            </div>

            <div className="mt-5 flex justify-end gap-2">
              <button
                onClick={() => {
                  setModalOpen(false);
                }}
                className="px-3 py-1.5 rounded-md border hover:bg-gray-50"
              >
                Cancel
              </button>
              <button
                disabled={!isValid || saving}
                onClick={onSave}
                className="px-3 py-1.5 rounded-md bg-indigo-600 text-white disabled:opacity-50"
              >
                Save
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}

function KV({
  label,
  value,
  multiline,
}: {
  label: string;
  value?: React.ReactNode | string | null;
  multiline?: boolean;
}) {
  const display =
    value == null || value === "" ? (
      <span className="text-gray-500">—</span>
    ) : typeof value === "string" && multiline ? (
      <div className="whitespace-pre-line">{value}</div>
    ) : (
      value
    );
  return (
    <div>
      <div className="text-gray-500 text-xs mb-1">{label}</div>
      <div>{display}</div>
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