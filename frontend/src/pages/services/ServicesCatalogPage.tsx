// Pathway: C:/Dev/AryaIntel_CRM/frontend/src/pages/services/ServicesCatalogPage.tsx
import React, { useEffect, useMemo, useRef, useState } from "react";
import { apiGet, apiPost, apiPut } from "../../lib/api";

/**
 * ServicesCatalogPage — Salesforce-style UI, parallel to ProductsPage.tsx
 * Fixes:
 * - Family create now selects the created row directly and shows errors if any.
 * - Toggle uses PATCH (backend expects PATCH).
 * - Better validation & busy flags to avoid double submissions.
 */

// ---------- Types ----------
type ServiceFamily = {
  id?: number;
  code: string;
  name: string;
  is_active: boolean;
  sort_order: number;
};

type ServiceItem = {
  id?: number;
  family_id: number;
  code: string;
  name: string;
  uom?: string | null;
  default_currency?: string | null;
  is_active: boolean;
  description?: string | null;
};

// Small helpers
const cleanStr = (v: any) => (typeof v === "string" ? v.trim() : v);
const toBool = (v: any) => (v ? true : false);

// ---------- Main Page ----------
export default function ServicesCatalogPage() {
  // Families
  const [families, setFamilies] = useState<ServiceFamily[]>([]);
  const [loadingFamilies, setLoadingFamilies] = useState(false);
  const [familyForm, setFamilyForm] = useState<ServiceFamily>({
    code: "",
    name: "",
    is_active: true,
    sort_order: 0,
  });
  const [familyBusy, setFamilyBusy] = useState(false);
  const [familyError, setFamilyError] = useState<string | null>(null);
  const [selectedFamilyId, setSelectedFamilyId] = useState<number | null>(null);

  // Items
  const [items, setItems] = useState<ServiceItem[]>([]);
  const [loadingItems, setLoadingItems] = useState(false);
  const [itemForm, setItemForm] = useState<ServiceItem>({
    family_id: 0,
    code: "",
    name: "",
    uom: "",
    default_currency: "",
    is_active: true,
    description: "",
  });
  const [itemBusy, setItemBusy] = useState(false);
  const [itemError, setItemError] = useState<string | null>(null);
  const [search, setSearch] = useState<string>("");
  const searchRef = useRef<number | null>(null);

  // Initial load of families
  useEffect(() => {
    reloadFamilies();
  }, []);

  // Load items on family change or search change (debounced)
  useEffect(() => {
    if (searchRef.current) window.clearTimeout(searchRef.current);
    searchRef.current = window.setTimeout(() => {
      reloadItems();
    }, 200);
    return () => {
      if (searchRef.current) window.clearTimeout(searchRef.current);
    };
  }, [selectedFamilyId, search]);

  const selectedFamily = useMemo(
    () => families.find((f) => f.id === selectedFamilyId) || null,
    [families, selectedFamilyId]
  );

  async function reloadFamilies(keepSelection = true) {
    setLoadingFamilies(true);
    setFamilyError(null);
    try {
      const rows = await apiGet<ServiceFamily[]>("/api/service-families");
      setFamilies(rows);
      if (rows.length > 0) {
        if (keepSelection && selectedFamilyId && rows.some((r) => r.id === selectedFamilyId)) {
          // keep
        } else {
          const firstActive = rows.find((r) => r.is_active) || rows[0];
          setSelectedFamilyId(firstActive?.id ?? null);
        }
      } else {
        setSelectedFamilyId(null);
      }
    } catch (e: any) {
      setFamilyError(e?.message || "Failed to load families");
    } finally {
      setLoadingFamilies(false);
    }
  }

  async function reloadItems() {
    if (!selectedFamilyId) {
      setItems([]);
      return;
    }
    setLoadingItems(true);
    setItemError(null);
    try {
      const params = new URLSearchParams();
      params.set("family_id", String(selectedFamilyId));
      if (search && search.trim().length > 0) params.set("q", search.trim());
      const rows = await apiGet<ServiceItem[]>(`/api/services?${params.toString()}`);
      setItems(rows);
    } catch (e: any) {
      setItemError(e?.message || "Failed to load services");
    } finally {
      setLoadingItems(false);
    }
  }

  // ---------- Families: create/update/toggle ----------
  function onFamilyEdit(f: ServiceFamily) {
    setFamilyError(null);
    setFamilyForm({
      id: f.id,
      code: f.code,
      name: f.name,
      is_active: !!f.is_active,
      sort_order: Number.isFinite(f.sort_order) ? f.sort_order : 0,
    });
  }

  function clearFamilyForm() {
    setFamilyError(null);
    setFamilyForm({
      code: "",
      name: "",
      is_active: true,
      sort_order: 0,
    });
  }

  async function submitFamily(e: React.FormEvent) {
    e.preventDefault();
    if (familyBusy) return;
    setFamilyBusy(true);
    setFamilyError(null);
    const payload: ServiceFamily = {
      code: cleanStr(familyForm.code)?.toUpperCase(),
      name: cleanStr(familyForm.name),
      is_active: toBool(familyForm.is_active),
      sort_order: Number.isFinite(familyForm.sort_order) ? Number(familyForm.sort_order) : 0,
    };
    if (!payload.code || !payload.name) {
      setFamilyError("Code and Name are required.");
      setFamilyBusy(false);
      return;
    }

    try {
      let created: ServiceFamily | null = null;
      if (familyForm.id) {
        created = await apiPut<ServiceFamily>(`/api/service-families/${familyForm.id}`, payload);
      } else {
        created = await apiPost<ServiceFamily>("/api/service-families", payload);
      }
      // Select the created/updated family explicitly
      if (created?.id) {
        setSelectedFamilyId(created.id);
      }
      clearFamilyForm();
      // reloadFamilies but keep selection we just set
      await reloadFamilies(true);
    } catch (e: any) {
      // surface server detail (e.detail) if available
      const msg = e?.detail || e?.message || "Failed to save family";
      setFamilyError(String(msg));
    } finally {
      setFamilyBusy(false);
    }
  }

  async function toggleFamilyActive(f: ServiceFamily) {
    try {
      await fetch(`/api/service-families/${f.id}/toggle`, {
        method: "PATCH",
        headers: { "Content-Type": "application/json" },
        body: "{}",
        credentials: "include",
      });
      await reloadFamilies(true);
    } catch (e) {
      // non-blocking
    }
  }

  // ---------- Items: create/update/toggle ----------
  function onItemEdit(it: ServiceItem) {
    setItemError(null);
    setItemForm({
      id: it.id,
      family_id: it.family_id,
      code: it.code,
      name: it.name,
      uom: it.uom || "",
      default_currency: it.default_currency || "",
      is_active: !!it.is_active,
      description: it.description || "",
    });
  }

  function clearItemForm() {
    setItemError(null);
    setItemForm({
      family_id: selectedFamilyId || 0,
      code: "",
      name: "",
      uom: "",
      default_currency: "",
      is_active: true,
      description: "",
    });
  }

  async function submitItem(e: React.FormEvent) {
    e.preventDefault();
    if (itemBusy) return;
    if (!selectedFamilyId) return;
    setItemBusy(true);
    setItemError(null);
    const payload: ServiceItem = {
      family_id: selectedFamilyId,
      code: cleanStr(itemForm.code)?.toUpperCase(),
      name: cleanStr(itemForm.name),
      uom: cleanStr(itemForm.uom || ""),
      default_currency: cleanStr(itemForm.default_currency || ""),
      is_active: toBool(itemForm.is_active),
      description: cleanStr(itemForm.description || ""),
    };
    if (!payload.code || !payload.name) {
      setItemError("Code and Name are required.");
      setItemBusy(false);
      return;
    }

    try {
      if (itemForm.id) {
        await apiPut<ServiceItem>(`/api/services/${itemForm.id}`, payload);
      } else {
        await apiPost<ServiceItem>("/api/services", payload);
      }
      clearItemForm();
      await reloadItems();
    } catch (e: any) {
      const msg = e?.detail || e?.message || "Failed to save service";
      setItemError(String(msg));
    } finally {
      setItemBusy(false);
    }
  }

  async function toggleItemActive(it: ServiceItem) {
    try {
      await fetch(`/api/services/${it.id}/toggle`, {
        method: "PATCH",
        headers: { "Content-Type": "application/json" },
        body: "{}",
        credentials: "include",
      });
      await reloadItems();
    } catch (e) {
      // non-blocking
    }
  }

  // ---------- Render ----------
  return (
    <div className="p-4 grid grid-cols-12 gap-4">
      {/* LEFT: Service Families */}
      <section className="col-span-4">
        <div className="mb-3">
          <h2 className="text-xl font-semibold">Service Families</h2>
          <p className="text-sm text-gray-500">Define top-level service categories (e.g., Labor, Equipment, Freight).</p>
        </div>

        {/* Families Table */}
        <div className="rounded-xl border p-3 bg-white shadow-sm">
          <div className="flex justify-between items-center mb-2">
            <span className="text-sm text-gray-500">{loadingFamilies ? "Loading..." : `${families.length} families`}</span>
            <button
              className="px-3 py-1 rounded-lg border text-sm"
              onClick={() => {
                clearFamilyForm();
              }}
            >
              + New Family
            </button>
          </div>
          <div className="max-h-80 overflow-auto">
            <table className="w-full text-sm">
              <thead>
                <tr className="text-left text-gray-500">
                  <th className="py-1">Code</th>
                  <th className="py-1">Name</th>
                  <th className="py-1">Active</th>
                  <th className="py-1">Order</th>
                  <th className="py-1"></th>
                </tr>
              </thead>
              <tbody>
                {families.map((f) => (
                  <tr
                    key={f.id}
                    className={`hover:bg-gray-50 cursor-pointer ${selectedFamilyId === f.id ? "bg-gray-50" : ""}`}
                    onClick={() => setSelectedFamilyId(f.id ?? null)}
                  >
                    <td className="py-1 pr-2">{f.code}</td>
                    <td className="py-1 pr-2">{f.name}</td>
                    <td className="py-1 pr-2">{f.is_active ? "Yes" : "No"}</td>
                    <td className="py-1 pr-2">{f.sort_order ?? 0}</td>
                    <td className="py-1 pr-2 text-right">
                      <button className="text-xs underline mr-2" onClick={(e) => { e.stopPropagation(); onFamilyEdit(f); }}>Edit</button>
                      <button className="text-xs underline" onClick={(e) => { e.stopPropagation(); toggleFamilyActive(f); }}>{f.is_active ? "Deactivate" : "Activate"}</button>
                    </td>
                  </tr>
                ))}
                {families.length === 0 && (
                  <tr><td colSpan={5} className="py-2 text-center text-gray-400">No families yet</td></tr>
                )}
              </tbody>
            </table>
          </div>
        </div>

        {/* Family Form */}
        <form className="rounded-xl border p-3 bg-white shadow-sm mt-3" onSubmit={submitFamily}>
          <h3 className="font-medium mb-2">{familyForm.id ? "Edit Family" : "New Family"}</h3>
          {familyError && <div className="mb-2 text-sm text-red-600">{familyError}</div>}
          <div className="grid grid-cols-2 gap-2">
            <label className="text-sm">
              Code
              <input
                className="mt-1 w-full border rounded-lg px-2 py-1"
                value={familyForm.code}
                onChange={(e) => setFamilyForm({ ...familyForm, code: e.target.value })}
                required
              />
            </label>
            <label className="text-sm">
              Name
              <input
                className="mt-1 w-full border rounded-lg px-2 py-1"
                value={familyForm.name}
                onChange={(e) => setFamilyForm({ ...familyForm, name: e.target.value })}
                required
              />
            </label>
            <label className="text-sm">
              Sort Order
              <input
                className="mt-1 w-full border rounded-lg px-2 py-1"
                type="number"
                inputMode="numeric"
                value={familyForm.sort_order ?? 0}
                onChange={(e) => setFamilyForm({ ...familyForm, sort_order: Number(e.target.value || 0) })}
              />
            </label>
            <label className="text-sm flex items-center">
              <input
                className="mr-2"
                type="checkbox"
                checked={!!familyForm.is_active}
                onChange={(e) => setFamilyForm({ ...familyForm, is_active: e.target.checked })}
              />
              Active
            </label>
          </div>
          <div className="mt-3 flex gap-2">
            <button className="px-3 py-1 rounded-lg border" type="submit" disabled={familyBusy}>
              {familyForm.id ? (familyBusy ? "Updating..." : "Update") : (familyBusy ? "Creating..." : "Create")}
            </button>
            <button type="button" className="px-3 py-1 rounded-lg border" onClick={clearFamilyForm} disabled={familyBusy}>Clear</button>
          </div>
        </form>
      </section>

      {/* RIGHT: Services under selected family */}
      <section className="col-span-8">
        <div className="mb-3">
          <h2 className="text-xl font-semibold">Services</h2>
          <p className="text-sm text-gray-500">Manage service items under the selected family. Use search for code or name.</p>
        </div>

        {/* Toolbar */}
        <div className="flex justify-between items-center mb-2">
          <div className="flex items-center gap-2">
            <input
              className="border rounded-lg px-2 py-1 w-64"
              placeholder="Search code or name..."
              value={search}
              onChange={(e) => setSearch(e.target.value)}
            />
            {selectedFamily && <span className="text-sm text-gray-500">Family: <b>{selectedFamily.name}</b></span>}
          </div>
          <div>
            <button
              className="px-3 py-1 rounded-lg border"
              onClick={() => {
                clearItemForm();
              }}
              disabled={!selectedFamilyId}
            >
              + New Service
            </button>
          </div>
        </div>

        {/* Items Table */}
        <div className="rounded-xl border p-3 bg-white shadow-sm">
          <div className="max-h-96 overflow-auto">
            <table className="w-full text-sm">
              <thead>
                <tr className="text-left text-gray-500">
                  <th className="py-1">Code</th>
                  <th className="py-1">Name</th>
                  <th className="py-1">UOM</th>
                  <th className="py-1">Currency</th>
                  <th className="py-1">Active</th>
                  <th className="py-1"></th>
                </tr>
              </thead>
              <tbody>
                {items.map((it) => (
                  <tr key={it.id}>
                    <td className="py-1 pr-2">{it.code}</td>
                    <td className="py-1 pr-2">{it.name}</td>
                    <td className="py-1 pr-2">{it.uom || "-"}</td>
                    <td className="py-1 pr-2">{it.default_currency || "-"}</td>
                    <td className="py-1 pr-2">{it.is_active ? "Yes" : "No"}</td>
                    <td className="py-1 pr-2 text-right whitespace-nowrap">
                      <button className="text-xs underline mr-2" onClick={() => onItemEdit(it)}>Edit</button>
                      <button className="text-xs underline" onClick={() => toggleItemActive(it)}>{it.is_active ? "Deactivate" : "Activate"}</button>
                    </td>
                  </tr>
                ))}
                {items.length === 0 && (
                  <tr><td colSpan={6} className="py-2 text-center text-gray-400">{loadingItems ? "Loading..." : "No services"}</td></tr>
                )}
              </tbody>
            </table>
          </div>
        </div>

        {/* Item Form */}
        <form className="rounded-xl border p-3 bg-white shadow-sm mt-3" onSubmit={submitItem}>
          <h3 className="font-medium mb-2">{itemForm.id ? "Edit Service" : "New Service"}</h3>
          {itemError && <div className="mb-2 text-sm text-red-600">{itemError}</div>}
          {!selectedFamilyId && <div className="text-sm text-red-500 mb-2">Please select a family on the left.</div>}
          <div className="grid grid-cols-3 gap-2">
            <label className="text-sm">
              Code
              <input
                className="mt-1 w-full border rounded-lg px-2 py-1"
                value={itemForm.code}
                onChange={(e) => setItemForm({ ...itemForm, code: e.target.value })}
                required
                disabled={!selectedFamilyId}
              />
            </label>
            <label className="text-sm col-span-2">
              Name
              <input
                className="mt-1 w-full border rounded-lg px-2 py-1"
                value={itemForm.name}
                onChange={(e) => setItemForm({ ...itemForm, name: e.target.value })}
                required
                disabled={!selectedFamilyId}
              />
            </label>
            <label className="text-sm">
              UOM
              <input
                className="mt-1 w-full border rounded-lg px-2 py-1"
                value={itemForm.uom || ""}
                onChange={(e) => setItemForm({ ...itemForm, uom: e.target.value })}
                placeholder="e.g., hour, day"
                disabled={!selectedFamilyId}
              />
            </label>
            <label className="text-sm">
              Currency
              <input
                className="mt-1 w-full border rounded-lg px-2 py-1"
                value={itemForm.default_currency || ""}
                onChange={(e) => setItemForm({ ...itemForm, default_currency: e.target.value })}
                placeholder="e.g., USD, EUR"
                disabled={!selectedFamilyId}
              />
            </label>
            <label className="text-sm col-span-1 flex items-center">
              <input
                className="mr-2"
                type="checkbox"
                checked={!!itemForm.is_active}
                onChange={(e) => setItemForm({ ...itemForm, is_active: e.target.checked })}
                disabled={!selectedFamilyId}
              />
              Active
            </label>
            <label className="text-sm col-span-3">
              Description
              <textarea
                className="mt-1 w-full border rounded-lg px-2 py-1"
                value={itemForm.description || ""}
                onChange={(e) => setItemForm({ ...itemForm, description: e.target.value })}
                rows={3}
                disabled={!selectedFamilyId}
              />
            </label>
          </div>
          <div className="mt-3 flex gap-2">
            <button className="px-3 py-1 rounded-lg border" type="submit" disabled={!selectedFamilyId || itemBusy}>
              {itemForm.id ? (itemBusy ? "Updating..." : "Update") : (itemBusy ? "Creating..." : "Create")}
            </button>
            <button type="button" className="px-3 py-1 rounded-lg border" onClick={clearItemForm} disabled={!selectedFamilyId || itemBusy}>
              Clear
            </button>
          </div>
        </form>
      </section>
    </div>
  );
}
