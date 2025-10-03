import { useEffect, useMemo, useState } from "react";
import { apiGet, apiPost, apiPatch, apiDelete, ApiError } from "../lib/api";

/* ================================
   Types
================================ */
type Role = {
  id: number | string;
  tenant_id?: number;
  name: string;
  permissions?: string | null; // "accounts:read,contacts:read"
};

type RolesPayload =
  | Role[]
  | {
      items?: Role[];
      meta?: unknown;
    };

/* ================================
   Permission Matrix (UI)
   - Resources: satırlar
   - Actions: sütunlar (label -> tokens mapping)
   - BE eşleşmesi:
       read   -> `${res}:read`
       write  -> `${res}:write`       (update + delete sunucuda 'write' ile korunuyor)
       delete -> `${res}:write` + `${res}:delete`  (opsiyonel; BE 'delete' aramasa da sorun yok)
       create -> `${res}:create`
================================ */
const RESOURCES = [
  "accounts",
  "contacts",
  "deals",
  "leads",     // ← EKLENDİ
  "users",
  "roles",
  "secure",
] as const;

type ActionKey = "read" | "write" | "delete" | "create";

const ACTIONS: { key: ActionKey; label: string; toTokens: (res: string) => string[] }[] =
  [
    { key: "read", label: "Read", toTokens: (r) => [`${r}:read`] },
    { key: "write", label: "Write", toTokens: (r) => [`${r}:write`] },
    {
      key: "delete",
      label: "Delete",
      // Delete: BE genelde :write ile kontrol ediyor; ileriye dönük :delete de ekliyoruz
      toTokens: (r) => [`${r}:write`, `${r}:delete`],
    },
    { key: "create", label: "Create", toTokens: (r) => [`${r}:create`] },
  ];

/* ================================
   Helpers
================================ */
function normalizeList(data: RolesPayload): Role[] {
  if (Array.isArray(data)) return data;
  if (data && Array.isArray((data as any).items)) return (data as any).items as Role[];
  return [];
}

function parsePermissionsToSet(perms?: string | null): Set<string> {
  const s = new Set<string>();
  (perms || "")
    .split(",")
    .map((p) => p.trim())
    .filter(Boolean)
    .forEach((p) => s.add(p));
  return s;
}

function toggleTokens(set: Set<string>, tokens: string[], checked: boolean) {
  tokens.forEach((t) => {
    if (checked) set.add(t);
    else set.delete(t);
  });
}

