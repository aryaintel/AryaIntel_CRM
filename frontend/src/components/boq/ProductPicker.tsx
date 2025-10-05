// src/components/boq/ProductPicker.tsx
import { useEffect, useMemo, useState } from "react";
import { listProducts, getBestPriceForProduct, type Product } from "../../lib/apiProducts";

export default function ProductPicker({
  value,
  onChange,
  onPrice,
  familyId,
}: {
  value?: number;
  onChange: (productId?: number) => void;
  onPrice?: (p: { unit_price: number; currency?: string | null }) => void;
  familyId?: number;
}) {
  const [q, setQ] = useState("");
  const [items, setItems] = useState<Product[]>([]);
  const [loading, setLoading] = useState(false);

  const debouncedQ = useMemo(() => q, [q]); // basit kullanım

  useEffect(() => {
    let cancelled = false;
    const load = async () => {
      setLoading(true);
      try {
        const res = await listProducts({
          q: debouncedQ || undefined,
          family_id: familyId,
          active: true,
          limit: 20,
          offset: 0,
        });
        if (!cancelled) setItems(res.items || []);
      } finally {
        if (!cancelled) setLoading(false);
      }
    };
    load();
    return () => {
      cancelled = true;
    };
  }, [debouncedQ, familyId]);

  const handlePick = async (idStr: string) => {
    const id = idStr ? Number(idStr) : undefined;
    onChange(id);
    if (id && onPrice) {
      try {
        const best = await getBestPriceForProduct(id);
        onPrice({ unit_price: best.unit_price, currency: best.currency });
      } catch {
        // fiyat bulunamazsa sessizce geç
      }
    }
  };

  return (
    <div className="space-y-1">
      <div className="flex gap-2">
        <input
          className="flex-1 border rounded px-2 py-1"
          placeholder="Search product…"
          value={q}
          onChange={(e) => setQ(e.target.value)}
        />
        {loading && <span className="text-xs text-gray-500 self-center">Loading…</span>}
      </div>

      <select
        className="w-full border rounded px-2 py-1"
        value={value ?? ""}
        onChange={(e) => handlePick(e.target.value)}
      >
        <option value="">— select product —</option>
        {items.map((p) => (
          <option key={p.id} value={p.id}>
            {p.code} — {p.name}
          </option>
        ))}
      </select>
    </div>
  );
}
