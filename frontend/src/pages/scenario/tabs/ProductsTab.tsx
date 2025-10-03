// Products Tab — Arya CRM (single-file)
// List + search + create/edit + archive/delete with first-success API helpers

import React, { useEffect, useMemo, useState } from "react";
import { apiGet, apiPost, apiPut } from "../../../lib/api";

type Product = {
  id: number;
  code: string;
  name: string;
  currency?: string | null;
  uom?: string | null;
  is_active?: boolean | null;
  // created_at/updated_at vb. varsa UI göstermiyoruz ama alıp taşıyabiliriz
};

type EditDraft = {
  id?: number | null;
  code: string;
  name: string;
  currency?: string | null;
  uom?: string | null;
  is_active?: boolean;
};

function cls(...a: Array<string | false | undefined>) {
  return a.filter(Boolean).join(" ");
}

// -------- generic GET with fallbacks
async function getAny<T = any>(paths: string[]): Promise<T> {
  let last: any;
  for (const p of paths) {
    try { return await apiGet<T>(p); } catch (e) { last = e; }
  }
  throw last || new Error("No endpoint matched");
}
// -------- generic POST with fallbacks
async function postAny<T = any>(paths: string[], body: any): Promise<T> {
  let last: any;
  for (const p of paths) {
    try { return await apiPost<T>(p, body); } catch (e) { last = e; }
  }
  throw last || new Error("No POST endpoint matched");
}
// -------- generic PUT/DELETE with fallbacks
async function putAny<T = any>(paths: string[], body: any): Promise<T> {
  let last: any;
  for (const p of paths) {
    try { return await apiPut<T>(p, body); } catch (e) { last = e; }
  }
  throw last || new Error("No PUT endpoint matched");
}
// A few APIs expose DELETE via PUT with payload { archived: true } — destekleyelim
async function deleteAny(paths: string[]) {
  let last: any;
  for (const p of paths) {
    try {
      // api lib’inde delete yoksa PUT ile soft delete dene
      await apiPut(p, { _method: "DELETE" });
      return;
    } catch (e) { last = e; }
  }
  throw last || new Error("No DELETE endpoint matched");
}

