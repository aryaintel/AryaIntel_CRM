// frontend/src/pages/ProductsPage.tsx
import React, { useEffect, useMemo, useState } from "react";
import { apiGet, apiPost, apiPut, apiDelete } from "../lib/api";

type Product = {
  id: number; code: string; name: string; description?: string | null;
  uom?: string | null; currency: string; base_price: number;
  tax_rate_pct?: number | null; barcode_gtin?: string | null;
  is_active: boolean; created_at?: string; updated_at?: string;
};
type PriceBook = { id: number; name: string; currency?: string | null; };
type PriceBookEntry = { id: number; price_book_id: number; product_id: number; unit_price: number; currency?: string | null; };

export default function ProductsPage() {
  const [rows, setRows] = useState<Product[]>([]);
  const [loading, setLoading] = useState(true);
  const [err, setErr] = useState<string | null>(null);
  const [q, setQ] = useState("");
  const [selected, setSelected] = useState<Product | null>(null);
  const [editing, setEditing] = useState<Partial<Product> | null>(null);
  const [tab, setTab] = useState<"overview"|"pricebooks"|"audit">("overview");
  const [books, setBooks] = useState<PriceBook[]>([]);
  const [bookEntries, setBookEntries] = useState<PriceBookEntry[]>([]);

  useEffect(() => { (async () => {
    setLoading(true); setErr(null);
    try { const res = await apiGet<any>("/api/products"); setRows(res.items ?? res ?? []); }
    catch (e:any){ setErr(e?.message || "Failed to load products"); }
    finally { setLoading(false); }
  })(); }, []);

  useEffect(() => { (async () => {
    if (!selected || tab!=="pricebooks") return;
    try {
      const bks = await apiGet<any>("/api/price-books");
      setBooks(bks.items ?? bks ?? []);
      // tüm kitapların entry'lerini çekip filtrelemek basit MVP:
      const all: PriceBookEntry[] = [];
      for (const b of (bks.items ?? bks ?? [])) {
        const es = await apiGet<any>(`/api/price-books/${b.id}/entries`);
        const arr = es.items ?? es ?? [];
        all.push(...arr.filter((e: any) => e.product_id === selected.id));
      }
      setBookEntries(all);
    } catch {}
  })(); }, [selected, tab]);

  const filtered = useMemo(() => {
    const t = q.toLowerCase().trim();
    if (!t) return rows;
    return rows.filter(r =>
      r.name.toLowerCase().includes(t) ||
      r.code.toLowerCase().includes(t)
    );
  }, [rows, q]);

  async function save() {
  if (!editing) return;

  const payload = {
    code: editing.code || "",
    name: editing.name || "",
    description: editing.description ?? null,
    uom: editing.uom ?? null,
    currency: editing.currency || "USD",
    base_price: Number(editing.base_price || 0),
    tax_rate_pct: editing.tax_rate_pct ?? null,
    barcode_gtin: editing.barcode_gtin ?? null,
    is_active: editing.is_active ?? true,
  };

  if (editing.id) {
    await apiPut(`/api/products/${editing.id}`, payload);
  } else {
    const created: any = await apiPost("/api/products", payload);
    // Eğer anında seçili göstermek istersen:
    const newId = created?.id ?? created?.data?.id;
    if (newId) {
      setSelected({
        id: newId,
        ...payload,
      } as any);
    }
  }

  // refresh
  const res = await apiGet<any>("/api/products");
  setRows(res.items ?? res ?? []);
  setEditing(null);
}

  async function remove(p: Product) {
    if (!confirm(`Delete ${p.name}?`)) return;
    await apiDelete(`/api/products/${p.id}`);
    const res = await apiGet<any>("/api/products");
    setRows(res.items ?? res ?? []);
    if (selected?.id === p.id) setSelected(null);
  }

  return (
    <div className="grid grid-cols-12 gap-4">
      <aside className="col-span-4 border rounded-xl p-3 bg-white">
        <div className="flex justify-between items-center mb-2">
          <input className="border rounded px-2 py-1 w-2/3" placeholder="Search code/name…" value={q} onChange={e=>setQ(e.target.value)} />
          <button className="px-3 py-1.5 border rounded" onClick={()=>setEditing({ currency:"USD", is_active:true })}>+ New</button>
        </div>
        {loading ? <div>Loading…</div> : err ? <div className="text-red-600">{err}</div> : (
          <div className="h-[520px] overflow-auto divide-y">
            {filtered.map(p=>(
              <div key={p.id} className={"p-2 cursor-pointer text-sm "+(selected?.id===p.id?"bg-indigo-50":"hover:bg-gray-50")}
                   onClick={()=>setSelected(p)}>
                <div className="font-medium">{p.name}</div>
                <div className="text-gray-600">{p.code} • {p.currency} {Number(p.base_price||0).toFixed(2)}</div>
              </div>
            ))}
          </div>
        )}
      </aside>

      <main className="col-span-8 space-y-4">
        {!selected && !editing ? (
          <div className="text-sm text-gray-600 border rounded-xl p-6 bg-white">Select a product or create a new one.</div>
        ) : editing ? (
          <div className="border rounded-xl p-4 bg-white space-y-3">
            <h3 className="font-semibold">{editing.id ? "Edit Product" : "New Product"}</h3>
            <div className="grid grid-cols-2 gap-3 text-sm">
              <label className="flex flex-col"><span>Code</span>
                <input className="border rounded px-2 py-1" value={editing.code||""} onChange={e=>setEditing({...editing, code:e.target.value})}/>
              </label>
              <label className="flex flex-col"><span>Name</span>
                <input className="border rounded px-2 py-1" value={editing.name||""} onChange={e=>setEditing({...editing, name:e.target.value})}/>
              </label>
              <label className="flex flex-col"><span>UOM</span>
                <input className="border rounded px-2 py-1" value={editing.uom||""} onChange={e=>setEditing({...editing, uom:e.target.value})}/>
              </label>
              <label className="flex flex-col"><span>Currency</span>
                <input className="border rounded px-2 py-1" value={editing.currency||"USD"} onChange={e=>setEditing({...editing, currency:e.target.value})}/>
              </label>
              <label className="flex flex-col"><span>Base Price</span>
                <input type="number" className="border rounded px-2 py-1" value={Number(editing.base_price||0)} onChange={e=>setEditing({...editing, base_price:Number(e.target.value||0)})}/>
              </label>
              <label className="flex flex-col"><span>Tax %</span>
                <input type="number" className="border rounded px-2 py-1" value={Number(editing.tax_rate_pct||0)} onChange={e=>setEditing({...editing, tax_rate_pct:Number(e.target.value||0)})}/>
              </label>
              <label className="flex items-center gap-2"><input type="checkbox" checked={editing.is_active??true} onChange={e=>setEditing({...editing, is_active:e.target.checked})}/> Active</label>
              <label className="flex flex-col col-span-2"><span>Description</span>
                <textarea className="border rounded px-2 py-1" rows={3} value={editing.description||""} onChange={e=>setEditing({...editing, description:e.target.value})}/>
              </label>
            </div>
            <div className="flex gap-2">
              <button className="px-3 py-1.5 border rounded" onClick={save}>Save</button>
              <button className="px-3 py-1.5 border rounded" onClick={()=>setEditing(null)}>Cancel</button>
            </div>
          </div>
        ) : (
          <div className="border rounded-xl p-4 bg-white">
            <div className="flex justify-between items-center">
              <h3 className="font-semibold">{selected?.name}</h3>
              <div className="flex gap-2">
                <button className="px-3 py-1.5 border rounded" onClick={()=>setEditing(selected!)}>Edit</button>
                <button className="px-3 py-1.5 border rounded" onClick={()=>remove(selected!)}>Delete</button>
              </div>
            </div>
            <div className="mt-3 border-b flex gap-4 text-sm">
              {["overview","pricebooks","audit"].map(t=>(
                <button key={t} className={"pb-2 "+(tab===t?"border-b-2 border-indigo-600 font-medium":"text-gray-600")} onClick={()=>setTab(t as any)}>
                  {t}
                </button>
              ))}
            </div>

            {tab==="overview" && (
              <div className="mt-3 text-sm grid grid-cols-2 gap-3">
                <div><span className="text-gray-500">Code:</span> {selected?.code}</div>
                <div><span className="text-gray-500">UOM:</span> {selected?.uom || "-"}</div>
                <div><span className="text-gray-500">Currency:</span> {selected?.currency}</div>
                <div><span className="text-gray-500">Base Price:</span> {Number(selected?.base_price||0).toFixed(2)}</div>
                <div className="col-span-2"><span className="text-gray-500">Description:</span> {selected?.description || "-"}</div>
              </div>
            )}

            {tab==="pricebooks" && (
              <div className="mt-3 text-sm">
                {bookEntries.length===0 ? <div className="text-gray-500">No price-book entries for this product.</div> : (
                  <div className="divide-y">
                    {bookEntries.map(e=>(
                      <div key={e.id} className="py-2 flex justify-between">
                        <div>Book #{e.price_book_id}</div>
                        <div>{e.currency || selected?.currency} {Number(e.unit_price).toFixed(2)}</div>
                      </div>
                    ))}
                  </div>
                )}
              </div>
            )}

            {tab==="audit" && (
              <div className="mt-3 text-sm text-gray-600">
                Created: {selected?.created_at || "-"} · Updated: {selected?.updated_at || "-"}
              </div>
            )}
          </div>
        )}
      </main>
    </div>
  );
}
