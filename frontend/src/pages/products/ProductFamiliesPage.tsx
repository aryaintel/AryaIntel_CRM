// src/pages/products/ProductFamiliesPage.tsx
import React, { useEffect, useMemo, useState } from "react";
import { apiGet, apiPost, apiPut, apiDelete } from "../../lib/api";

/**
 * ProductFamiliesPage — Salesforce-style CRUD for Tender categories
 * ----------------------------------------------------------------
 * DB: product_families (id, name, description, is_active)
 * Endpoints (auto-discovery):
 *   - Primary:   /api/product-families
 *   - Fallbacks: /api/product_families, /api/products/families
 * Behavior:
 *   - List & search
 *   - Create / Edit (name, description, active)
 *   - Activate/Deactivate, Delete
 */

type Family = {
  id?: number;
  name: string;
  description?: string | null;
  is_active: boolean;
};

function unwrapList<T = any>(res: any): T[] {
  if (Array.isArray(res)) return res as T[];
  if (res?.items && Array.isArray(res.items)) return res.items as T[];
  if (res?.data && Array.isArray(res.data)) return res.data as T[];
  if (res?.results && Array.isArray(res.results)) return res.results as T[];
  return [];
}
function toBool(x: any): boolean {
  if (typeof x === "boolean") return x;
  if (typeof x === "number") return x !== 0;
  if (typeof x === "string") return x === "1" || x.toLowerCase() === "true";
  return !!x;
}

/* ---------- helpers ---------- */
function cleanName(v: any): string {
  return String(v ?? "").trim();
}
function cleanDesc(v: any): string | null {
  const s = String(v ?? "").trim();
  return s.length ? s : null;
}

