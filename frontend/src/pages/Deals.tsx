// src/pages/Deals.tsx — UI: Opportunities
import { useEffect, useMemo, useState } from "react";
import { Link } from "react-router-dom";
import { apiGet, apiPost, apiPatch, apiDelete, ApiError } from "../lib/api";

type Deal = {
  id: number | string;
  account_id: number;
  account_name?: string | null;
  owner_id: number;
  owner_email?: string | null;
  name: string;
  amount?: number | null;
  currency?: string | null;
  stage_id?: number | null;
  expected_close_date?: string | null;
  source?: string | null;
};

type DealsPayload = {
  items: Deal[];
  total?: number;
  page?: number;
  page_size?: number;
};

type AccountRow = { id: number; name: string; industry?: string | null };
type AccountsList = { items: AccountRow[] };

type StageRow = { id: number; no: number; name: string };

export default function DealsPage() {
  const [items, setItems] = useState<Deal[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const [page, setPage] = useState(1);
  const [pageSize] = useState(20);
  const [total, setTotal] = useState<number | undefined>();

  const [stages, setStages] = useState<StageRow[]>([]);
  const stageMap = useMemo(
    () => Object.fromEntries(stages.map((s) => [s.id, s] as const)),
    [stages]
  );

  const [accQuery, setAccQuery] = useState("");
  const [accOptions, setAccOptions] = useState<AccountRow[]>([]);
  const [accLoading, setAccLoading] = useState(false);

  const [open, setOpen] = useState(false);
  const [editing, setEditing] = useState<Deal | null>(null);
  const [form, setForm] = useState<{
    name: string;
    amount: string;
    currency: string;
    expected_close_date: string;
    source: string;
    account_id: string | number | "";
    account_name: string;
    stage_id: number | "";
    owner_email_hint?: string | null;
  }>({
    name: "",
    amount: "",
    currency: "",
    expected_close_date: "",
    source: "",
    account_id: "",
    account_name: "",
    stage_id: "",
    owner_email_hint: null,
  });

  const isValid = useMemo(() => {
    const hasName = (form.name || "").trim().length > 1;
    const hasAccount = form.account_id !== "" && form.account_id !== null;
    return hasName && hasAccount;
  }, [form]);

  const byIdUrl = (id: number | string) => `/deals/${id}/`;
  const byIdUrlNoSlash = (id: number | string) => `/deals/${id}`;

  const fetchDeals = async (p = page) => {
    setLoading(true);
    setError(null);
    try {
      const qs = new URLSearchParams({ page: String(p), page_size: String(pageSize) });
      const data = await apiGet<DealsPayload>(`/deals/?${qs.toString()}`);
      const list: Deal[] = Array.isArray((data as any).items)
        ? ((data as any).items as Deal[])
        : [];
      setItems(list);
      setTotal(typeof data.total === "number" ? data.total : list.length);
      setPage(typeof data.page === "number" ? data.page : p);
    } catch (e: any) {
      const msg =
        (e instanceof ApiError && e.message) || e?.message || "Opportunities fetch failed";
      setError(String(msg));
    } finally {
      setLoading(false);
    }
  };

  const fetchStages = async () => {
    try {
      const list = await apiGet<StageRow[]>("/deals/stages");
      setStages(list);
    } catch {
      setStages([]);
    }
  };

  useEffect(() => {
    fetchDeals(1);
    fetchStages();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const pagerText = useMemo(() => {
    const head = `Page ${page}`;
    return typeof total === "number" ? `${head} • Total: ${total}` : head;
  }, [page, total]);

  const hasPrev = page > 1;
  const hasNext =
    typeof total === "number" ? page * pageSize < total : items.length === pageSize;

  const fetchAccounts = async (q: string) => {
    setAccLoading(true);
    try {
      const qs = new URLSearchParams({ q, size: "10", page: "1" });
      const data = await apiGet<AccountsList>(`/accounts/?${qs.toString()}`);
      const list = Array.isArray((data as any).items)
        ? ((data as any).items as AccountRow[])
        : [];
      setAccOptions(list);
    } catch {
      setAccOptions([]);
    } finally {
      setAccLoading(false);
    }
  };

  useEffect(() => {
    const t = setTimeout(() => {
      if (accQuery.trim().length) fetchAccounts(accQuery.trim());
      else setAccOptions([]);
    }, 250);
    return () => clearTimeout(t);
  }, [accQuery]);

  const onRefresh = () => fetchDeals(page);

  const onNew = () => {
    setEditing(null);
    setForm({
      name: "",
      amount: "",
      currency: "",
      expected_close_date: "",
      source: "",
      account_id: "",
      account_name: "",
      stage_id: "",
      owner_email_hint: null,
    });
    setAccQuery("");
    setAccOptions([]);
    setOpen(true);
  };

  const onEdit = (d: Deal) => {
    setEditing(d);
    setForm({
      name: d.name ?? "",
      amount: d.amount != null ? String(d.amount) : "",
      currency: d.currency ?? "",
      expected_close_date: (d.expected_close_date ?? "").slice(0, 10),
      source: d.source ?? "",
      account_id: d.account_id,
      account_name: d.account_name ?? "",
      stage_id: d.stage_id ?? "",
      owner_email_hint: d.owner_email ?? null,
    });
    setAccQuery("");
    setAccOptions([]);
    setOpen(true);
  };

  const onDelete = async (row: Deal) => {
    if (!confirm(`Delete opportunity "${row.name ?? row.id}"?`)) return;
    try {
      try {
        await apiDelete(byIdUrl(row.id));
      } catch {
        await apiDelete(byIdUrlNoSlash(row.id));
      }
      await fetchDeals(page);
      alert("Deleted.");
    } catch (e: any) {
      const msg = (e instanceof ApiError && e.message) || e?.message || "Delete failed";
      alert(String(msg));
    }
  };

  const onSave = async () => {
    if (!isValid) return;

    const createPayload = {
      name: form.name.trim(),
      amount: form.amount.trim() === "" ? null : Number(form.amount),
      currency: form.currency.trim() || null,
      expected_close_date: form.expected_close_date || null,
      source: form.source.trim() || null,
      account_id: Number(form.account_id),
      stage_id: form.stage_id === "" ? undefined : Number(form.stage_id),
    };

    const updatePayload = {
      name: form.name.trim(),
      amount: form.amount.trim() === "" ? null : Number(form.amount),
      currency: form.currency.trim() || null,
      expected_close_date: form.expected_close_date || null,
      source: form.source.trim() || null,
      stage_id: form.stage_id === "" ? undefined : Number(form.stage_id),
    };

    try {
      if (editing) {
        try {
          await apiPatch(byIdUrl(editing.id), updatePayload);
        } catch {
          await apiPatch(byIdUrlNoSlash(editing.id), updatePayload);
        }
      } else {
        await apiPost("/deals/", createPayload);
      }
      setOpen(false);
      await fetchDeals(page);
      alert("Saved.");
    } catch (e: any) {
      const msg = (e instanceof ApiError && e.message) || e?.message || "Save failed";
      alert(String(msg));
    }
  };

  return (
    <div className="bg-white rounded-xl shadow p-6">
      {/* header — Accounts ile aynı düzen */}
      <div className="flex flex-col sm:flex-row sm:items-center sm:justify-between gap-3 mb-4">
        <h2 className="text-lg font-medium">Opportunities</h2>
        <div className="flex gap-2">
          <button
            type="button"
            onClick={onRefresh}
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
        </div>
      </div>

      {/* states */}
      {loading && <div className="text-sm text-gray-500">Loading opportunities…</div>}
      {error && <div className="text-sm text-red-600">Error: {error}</div>}
      {!loading && !error && items.length === 0 && (
        <div className="text-sm text-gray-500">
          No opportunities yet. Add one and click <b>Refresh</b>.
        </div>
      )}

      {/* list — Accounts tablosuyla birebir */}
      {!loading && !error && items.length > 0 && (
        <>
          <div className="overflow-x-auto">
            <table className="min-w-full text-sm">
              <thead>
                <tr className="text-left border-b">
                  <th className="py-2 pr-4">Name</th>
                  <th className="py-2 pr-4">Account</th>
                  <th className="py-2 pr-4">Owner</th>
                  <th className="py-2 pr-4">Stage</th>
                  <th className="py-2 pr-4">Amount</th>
                  <th className="py-2 pr-4">Currency</th>
                  <th className="py-2 pr-4">Expected Close</th>
                  <th className="py-2 pr-4">Source</th>
                  <th className="py-2 pr-4 w-32 text-right">Actions</th>
                </tr>
              </thead>
              <tbody>
                {items.map((d) => (
                  <tr key={d.id} className="border-b last:border-0">
                    <td className="py-2 pr-4 font-medium">
                      {d.name ? (
                        <Link to={`/deals/${d.id}`} className="text-indigo-600 hover:underline">
                          {d.name}
                        </Link>
                      ) : (
                        "—"
                      )}
                    </td>
                    <td className="py-2 pr-4">{d.account_name ?? d.account_id ?? "—"}</td>
                    <td className="py-2 pr-4">{d.owner_email ?? d.owner_id ?? "—"}</td>
                    <td className="py-2 pr-4">
                      {d.stage_id ? (stageMap[d.stage_id]?.name ?? d.stage_id) : "—"}
                    </td>
                    <td className="py-2 pr-4">{d.amount ?? "—"}</td>
                    <td className="py-2 pr-4">{d.currency ?? "—"}</td>
                    <td className="py-2 pr-4">
                      {d.expected_close_date
                        ? new Date(d.expected_close_date).toLocaleDateString()
                        : "—"}
                    </td>
                    <td className="py-2 pr-4">{d.source ?? "—"}</td>
                    <td className="py-2 pr-4 text-right">
                      <button
                        onClick={() => onEdit(d)}
                        className="px-2 py-1 rounded border mr-2 hover:bg-gray-50"
                      >
                        Edit
                      </button>
                      <button
                        onClick={() => onDelete(d)}
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
            <div className="text-gray-500">{pagerText}</div>
            <div className="flex gap-2">
              <button
                disabled={!hasPrev}
                onClick={() => {
                  const next = Math.max(1, page - 1);
                  setPage(next);
                  fetchDeals(next);
                }}
                className="px-3 py-1.5 rounded-md border hover:bg-gray-50 disabled:opacity-50"
              >
                ‹ Prev
              </button>
              <button
                disabled={!hasNext}
                onClick={() => {
                  const next = page + 1;
                  setPage(next);
                  fetchDeals(next);
                }}
                className="px-3 py-1.5 rounded-md border hover:bg-gray-50 disabled:opacity-50"
              >
                Next ›
              </button>
            </div>
          </div>
        </>
      )}

      {/* modal (değişmedi) */}
      {open && (
        <div className="fixed inset-0 bg-black/30 flex items-center justify-center z-50">
          <div className="bg-white w-[720px] max-w-[95vw] rounded-xl shadow p-5">
            <div className="text-lg font-semibold mb-4">
              {editing ? "Edit Opportunity" : "New Opportunity"}
            </div>

            <div className="space-y-3">
              <Field label="Name">
                <input
                  value={form.name}
                  onChange={(e) => setForm((f) => ({ ...f, name: e.target.value }))}
                  className="w-full px-3 py-2 rounded-md border text-sm"
                  placeholder="New project"
                />
              </Field>

              <div className="grid grid-cols-1 md:grid-cols-3 gap-3">
                <Field label="Amount">
                  <input
                    type="number"
                    value={form.amount}
                    onChange={(e) => setForm((f) => ({ ...f, amount: e.target.value }))}
                    className="w-full px-3 py-2 rounded-md border text-sm"
                    placeholder="10000"
                  />
                </Field>
                <Field label="Currency">
                  <input
                    value={form.currency}
                    onChange={(e) => setForm((f) => ({ ...f, currency: e.target.value }))}
                    className="w-full px-3 py-2 rounded-md border text-sm"
                    placeholder="USD"
                  />
                </Field>
                <Field label="Expected Close">
                  <input
                    type="date"
                    value={form.expected_close_date}
                    onChange={(e) =>
                      setForm((f) => ({ ...f, expected_close_date: e.target.value }))
                    }
                    className="w-full px-3 py-2 rounded-md border text-sm"
                  />
                </Field>
              </div>

              {/* Account lookup */}
              <Field label="Account">
                <input
                  value={form.account_name}
                  onChange={(e) => {
                    const val = e.target.value;
                    setForm((f) => ({ ...f, account_name: val, account_id: "" }));
                    setAccQuery(val);
                  }}
                  className="w-full px-3 py-2 rounded-md border text-sm"
                  placeholder="Type to search accounts…"
                />
                {accLoading ? (
                  <div className="text-xs text-gray-500 mt-1">Searching…</div>
                ) : accOptions.length > 0 ? (
                  <div className="mt-1 border rounded-md max-h-44 overflow-auto">
                    {accOptions.map((a) => (
                      <button
                        key={a.id}
                        type="button"
                        onClick={() => {
                          setForm((f) => ({ ...f, account_id: a.id, account_name: a.name }));
                          setAccOptions([]);
                          setAccQuery("");
                        }}
                        className="w-full text-left px-3 py-2 text-sm hover:bg-gray-50"
                      >
                        {a.name}
                        {a.industry ? (
                          <span className="text-gray-500"> — {a.industry}</span>
                        ) : null}
                      </button>
                    ))}
                  </div>
                ) : accQuery.trim().length ? (
                  <div className="text-xs text-gray-500 mt-1">No matches.</div>
                ) : null}
                {!form.account_id && (
                  <div className="text-xs text-amber-600 mt-1">Account is required.</div>
                )}
              </Field>

              {/* Stage dropdown */}
              <Field label="Stage">
                <select
                  value={form.stage_id}
                  onChange={(e) =>
                    setForm((f) => ({
                      ...f,
                      stage_id: e.target.value === "" ? "" : Number(e.target.value),
                    }))
                  }
                  className="w-full px-3 py-2 rounded-md border text-sm bg-white"
                >
                  <option value="">(Default pipeline first stage)</option>
                  {stages.map((s) => (
                    <option key={s.id} value={s.id}>
                      {s.no}. {s.name}
                    </option>
                  ))}
                </select>
              </Field>

              <div className="text-xs text-gray-500">
                {editing ? (
                  <>
                    Owner: <b>{form.owner_email_hint ?? "—"}</b>
                  </>
                ) : (
                  <>
                    Owner: <b>bu kaydı oluşturan kullanıcı</b> olacaktır.
                  </>
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