export default function ProductsTab() {
  const [items, setItems] = useState<Product[]>([]);
  const [loading, setLoading] = useState(true);
  const [err, setErr] = useState<string | null>(null);

  const [q, setQ] = useState("");
  const [draft, setDraft] = useState<EditDraft | null>(null);
  const [busy, setBusy] = useState(false);
  const [toast, setToast] = useState<{ ok?: string; err?: string } | null>(null);

  const filtered = useMemo(() => {
    const t = q.trim().toLowerCase();
    if (!t) return items;
    return items.filter(
      (p) =>
        (p.name || "").toLowerCase().includes(t) ||
        (p.code || "").toLowerCase().includes(t) ||
        (p.currency || "").toLowerCase().includes(t) ||
        (p.uom || "").toLowerCase().includes(t)
    );
  }, [items, q]);

  useEffect(() => {
    (async () => {
      setLoading(true);
      setErr(null);
      try {
        const res: any = await getAny<any>([
          "/api/products?limit=1000&offset=0",
          "/products?limit=1000&offset=0",
        ]);
        const list: Product[] = Array.isArray(res) ? res : res.items ?? res.data ?? [];
        setItems(list);
      } catch (e: any) {
        setErr(e?.message || "Failed to load products.");
      } finally {
        setLoading(false);
      }
    })();
  }, []);

  function openNew() {
    setDraft({ id: null, code: "", name: "", currency: "", uom: "", is_active: true });
  }
  function openEdit(p: Product) {
    setDraft({
      id: p.id,
      code: p.code || "",
      name: p.name || "",
      currency: p.currency || "",
      uom: p.uom || "",
      is_active: p.is_active ?? true,
    });
  }
  function closeEditor() {
    setDraft(null);
  }

  async function save() {
    if (!draft) return;
    if (!draft.code?.trim() || !draft.name?.trim()) {
      setToast({ err: "Code ve Name zorunludur." });
      return;
    }
    setBusy(true);
    setToast(null);
    try {
      const payload = {
        code: draft.code.trim(),
        name: draft.name.trim(),
        currency: (draft.currency || "") || null,
        uom: (draft.uom || "") || null,
        is_active: draft.is_active ?? true,
      };

      if (draft.id) {
        // UPDATE
        const updated: any = await putAny<any>(
          [`/api/products/${draft.id}`, `/products/${draft.id}`],
          payload
        );
        // optimistic update
        setItems((prev) =>
          prev.map((it) => (it.id === draft.id ? { ...it, ...payload } as Product : it))
        );
        setToast({ ok: "Product updated." });
      } else {
        // CREATE
        const created: any = await postAny<any>(["/api/products", "/products"], payload);
        const id = created?.id || created?.data?.id || created?.product_id;
        const newItem: Product = { id: id ?? Math.random(), ...payload } as Product;
        setItems((prev) => [newItem, ...prev]);
        setToast({ ok: "Product created." });
      }
      closeEditor();
    } catch (e: any) {
      const msg = e?.response?.data?.detail || e?.message || "Save failed.";
      setToast({ err: String(msg) });
    } finally {
      setBusy(false);
    }
  }

  async function archive(p: Product, value: boolean) {
    setBusy(true);
    setToast(null);
    try {
      await putAny<any>([`/api/products/${p.id}`, `/products/${p.id}`], { is_active: !value });
      setItems((prev) => prev.map((it) => (it.id === p.id ? { ...it, is_active: !value } : it)));
      setToast({ ok: value ? "Archived." : "Restored." });
    } catch (e: any) {
      setToast({ err: e?.response?.data?.detail || e?.message || "Operation failed." });
    } finally {
      setBusy(false);
    }
  }

  async function remove(p: Product) {
    if (!confirm(`Delete product ${p.code}?`)) return;
    setBusy(true);
    setToast(null);
    try {
      await deleteAny([`/api/products/${p.id}`, `/products/${p.id}`]);
      setItems((prev) => prev.filter((it) => it.id !== p.id));
      setToast({ ok: "Deleted." });
    } catch (e: any) {
      setToast({ err: e?.response?.data?.detail || e?.message || "Delete failed." });
    } finally {
      setBusy(false);
    }
  }

  if (loading) return <div>Loading…</div>;
  if (err) return <div className="text-red-600">{err}</div>;

  return (
    <div className="space-y-4">
      <header className="flex items-center justify-between">
        <h2 className="text-lg font-semibold">Products</h2>
        <div className="flex items-center gap-2">
          <input
            value={q}
            onChange={(e) => setQ(e.target.value)}
            placeholder="Search code / name / currency / uom…"
            className="border rounded px-2 py-1 text-sm w-72"
          />
          <button onClick={openNew} className="px-3 py-1.5 rounded-md border text-sm hover:bg-gray-50">
            + New Product
          </button>
        </div>
      </header>

      {toast && (
        <div
          className={cls(
            "text-sm px-2 py-1 rounded border",
            toast.ok ? "text-green-700 bg-green-50 border-green-300" : "text-red-700 bg-red-50 border-red-300"
          )}
        >
          {toast.ok || toast.err}
        </div>
      )}

      {/* List */}
      <div className="border rounded-xl overflow-hidden bg-white">
        <table className="w-full text-sm">
          <thead className="bg-gray-50">
            <tr>
              <th className="text-left p-2 w-28">Code</th>
              <th className="text-left p-2">Name</th>
              <th className="text-left p-2 w-24">Currency</th>
              <th className="text-left p-2 w-24">UoM</th>
              <th className="text-left p-2 w-20">Active</th>
              <th className="text-right p-2 w-40">Actions</th>
            </tr>
          </thead>
          <tbody>
            {filtered.length === 0 && (
              <tr>
                <td colSpan={6} className="p-4 text-center text-gray-500">
                  No products found.
                </td>
              </tr>
            )}
            {filtered.map((p) => (
              <tr key={p.id} className="border-t">
                <td className="p-2 font-mono">{p.code}</td>
                <td className="p-2">{p.name}</td>
                <td className="p-2">{p.currency || "—"}</td>
                <td className="p-2">{p.uom || "—"}</td>
                <td className="p-2">{p.is_active === false ? "No" : "Yes"}</td>
                <td className="p-2 text-right">
                  <div className="inline-flex gap-2">
                    <button className="px-2 py-1 rounded border text-xs hover:bg-gray-50" onClick={() => openEdit(p)}>
                      Edit
                    </button>
                    <button
                      className="px-2 py-1 rounded border text-xs hover:bg-gray-50"
                      onClick={() => archive(p, p.is_active === false)}
                    >
                      {p.is_active === false ? "Restore" : "Archive"}
                    </button>
                    <button className="px-2 py-1 rounded border text-xs hover:bg-red-50" onClick={() => remove(p)}>
                      Delete
                    </button>
                  </div>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      {/* Drawer / Modal-like editor (simple inline card) */}
      {draft && (
        <div className="border rounded-xl p-4 bg-white">
          <div className="flex items-center justify-between mb-3">
            <div className="font-semibold">{draft.id ? "Edit Product" : "New Product"}</div>
            <button onClick={closeEditor} className="px-2 py-1 rounded border text-xs hover:bg-gray-50">
              Close
            </button>
          </div>
          <div className="grid grid-cols-5 gap-3 text-sm">
            <label className="flex flex-col">
              <span className="text-gray-600">Code *</span>
              <input
                value={draft.code}
                onChange={(e) => setDraft({ ...(draft as EditDraft), code: e.target.value })}
                className="border rounded px-2 py-1"
              />
            </label>
            <label className="flex flex-col col-span-2">
              <span className="text-gray-600">Name *</span>
              <input
                value={draft.name}
                onChange={(e) => setDraft({ ...(draft as EditDraft), name: e.target.value })}
                className="border rounded px-2 py-1"
              />
            </label>
            <label className="flex flex-col">
              <span className="text-gray-600">Currency</span>
              <input
                value={draft.currency || ""}
                onChange={(e) => setDraft({ ...(draft as EditDraft), currency: e.target.value })}
                className="border rounded px-2 py-1"
                placeholder="USD, EUR, TRY…"
              />
            </label>
            <label className="flex flex-col">
              <span className="text-gray-600">UoM</span>
              <input
                value={draft.uom || ""}
                onChange={(e) => setDraft({ ...(draft as EditDraft), uom: e.target.value })}
                className="border rounded px-2 py-1"
                placeholder="unit, kg, hour…"
              />
            </label>
            <label className="flex items-center gap-2 col-span-5">
              <input
                type="checkbox"
                checked={draft.is_active !== false}
                onChange={(e) => setDraft({ ...(draft as EditDraft), is_active: e.target.checked })}
              />
              <span>Active</span>
            </label>
          </div>
          <div className="mt-3">
            <button
              disabled={busy}
              onClick={save}
              className={cls(
                "px-3 py-1.5 rounded-md border text-sm",
                busy ? "opacity-60 cursor-not-allowed" : "hover:bg-gray-50"
              )}
            >
              {draft.id ? "Save Changes" : "Create Product"}
            </button>
          </div>
        </div>
      )}
    </div>
  );
}
