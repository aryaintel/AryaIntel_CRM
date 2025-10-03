

/** ---------- Date helpers ---------- */

/** ISO (YYYY-MM-DD, ISO string vs.) -> "YYYY-MM-DD" (geçersizse olduğu gibi döndürür) */
export function formatDate(iso: string) {
  if (!iso) return "";
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return iso;
  const y = d.getFullYear();
  const m = String(d.getMonth() + 1).padStart(2, "0");
  const day = String(d.getDate()).padStart(2, "0");
  return `${y}-${m}-${day}`;
}

/** "Nov-25" gibi kısa başlık; y=2025, m=11 -> "Nov-25" */
export function fmtMonthYY(y: number, m: number) {
  const names = ["Jan","Feb","Mar","Apr","May","Jun","Jul","Aug","Sep","Oct","Nov","Dec"];
  const mm = Math.min(12, Math.max(1, m));
  const yy = String(y).slice(-2);
  return `${names[mm - 1]}-${yy}`;
}

/** ---------- Number helpers ---------- */

export function fmt(n?: number | null) {
  const v = typeof n === "number" && Number.isFinite(n) ? n : 0;
  return new Intl.NumberFormat("en-US", {
    maximumFractionDigits: 0,
  }).format(v);
}

export function fmt2(n?: number | null) {
  const v = typeof n === "number" && Number.isFinite(n) ? n : 0;
  return new Intl.NumberFormat("en-US", {
    minimumFractionDigits: 2,
    maximumFractionDigits: 2,
  }).format(v);
}

export function fmtMoney(n?: number | null, currency = "USD") {
  const v = typeof n === "number" && Number.isFinite(n) ? n : 0;
  return new Intl.NumberFormat("en-US", {
    style: "currency",
    currency,
    maximumFractionDigits: 2,
  }).format(v);
}

/** 0..1 arası oranı yüzde değere çevirir (0.153 -> 15.3) */
export function fmtPct(n?: number | null, digits = 1) {
  const v = typeof n === "number" && Number.isFinite(n) ? n : 0;
  return (v * 100).toFixed(digits);
}

/** Negatif/pozitif sayıları renklendirmek için tailwind class */
export function getNumberClass(v?: number | null) {
  if (typeof v !== "number" || !Number.isFinite(v) || v === 0) return "";
  return v < 0 ? "text-red-600" : "text-green-700";
}

/** ---------- Table layout constants ---------- */
export const FIRST_COL_W = "160px";
export const MONTH_COL_W = "72px";