/* ================================
   Component
================================ */
export default function RolesPage() {
  const [items, setItems] = useState<Role[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const [q, setQ] = useState("");
  const [open, setOpen] = useState(false);
  const [editing, setEditing] = useState<Role | null>(null);

  const [name, setName] = useState("");
  const [permSet, setPermSet] = useState<Set<string>>(new Set()); // checkbox'lar burayı günceller

  const isValid = useMemo(() => name.trim().length > 0, [name]);

  async function fetchRoles() {
    setLoading(true);
    setError(null);
    try {
      const params = new URLSearchParams();
      if (q.trim()) params.set("q", q.trim());
      const data = await apiGet<RolesPayload>(`/roles/?${params.toString()}`);
      setItems(normalizeList(data));
    } catch (e: any) {
      const msg =
        (e instanceof ApiError && e.message) || e?.message || "Failed to load roles";
      setError(String(msg));
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    fetchRoles();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  function onSearch(e: React.FormEvent) {
    e.preventDefault();
    fetchRoles();
  }

  function onNew() {
    setEditing(null);
    setName("");
    setPermSet(new Set());
    setOpen(true);
  }

  function onEdit(r: Role) {
    setEditing(r);
    setName(r.name ?? "");
    setPermSet(parsePermissionsToSet(r.permissions));
    setOpen(true);
  }

  async function onDelete(r: Role) {
    if (!confirm(`Delete role "${r.name}"?`)) return;
    try {
      try {
        await apiDelete(`/roles/${r.id}/`);
      } catch {
        await apiDelete(`/roles/${r.id}`);
      }
      await fetchRoles();
      alert("Deleted.");
    } catch (e: any) {
      const msg =
        (e instanceof ApiError && e.message) || e?.message || "Delete failed";
      alert(String(msg));
    }
  }

  async function onSave() {
    if (!isValid) return;

    // Set -> virgülle ayrılmış string
    const permissions =
      Array.from(permSet)
        .sort()
        .join(",") || null;

    const payload = { name: name.trim(), permissions };

    try {
      if (editing) {
        try {
          await apiPatch(`/roles/${editing.id}/`, payload);
        } catch {
          await apiPatch(`/roles/${editing.id}`, payload);
        }
      } else {
        await apiPost(`/roles/`, payload);
      }
      setOpen(false);
      await fetchRoles();
      alert("Saved.");
    } catch (e: any) {
      const msg =
        (e instanceof ApiError && e.message) || e?.message || "Save failed";
      alert(String(msg));
    }
  }

  // checkbox işleyici
  function onToggle(resource: string, actionKey: ActionKey, checked: boolean) {
    const next = new Set(permSet);
    const tokens = ACTIONS.find((a) => a.key === actionKey)!.toTokens(resource);

    // delete -> write+delete; read/write/create normal
    toggleTokens(next, tokens, checked);

    // UX: 'delete' işaretlenmişse 'write' zaten eklenmiş olur.
    // 'write' kaldırılırsa 'delete' de mantıksal olarak kalksın:
    if (actionKey === "write" && !checked) {
      next.delete(`${resource}:delete`);
    }

    setPermSet(next);
  }

  function isChecked(resource: string, actionKey: ActionKey): boolean {
    const tokens = ACTIONS.find((a) => a.key === actionKey)!.toTokens(resource);
    // En az bir token permSet içindeyse işaretli kabul et
    return tokens.some((t) => permSet.has(t));
  }

  return (
    <div className="bg-white rounded-xl shadow p-6">
      <div className="flex flex-col sm:flex-row sm:items-center sm:justify-between gap-3 mb-4">
        <h2 className="text-lg font-medium">Roles</h2>
        <form onSubmit={onSearch} className="flex gap-2 items-center">
          <input
            value={q}
            onChange={(e) => setQ(e.target.value)}
            placeholder="Search role name…"
            className="px-3 py-1.5 rounded-md border text-sm w-64"
          />
          <button type="submit" className="px-3 py-1.5 rounded-md border text-sm hover:bg-gray-50">
            Search
          </button>
          <button
            type="button"
            onClick={fetchRoles}
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

      {loading && <div className="text-sm text-gray-500">Loading roles…</div>}
      {error && <div className="text-sm text-red-600">Error: {error}</div>}
      {!loading && !error && items.length === 0 && (
        <div className="text-sm text-gray-500">No roles found.</div>
      )}

      {!loading && !error && items.length > 0 && (
        <div className="overflow-x-auto">
          <table className="min-w-full text-sm">
            <thead>
              <tr className="text-left border-b">
                <th className="py-2 pr-4">Name</th>
                <th className="py-2 pr-4">Permissions</th>
                <th className="py-2 pr-4 w-40 text-right">Actions</th>
              </tr>
            </thead>
            <tbody>
              {items.map((r) => (
                <tr key={r.id} className="border-b last:border-0">
                  <td className="py-2 pr-4 font-medium">{r.name || "—"}</td>
                  <td className="py-2 pr-4">
                    {r.permissions ? r.permissions : <span className="text-gray-400">—</span>}
                  </td>
                  <td className="py-2 pr-4 text-right">
                    <button
                      onClick={() => onEdit(r)}
                      className="px-2 py-1 rounded border mr-2 hover:bg-gray-50"
                    >
                      Edit
                    </button>
                    <button
                      onClick={() => onDelete(r)}
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
      )}

      {/* Modal */}
      {open && (
        <div className="fixed inset-0 bg-black/30 flex items-center justify-center z-50">
          <div className="bg-white w-[900px] max-w-[96vw] rounded-xl shadow p-5">
            <div className="text-lg font-semibold mb-4">
              {editing ? "Edit Role" : "New Role"}
            </div>

            {/* Name */}
            <div className="space-y-3">
              <Field label="Name">
                <input
                  value={name}
                  onChange={(e) => setName(e.target.value)}
                  className="w-full px-3 py-2 rounded-md border text-sm"
                  placeholder="sales_rep"
                />
              </Field>

              {/* Permission Matrix */}
              <div>
                <div className="text-xs text-gray-500 mb-2">Permissions</div>
                <div className="overflow-x-auto border rounded-lg">
                  <table className="min-w-full text-sm">
                    <thead className="bg-gray-50">
                      <tr>
                        <th className="py-2 px-3 text-left">Resource</th>
                        {ACTIONS.map((a) => (
                          <th key={a.key} className="py-2 px-3 text-left">
                            {a.label}
                          </th>
                        ))}
                      </tr>
                    </thead>
                    <tbody>
                      {RESOURCES.map((res) => (
                        <tr key={res} className="border-t">
                          <td className="py-2 px-3 font-medium capitalize">{res}</td>
                          {ACTIONS.map((a) => {
                            const checked = isChecked(res, a.key);
                            return (
                              <td key={a.key} className="py-2 px-3">
                                <input
                                  type="checkbox"
                                  checked={checked}
                                  onChange={(e) => onToggle(res, a.key, e.target.checked)}
                                />
                              </td>
                            );
                          })}
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
                <div className="text-xs text-gray-500 mt-2">
                  <b>Not:</b> Delete işaretlendiğinde sistem, arka planda <code>:write</code> iznini
                  da ekler. Backend çoğu silme işlemini <code>resource:write</code> ile korur.
                </div>
              </div>
            </div>

            {/* Actions */}
            <div className="mt-5 flex justify-end gap-2">
              <button onClick={() => setOpen(false)} className="px-3 py-1.5 rounded-md border hover:bg-gray-50">
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
