// [BEGIN FILE] src/pages/products/PriceTermsPage.tsx
import React, { useEffect, useMemo, useState } from "react";
import { apiGet, apiPost, apiPut, apiDelete } from "../../lib/api";

// ---------------- Types ----------------
type PriceTerm = {
  id?: number;
  code: string;
  name?: string | null;
  description?: string | null;
  notes?: string | null;
  default_days?: number | null;
  is_active: boolean | number;
  created_at?: string | null;
  updated_at?: string | null;
};

// -------------- Utils --------------
function toBool(x: any): boolean {
  if (typeof x === "boolean") return x;
  if (typeof x === "number") return x !== 0;
  if (typeof x === "string") return x === "1" || x.toLowerCase() === "true";
  return !!x;
}
function unwrapList<T = any>(res: any): T[] {
  if (Array.isArray(res)) return res;
  if (res?.items && Array.isArray(res.items)) return res.items;
  if (res?.data && Array.isArray(res.data)) return res.data;
  if (res?.results && Array.isArray(res.results)) return res.results;
  return [];
}
async function discoverBase(paths: string[]): Promise<string> {
  for (const p of paths) {
    try {
      await apiGet(p + "?limit=1&offset=0"); // cheap probe
      return p;
    } catch {}
  }
  throw new Error("PriceTerms endpoint not found");
}
function normalize(t: any): PriceTerm {
  return {
    id: t.id,
    code: t.code ?? "",
    name: t.name ?? null,
    description: t.description ?? null,
    notes: t.notes ?? null,
    default_days: t.default_days ?? t.defaultDays ?? null,
    is_active: toBool(t.is_active ?? t.isActive ?? true),
    created_at: t.created_at ?? null,
    updated_at: t.updated_at ?? null,
  };
}