export default function ProductFamiliesPage() {
  const [baseUrl, setBaseUrl] = useState<string | null>(null);
  const [rows, setRows] = useState<Family[]>([]);
  const [q, setQ] = useState("");
  const [busy, setBusy] = useState<string | null>(null);
  const [err, setErr] = useState<string | null>(null);

  const [selected, setSelected] = useState<Family | null>(null);
  // IMPORTANT: allow partial while editing to avoid TS complaints when starting from null
  const [editing, setEditing] = useState<Partial<Family> | null>(null);

  // ---------- discovery + load ----------
  useEffect(() => {
    (async () => {
      setBusy("discover");
      setErr(null);
      const candidates = [
        "/api/product-families",
        "/api/product_families",
        "/api/products/families",
      ];
      for (const url of candidates) {
        try {
          const res = await apiGet(url);
          setBaseUrl(url.replace(/\?.*$/, "")); // store clean base
          setRows(normalizeList(res));
          setBusy(null);
          return;
        } catch {
          /* try next */
        }
      }
      setBusy(null);
      setErr("No product-families endpoint found");
    })();
  }, []);

  function normalizeList(res: any): Family[] {
    return unwrapList<Family>(res).map((f: any) => ({
      id: f.id,
      name: f.name ?? "",
      description: f.description ?? null,
      is_active: toBool(f.is_active ?? true),
    }));
  }

  async function reload() {
    if (!baseUrl) return;
    const res = await apiGet(baseUrl);
    setRows(normalizeList(res));
  }

  // ---------- derived ----------
  const filtered = useMemo(() => {
    const t = q.toLowerCase().trim();
    if (!t) return rows;
    return rows.filter(
      (r) =>
        r.name.toLowerCase().includes(t) ||
        (r.description ?? "").toLowerCase().includes(t)
    );
  }, [rows, q]);

  // ---------- mutations ----------
  async function createFamily() {
    if (!baseUrl || !editing) return;
    const name = cleanName(editing.name);
    if (!name) {
      alert("Name is required");
      return;
    }
    setBusy("create");
    setErr(null);
    try {
      const payload = {
        name,
        description: cleanDesc(editing.description),
        // ✅ send boolean; do NOT coerce other fields
        is_active: editing.is_active ?? true,
      };
      await apiPost(baseUrl, payload);
      await reload();
      setEditing(null);
    } catch (e: any) {
      setErr(e?.message || String(e));
    } finally {
      setBusy(null);
    }
  }

  async function updateFamily(f: Family) {
    if (!baseUrl || !f.id) return;
    setBusy(`update-${f.id}`);
    setErr(null);
    try {
      const payload = {
        name: cleanName(f.name),
        description: cleanDesc(f.description),
        // ✅ boolean only
        is_active: !!f.is_active,
      };
      await apiPut(`${baseUrl}/${f.id}`, payload);
      await reload();
    } catch (e: any) {
      setErr(e?.message || String(e));
    } finally {
      setBusy(null);
    }
  }

  async function removeFamily(f: Family) {
    if (!baseUrl || !f.id) return;
    if (!confirm(`Delete ${f.name}?`)) return;
    setBusy(`delete-${f.id}`);
    setErr(null);
    try {
      await apiDelete(`${baseUrl}/${f.id}`);
      await reload();
      if (selected?.id === f.id) setSelected(null);
    } catch (e: any) {
      setErr(e?.message || String(e));
    } finally {
      setBusy(null);
    }
  }

  // ---------- render ----------
  return (
    <div className="space-y-4">
      {/* Header */}
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-semibold text-gray-900">Product Families</h1>
          <p className="text-sm text-gray-600">
            Tender categories (e.g., Ammonium Nitrate Emulsion) used to group products.
          </p>
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

      <div className="grid grid-cols-1 xl:grid-cols-3 gap-4">
        {/* Left: Create + List */}
        <div className="xl:col-span-1 space-y-4">
          {/* Create */}
          <div className="bg-white border rounded-2xl shadow-sm">
            <div className="px-4 py-3 border-b">
              <h2 className="font-medium">New Family</h2>
            </div>
            <div className="p-4 space-y-3">
              <label className="block text-xs text-gray-600">
                Name
                <input
                  className="mt-1 w-full rounded-lg border px-3 py-2 text-sm"
                  placeholder="Ammonium Nitrate Emulsion"
                  value={editing?.name ?? ""}
                  onChange={(e) =>
                    setEditing((prev) => ({
                      ...(prev ?? { is_active: true }),
                      name: e.target.value,
                    }))
                  }
                />
              </label>
              <label className="block text-xs text-gray-600">
                Description
                <textarea
                  className="mt-1 w-full rounded-lg border px-3 py-2 text-sm"
                  rows={3}
                  placeholder="Used for bulk emulsion formulations…"
                  value={editing?.description ?? ""}
                  onChange={(e) =>
                    setEditing((prev) => ({
                      ...(prev ?? { is_active: true, name: "" }),
                      description: e.target.value,
                    }))
                  }
                />
              </label>
              <label className="inline-flex items-center gap-2 text-sm">
                <input
                  type="checkbox"
                  checked={editing?.is_active ?? true}
                  onChange={(e) =>
                    setEditing((prev) => ({
                      ...(prev ?? { name: "", description: "" }),
                      is_active: e.target.checked,
                    }))
                  }
                />
                Active
              </label>
              <div className="flex gap-2">
                <button
                  onClick={createFamily}
                  disabled={!(editing?.name ?? "").trim() || busy === "create" || !baseUrl}
                  className="inline-flex items-center justify-center rounded-lg bg-indigo-600 text-white text-sm px-3 py-2 hover:bg-indigo-700 disabled:opacity-50"
                >
                  Add Family
                </button>
                <button
                  onClick={() => setEditing(null)}
                  className="px-3 py-2 text-sm rounded-lg border hover:bg-gray-50"
                >
                  Clear
                </button>
              </div>
            </div>
          </div>

          {/* List */}
          <div className="bg-white border rounded-2xl shadow-sm">
            <div className="px-4 py-3 border-b flex items-center justify-between">
              <h2 className="font-medium">Families</h2>
              <input
                className="text-sm border rounded px-2 py-1"
                placeholder="Search…"
                value={q}
                onChange={(e) => setQ(e.target.value)}
              />
            </div>
            <div>
              {rows.length === 0 ? (
                <div className="p-4 text-sm text-gray-600">No families yet.</div>
              ) : (
                <ul className="divide-y">
                  {filtered.map((f) => {
                    const active = selected?.id === f.id;
                    return (
                      <li
                        key={f.id}
                        className={`p-4 cursor-pointer ${active ? "bg-indigo-50" : "bg-white"}`}
                        onClick={() => setSelected(f)}
                      >
                        <div className="flex items-center justify-between">
                          <div>
                            <div className="font-medium">{f.name}</div>
                            <div className="text-xs text-gray-600">{f.is_active ? "Active" : "Inactive"}</div>
                            {f.description ? (
                              <div className="text-xs text-gray-500 mt-1">{f.description}</div>
                            ) : null}
                          </div>
                          <div className="flex gap-2">
                            <button
                              onClick={(e) => {
                                e.stopPropagation();
                                setSelected(f);
                                setEditing({ ...f });
                              }}
                              className="px-2 py-1 text-xs rounded border hover:bg-gray-50"
                            >
                              Edit
                            </button>
                            <button
                              onClick={(e) => {
                                e.stopPropagation();
                                updateFamily({ ...f, is_active: !f.is_active });
                              }}
                              className="px-2 py-1 text-xs rounded border hover:bg-gray-50"
                            >
                              {f.is_active ? "Deactivate" : "Activate"}
                            </button>
                            <button
                              onClick={(e) => {
                                e.stopPropagation();
                                removeFamily(f);
                              }}
                              className="px-2 py-1 text-xs rounded border text-rose-600 hover:bg-rose-50"
                            >
                              Delete
                            </button>
                          </div>
                        </div>
                      </li>
                    );
                  })}
                </ul>
              )}
            </div>
          </div>
        </div>

        {/* Right: Details (update) */}
        <div className="xl:col-span-2">
          <div className="bg-white border rounded-2xl shadow-sm">
            <div className="px-4 py-3 border-b">
              <h2 className="font-medium">Details</h2>
            </div>
            {selected ? (
              <div className="p-4 space-y-4">
                <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
                  <label className="block text-xs text-gray-600">
                    Name
                    <input
                      className="mt-1 w-full rounded-lg border px-3 py-2 text-sm"
                      value={selected.name}
                      onChange={(e) =>
                        setSelected({ ...selected, name: e.target.value })
                      }
                    />
                  </label>
                  <label className="block text-xs text-gray-600">
                    Active
                    <div className="mt-2">
                      <input
                        type="checkbox"
                        checked={selected.is_active}
                        onChange={(e) =>
                          setSelected({ ...selected, is_active: e.target.checked })
                        }
                      />
                      <span className="ml-2 text-sm">
                        {selected.is_active ? "Yes" : "No"}
                      </span>
                    </div>
                  </label>
                  <label className="block text-xs text-gray-600 md:col-span-2">
                    Description
                    <textarea
                      className="mt-1 w-full rounded-lg border px-3 py-2 text-sm"
                      rows={4}
                      value={selected.description ?? ""}
                      onChange={(e) =>
                        setSelected({ ...selected, description: e.target.value })
                      }
                    />
                  </label>
                </div>
                <div className="flex gap-2">
                  <button
                    onClick={() => updateFamily(selected)}
                    disabled={busy?.startsWith("update-") || !baseUrl}
                    className="inline-flex items-center rounded-lg bg-indigo-600 text-white text-sm px-3 py-2 hover:bg-indigo-700 disabled:opacity-50"
                  >
                    {busy?.startsWith("update-") ? "Saving…" : "Save changes"}
                  </button>
                  <button
                    onClick={() => setSelected(null)}
                    className="px-3 py-2 text-sm rounded-lg border hover:bg-gray-50"
                  >
                    Close
                  </button>
                </div>
              </div>
            ) : (
              <div className="p-6 text-sm text-gray-600">
                Select a family on the left to see details.
              </div>
            )}
          </div>
        </div>
      </div>
    </div>
  );
}
