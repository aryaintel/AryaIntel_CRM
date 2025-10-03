// frontend/src/pages/scenario/tabs/IndexSeriesTab.tsx
import React, { useEffect, useMemo, useState } from "react";
import IndexSeriesForm from "../components/IndexSeriesForm";
import IndexPointsTable from "../components/IndexPointsTable";
import {
  listSeries,
  type IndexSeries,
  type Paginated,
} from "../api/indexSeries";

type FormMode = "create" | "edit" | null;

export default function IndexSeriesTab() {
  // List & selection
  const [items, setItems] = useState<IndexSeries[]>([]);
  const [selected, setSelected] = useState<IndexSeries | null>(null);
  const [mode, setMode] = useState<FormMode>(null);

  // Search & pagination
  const [q, setQ] = useState("");
  const [limit, setLimit] = useState(20);
  const [offset, setOffset] = useState(0);
  const [count, setCount] = useState(0);

  // States
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const page = useMemo(() => Math.floor(offset / limit) + 1, [offset, limit]);
  const pages = useMemo(
    () => Math.max(1, Math.ceil(count / (limit || 1))),
    [count, limit]
  );

  async function load() {
    setLoading(true);
    setError(null);
    try {
      const res: Paginated<IndexSeries> = await listSeries({ q, limit, offset });
      setItems(res.items || []);
      setCount(res.count ?? res.items?.length ?? 0);

      // Default selection
      if ((!selected || mode === null) && res.items?.length) {
        setSelected(res.items[0]);
        setMode("edit");
      } else if (!res.items?.length) {
        setSelected(null);
        setMode(null);
      }
    } catch (e: any) {
      setError(e?.message || "Failed to load index series.");
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    load();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [q, limit, offset]);

  function onNew() {
    setMode("create");
    setSelected(null);
  }

  function onSelect(item: IndexSeries) {
    setSelected(item);
    setMode("edit");
  }

  function onSaved(saved: IndexSeries) {
    // Update list
    setItems((list) => {
      const exists = list.some((x) => x.id === saved.id);
      if (exists) return list.map((x) => (x.id === saved.id ? saved : x));
      return [saved, ...list];
    });
    setSelected(saved);
    setMode("edit");
  }

  function onCancel() {
    // If cancelled from create, select first item if any
    if (!selected && items.length) {
      setSelected(items[0]);
      setMode("edit");
    } else if (!items.length) {
      setMode(null);
    }
  }

  const disablePrev = offset <= 0 || loading;
  const disableNext = offset + limit >= count || loading;

  return (
    <div className="grid grid-cols-12 gap-4">
      {/* Left: list & search */}
      <aside className="col-span-4 lg:col-span-3 border rounded-2xl p-3">
        <div className="flex items-center gap-2 mb-2">
          <input
            className="flex-1 border rounded px-2 py-1"
            placeholder="Search (code/name)…"
            value={q}
            onChange={(e) => {
              setOffset(0);
              setQ(e.target.value);
            }}
          />
          <button
            className="px-3 py-1 rounded border"
            onClick={() => load()}
            disabled={loading}
            title="Refresh"
          >
            {loading ? "…" : "↻"}
          </button>
          <button
            className="px-3 py-1 rounded bg-indigo-600 text-white"
            onClick={onNew}
          >
            + New
          </button>
        </div>

        {error && (
            <div className="text-sm text-red-700 bg-red-50 border border-red-200 rounded p-2 mb-2">
              {error}
            </div>
        )}

        <ul className="space-y-1 max-h-[60vh] overflow-auto pr-1">
          {items.map((it) => {
            const active = selected?.id === it.id && mode === "edit";
            return (
              <li key={it.id}>
                <button
                  className={`w-full text-left px-3 py-2 rounded transition ${
                    active ? "bg-indigo-50" : "hover:bg-gray-50"
                  }`}
                  onClick={() => onSelect(it)}
                >
                  <div className="font-medium">{it.name}</div>
                  <div className="text-xs text-gray-500">
                    {it.code} {it.currency ? `• ${it.currency}` : ""}
                  </div>
                </button>
              </li>
            );
          })}
          {!loading && !items.length && (
            <li className="text-sm text-gray-500 px-1 py-2">
              No records. Click “+ New” to add.
            </li>
          )}
        </ul>

        {/* Pagination */}
        <div className="mt-3 flex items-center justify-between text-sm">
          <div>
            Page {page}/{pages}
          </div>
          <div className="flex items-center gap-2">
            <button
              className="px-2 py-1 rounded border"
              disabled={disablePrev}
              onClick={() => setOffset((o) => Math.max(0, o - limit))}
            >
              ‹ Prev
            </button>
            <button
              className="px-2 py-1 rounded border"
              disabled={disableNext}
              onClick={() => setOffset((o) => o + limit)}
            >
              Next ›
            </button>
          </div>
        </div>
      </aside>

      {/* Right: Form + Points */}
      <main className="col-span-8 lg:col-span-9 space-y-4">
        {mode === "create" && (
          <IndexSeriesForm mode="create" onSaved={onSaved} onCancel={onCancel} />
        )}
        {mode === "edit" && selected && (
          <>
            <IndexSeriesForm
              mode="edit"
              value={selected}
              onSaved={onSaved}
              onCancel={onCancel}
            />
            <IndexPointsTable
              seriesId={selected.id}
              onChanged={() => {
                /* hook for side effects if needed */
              }}
            />
          </>
        )}
        {mode === null && (
          <div className="text-sm text-gray-600 border rounded-2xl p-6">
            Select a series from the list or click “+ New” to create one.
          </div>
        )}
      </main>
    </div>
  );
}