// -------------- Page --------------
export default function PriceTermsPage() {
  // discovery
  const [base, setBase] = useState<string | null>(null);

  // list/query
  const [terms, setTerms] = useState<PriceTerm[]>([]);
  const [q, setQ] = useState<string>("");
  const [onlyActive, setOnlyActive] = useState<boolean | "all">("all");
  const [busy, setBusy] = useState<string | null>(null);
  const [err, setErr] = useState<string | null>(null);

  // selection
  const [selectedId, setSelectedId] = useState<number | null>(null);
  const selected = useMemo(
    () => terms.find((t) => t.id === selectedId) ?? null,
    [terms, selectedId]
  );

  // create draft
  const [draft, setDraft] = useState<PriceTerm>({
    code: "",
    name: "",
    description: "",
    notes: "",
    default_days: null,
    is_active: true,
  });

  // initial discovery
  useEffect(() => {
    (async () => {
      setBusy("discover");
      setErr(null);
      try {
        const b = await discoverBase(["/api/price-terms", "/api/price_terms"]);
        setBase(b);
      } catch (e: any) {
        setErr(e?.message || String(e));
      } finally {
        setBusy(null);
      }
    })();
  }, []);

  // load list
  useEffect(() => {
    if (!base) return;
    (async () => {
      setBusy("load");
      setErr(null);
      try {
        const params = new URLSearchParams();
        params.set("limit", "500");
        params.set("offset", "0");
        if (q) params.set("q", q);
        if (onlyActive !== "all") params.set("active", onlyActive ? "1" : "0");
        const res = await apiGet(`${base}?${params.toString()}`);
        setTerms(unwrapList<PriceTerm>(res).map(normalize));
        // keep selection valid
        setSelectedId((prev) => {
          if (!prev) return null;
          return unwrapList<PriceTerm>(res).some((x: any) => x.id === prev) ? prev : null;
        });
      } catch (e: any) {
        setErr(e?.message || String(e));
      } finally {
        setBusy(null);
      }
    })();
  }, [base, q, onlyActive]);

  async function reload() {
    if (!base) return;
    const params = new URLSearchParams();
    params.set("limit", "500");
    params.set("offset", "0");
    if (q) params.set("q", q);
    if (onlyActive !== "all") params.set("active", onlyActive ? "1" : "0");
    const res = await apiGet(`${base}?${params.toString()}`);
    setTerms(unwrapList<PriceTerm>(res).map(normalize));
  }

  // ---------- CRUD ----------
  async function createTerm() {
    if (!base) return;
    if (!draft.code.trim()) {
      alert("Code is required");
      return;
    }
    setBusy("create");
    setErr(null);
    try {
      const body = {
        code: draft.code.trim(),
        name: (draft.name ?? "").trim() || null,
        description: (draft.description ?? "").trim() || null,
        notes: (draft.notes ?? "").trim() || null,
        default_days: draft.default_days ?? null,
        is_active: draft.is_active ? 1 : 0,
      };
      await apiPost(base, body);
      setDraft({ code: "", name: "", description: "", notes: "", default_days: null, is_active: true });
      await reload();
    } catch (e: any) {
      setErr(e?.message || String(e));
    } finally {
      setBusy(null);
    }
  }

  async function saveRow(row: PriceTerm) {
    if (!base || !row.id) return;
    setBusy(`update-${row.id}`);
    setErr(null);
    try {
      const body = {
        code: row.code,
        name: row.name ?? null,
        description: row.description ?? null,
        notes: row.notes ?? null,
        default_days: row.default_days ?? null,
        is_active: row.is_active ? 1 : 0,
      };
      await apiPut(`${base}/${row.id}`, body);
      await reload();
    } catch (e: any) {
      setErr(e?.message || String(e));
    } finally {
      setBusy(null);
    }
  }

  async function deleteRow(row: PriceTerm) {
    if (!base || !row.id) return;
    if (!confirm("Delete this price term?")) return;
    setBusy(`delete-${row.id}`);
    setErr(null);
    try {
      await apiDelete(`${base}/${row.id}`);
      await reload();
      if (selectedId === row.id) setSelectedId(null);
    } catch (e: any) {
      setErr(e?.message || String(e));
    } finally {
      setBusy(null);
    }
  }

  // ---------- Render ----------
  return (
    <div className="space-y-4">
      {/* Header */}
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-semibold text-gray-900">Price Terms</h1>
          <p className="text-sm text-gray-600">Define reusable commercial terms (e.g., EXW, CIF, NET30) and reuse them across Price Books & BOQ.</p>
        </div>
        <div className="text-sm text-gray-600">
          {busy ? (
            <span className="px-2 py-1 rounded bg-amber-50 text-amber-700 border border-amber-200">
              Working: {busy}
            </span>
          ) : null}
          {err ? (
            <span className="ml-2 px-2 py-1 rounded bg-rose-50 text-rose-700 border border-rose-200">
              Error: {err}
            </span>
          ) : null}
        </div>
      </div>

      {/* Toolbar */}
      <div className="bg-white border rounded-2xl shadow-sm p-4">
        <div className="grid grid-cols-1 md:grid-cols-3 gap-3">
          <div className="md:col-span-2 flex gap-3">
            <input
              className="w-full rounded-lg border px-3 py-2 text-sm"
              placeholder="Search (code, name, description)…"
              value={q}
              onChange={(e) => setQ(e.target.value)}
            />
            <select
              className="w-40 rounded-lg border px-3 py-2 text-sm"
              value={String(onlyActive)}
              onChange={(e) => {
                const v = e.target.value;
                setOnlyActive(v === "all" ? "all" : v === "true");
              }}
            >
              <option value="all">All</option>
              <option value="true">Active</option>
              <option value="false">Inactive</option>
            </select>
          </div>
          <div className="flex md:justify-end">
            <button
              onClick={reload}
              className="inline-flex items-center rounded-lg border px-3 py-2 text-sm hover:bg-gray-50"
            >
              Refresh
            </button>
          </div>
        </div>
      </div>

      {/* Create card */}
      <div className="bg-white border rounded-2xl shadow-sm">
        <div className="px-4 py-3 border-b">
          <h2 className="font-medium">New Price Term</h2>
        </div>
        <div className="p-4 space-y-3">
          <div className="grid grid-cols-1 md:grid-cols-6 gap-3">
            <div className="md:col-span-2">
              <label className="block text-xs text-gray-600 mb-1">Code *</label>
              <input
                className="w-full rounded-lg border px-3 py-2 text-sm"
                placeholder="e.g., EXW, CIF, NET30"
                value={draft.code}
                onChange={(e) => setDraft({ ...draft, code: e.target.value })}
              />
            </div>
            <div className="md:col-span-2">
              <label className="block text-xs text-gray-600 mb-1">Name</label>
              <input
                className="w-full rounded-lg border px-3 py-2 text-sm"
                placeholder="Friendly name (optional)"
                value={draft.name ?? ""}
                onChange={(e) => setDraft({ ...draft, name: e.target.value })}
              />
            </div>
            <div className="md:col-span-1">
              <label className="block text-xs text-gray-600 mb-1">Default Days</label>
              <input
                type="number"
                className="w-full rounded-lg border px-3 py-2 text-sm"
                placeholder="e.g., 30"
                value={draft.default_days ?? ""}
                onChange={(e) =>
                  setDraft({
                    ...draft,
                    default_days: e.target.value === "" ? null : Number(e.target.value),
                  })
                }
              />
            </div>
            <div className="md:col-span-1 flex items-end">
              <label className="inline-flex items-center gap-2 text-sm">
                <input
                  type="checkbox"
                  checked={toBool(draft.is_active)}
                  onChange={(e) => setDraft({ ...draft, is_active: e.target.checked })}
                />
                Active
              </label>
            </div>
            <div className="md:col-span-3">
              <label className="block text-xs text-gray-600 mb-1">Description</label>
              <input
                className="w-full rounded-lg border px-3 py-2 text-sm"
                value={draft.description ?? ""}
                onChange={(e) => setDraft({ ...draft, description: e.target.value })}
              />
            </div>
            <div className="md:col-span-3">
              <label className="block text-xs text-gray-600 mb-1">Notes</label>
              <input
                className="w-full rounded-lg border px-3 py-2 text-sm"
                value={draft.notes ?? ""}
                onChange={(e) => setDraft({ ...draft, notes: e.target.value })}
              />
            </div>
          </div>
          <button
            onClick={createTerm}
            disabled={busy === "create" || !draft.code.trim()}
            className="inline-flex items-center rounded-lg bg-indigo-600 text-white text-sm px-3 py-2 hover:bg-indigo-700 disabled:opacity-50"
          >
            {busy === "create" ? "Saving…" : "Add Price Term"}
          </button>
        </div>
      </div>

      {/* List card */}
      <div className="bg-white border rounded-2xl shadow-sm">
        <div className="px-4 py-3 border-b">
          <h2 className="font-medium">Price Terms</h2>
        </div>
        <div className="overflow-auto">
          <table className="min-w-full text-sm">
            <thead className="bg-gray-50">
              <tr className="text-left">
                <th className="px-3 py-2 font-medium">Code</th>
                <th className="px-3 py-2 font-medium">Name</th>
                <th className="px-3 py-2 font-medium">Default Days</th>
                <th className="px-3 py-2 font-medium">Active</th>
                <th className="px-3 py-2 font-medium">Description</th>
                <th className="px-3 py-2 font-medium">Notes</th>
                <th className="px-3 py-2"></th>
              </tr>
            </thead>
            <tbody className="divide-y">
              {terms.length === 0 ? (
                <tr>
                  <td className="px-3 py-3 text-gray-600" colSpan={7}>
                    No price terms found.
                  </td>
                </tr>
              ) : (
                terms.map((t) => (
                  <Row
                    key={t.id}
                    row={t}
                    onSave={saveRow}
                    onDelete={deleteRow}
                    selected={selectedId === t.id}
                    onSelect={() => setSelectedId(t.id ?? null)}
                  />
                ))
              )}
            </tbody>
          </table>
        </div>
      </div>
    </div>
  );
}

// -------------- Row --------------
function Row({
  row,
  onSave,
  onDelete,
  selected,
  onSelect,
}: {
  row: PriceTerm;
  onSave: (row: PriceTerm) => void;
  onDelete: (row: PriceTerm) => void;
  selected: boolean;
  onSelect: () => void;
}) {
  const [edit, setEdit] = useState<PriceTerm>({ ...row });

  // keep local edit in sync on external changes
  useEffect(() => setEdit({ ...row }), [row]);

  return (
    <tr className={`align-middle ${selected ? "bg-indigo-50" : ""}`} onClick={onSelect}>
      <td className="px-3 py-2">
        <input
          className="w-36 rounded-lg border px-3 py-2 text-sm"
          value={edit.code}
          onChange={(e) => setEdit({ ...edit, code: e.target.value })}
        />
      </td>
      <td className="px-3 py-2">
        <input
          className="w-44 rounded-lg border px-3 py-2 text-sm"
          value={edit.name ?? ""}
          onChange={(e) => setEdit({ ...edit, name: e.target.value })}
        />
      </td>
      <td className="px-3 py-2">
        <input
          type="number"
          className="w-24 rounded-lg border px-3 py-2 text-sm"
          value={edit.default_days ?? ""}
          onChange={(e) =>
            setEdit({
              ...edit,
              default_days: e.target.value === "" ? null : Number(e.target.value),
            })
          }
        />
      </td>
      <td className="px-3 py-2">
        <input
          type="checkbox"
          checked={!!edit.is_active}
          onChange={(e) => setEdit({ ...edit, is_active: e.target.checked })}
        />
      </td>
      <td className="px-3 py-2">
        <input
          className="w-72 rounded-lg border px-3 py-2 text-sm"
          value={edit.description ?? ""}
          onChange={(e) => setEdit({ ...edit, description: e.target.value })}
        />
      </td>
      <td className="px-3 py-2">
        <input
          className="w-72 rounded-lg border px-3 py-2 text-sm"
          value={edit.notes ?? ""}
          onChange={(e) => setEdit({ ...edit, notes: e.target.value })}
        />
      </td>
      <td className="px-3 py-2 whitespace-nowrap">
        <button
          onClick={(e) => { e.stopPropagation(); onSave(edit); }}
          className="mr-2 px-3 py-2 text-sm rounded-lg border hover:bg-gray-50"
        >
          Save
        </button>
        <button
          onClick={(e) => { e.stopPropagation(); onDelete(row); }}
          className="px-3 py-2 text-sm rounded-lg border text-rose-600 hover:bg-rose-50"
        >
          Delete
        </button>
      </td>
    </tr>
  );
}
// [END FILE]
