// frontend/src/pages/scenario/components/IndexPointsTable.tsx
import React, { useEffect, useMemo, useRef, useState } from "react";
import {
  listPoints,
  upsertPoint,
  bulkUpsertPoints,
  deletePointByYM,
  fromYM,
  type IndexPoint,
  type IndexPointBulkItem,
  type Paginated,
} from "../api/indexSeries";

// Chart (Recharts)
import {
  ResponsiveContainer,
  LineChart,
  Line,
  XAxis,
  YAxis,
  CartesianGrid,
  Tooltip,
} from "recharts";

type Props = {
  seriesId: number;       // Required: which series to manage
  onChanged?: () => void; // Optional callback after data changes
};

const YM_REGEX = /^\d{4}-(0[1-9]|1[0-2])$/;
const makeYM = (y: number, m: number) =>
  `${y}-${String(m).padStart(2, "0")}`;

// When BE returns year/month instead of ym
type RawPoint = Partial<IndexPoint> & {
  year?: number;
  month?: number;
  value: number;
};

export default function IndexPointsTable({ seriesId, onChanged }: Props) {
  // Listing & pagination
  const [rows, setRows] = useState<IndexPoint[]>([]);
  const [count, setCount] = useState(0);
  const [limit, setLimit] = useState(50);
  const [offset, setOffset] = useState(0);

  // State
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  // Single upsert form
  const [ym, setYM] = useState("");
  const [value, setValue] = useState<string>("");

  // Bulk upsert area
  const [bulkText, setBulkText] = useState("");
  const [fileName, setFileName] = useState<string>("");
  const fileInputRef = useRef<HTMLInputElement | null>(null);

  // Chart toggle
  const [showChart, setShowChart] = useState(false);

  const page = useMemo(() => Math.floor(offset / limit) + 1, [offset, limit]);
  const pages = useMemo(
    () => Math.max(1, Math.ceil(count / (limit || 1))),
    [count, limit]
  );

  async function load() {
    if (!seriesId) return;
    setLoading(true);
    setError(null);
    try {
      const res: Paginated<RawPoint> = await listPoints(seriesId, { limit, offset } as any);

      // Normalize items so each has ym
      const normalized: IndexPoint[] = (res.items || []).map((p: RawPoint) => {
        const ymKey =
          p.ym ??
          (p.year != null && p.month != null ? makeYM(p.year, p.month) : "");
        return {
          ym: ymKey,
          value: Number(p.value),
          source_ref: (p as any).source_ref ?? null,
        };
      });

      setRows(normalized);
      setCount(res.count ?? normalized.length ?? 0);
    } catch (e: any) {
      setError(e?.message || "Failed to load points.");
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    // reset paging and hide chart when series changes
    setOffset(0);
    setShowChart(false);
  }, [seriesId]);

  useEffect(() => {
    load();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [seriesId, limit, offset]);

  const canSingleSubmit = YM_REGEX.test(ym) && value.trim() !== "" && !loading;

  async function handleSingleUpsert() {
    if (!canSingleSubmit) return;
    setLoading(true);
    setError(null);
    try {
      const num = Number(value.replace(",", ".")); // accept decimal comma
      if (Number.isNaN(num)) {
        setError("Value must be numeric.");
        setLoading(false);
        return;
      }
      await upsertPoint(seriesId, { ym, value: num });
      setYM("");
      setValue("");
      await load();
      onChanged?.();
    } catch (e: any) {
      const status = e?.status ?? e?.response?.status;
      if (status === 400) setError("Invalid request. Check 'YYYY-MM' format and value.");
      else setError(e?.message || "Save error.");
    } finally {
      setLoading(false);
    }
  }

  const parsedBulk: IndexPointBulkItem[] = useMemo(() => {
    const out: IndexPointBulkItem[] = [];
    for (const raw of bulkText.split(/\r?\n/)) {
      const line = raw.trim();
      if (!line) continue;
      // skip header-ish lines
      if (/[a-zA-Z]/.test(line) && !/^\d/.test(line)) continue;

      const parts = line.split(/[;, \t]+/).map((s) => s.trim());
      // Format A: "YYYY-MM;value"
      if (parts.length === 2 && YM_REGEX.test(parts[0])) {
        const { year, month } = fromYM(parts[0]);
        const v = Number((parts[1] || "").replace(",", "."));
        if (!Number.isNaN(v)) out.push({ year, month, value: v });
      }
      // Format B: "year;month;value"
      else if (parts.length >= 3) {
        const y = Number(parts[0]);
        const m = Number(parts[1]);
        const v = Number((parts[2] || "").replace(",", "."));
        if (
          Number.isInteger(y) &&
          Number.isInteger(m) &&
          m >= 1 &&
          m <= 12 &&
          !Number.isNaN(v)
        ) {
          out.push({ year: y, month: m, value: v });
        }
      }
    }
    return out;
  }, [bulkText]);

  async function handleBulkUpsert() {
    if (!parsedBulk.length) return;
    setLoading(true);
    setError(null);
    try {
      await bulkUpsertPoints(seriesId, parsedBulk);
      setBulkText("");
      setFileName("");
      await load();
      onChanged?.();
    } catch (e: any) {
      setError(e?.message || "Bulk upload failed.");
    } finally {
      setLoading(false);
    }
  }

  async function handleDelete(ymKey: string) {
    if (!ymKey) return;
    setLoading(true);
    setError(null);
    try {
      await deletePointByYM(seriesId, ymKey);
      await load();
      onChanged?.();
    } catch (e: any) {
      setError(e?.message || "Delete failed.");
    } finally {
      setLoading(false);
    }
  }

  function handleChooseCSV() {
    fileInputRef.current?.click();
  }

  function handleFileSelected(e: React.ChangeEvent<HTMLInputElement>) {
    const file = e.target.files?.[0];
    if (!file) return;
    setFileName(file.name);
    const reader = new FileReader();
    reader.onload = () => {
      const text = String(reader.result || "");
      // Push file content into the paste area so the same parser is used
      setBulkText(text);
    };
    reader.readAsText(file);
    // reset input so same file can be chosen again later
    e.target.value = "";
  }

  function handleDownloadTemplate() {
    const sample = [
      "ym,value",
      "2025-01,22.5",
      "2025-02,23.1",
      "2025-03,24.0",
      "",
      "year,month,value",
      "2025,04,25.2",
      "2025,05,26.0",
    ].join("\n");
    const blob = new Blob([sample], { type: "text/csv;charset=utf-8" });
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = "index-points-template.csv";
    document.body.appendChild(a);
    a.click();
    a.remove();
    URL.revokeObjectURL(url);
  }

  function clearBulkArea() {
    setBulkText("");
    setFileName("");
  }

  const disablePrev = offset <= 0 || loading;
  const disableNext = offset + limit >= count || loading;

  // Chart data: sort ascending by YM, last 60 points
  const chartData = useMemo(() => {
    const sorted = [...rows]
      .filter((r) => r.ym)
      .sort((a, b) => (a.ym! < b.ym! ? -1 : a.ym! > b.ym! ? 1 : 0));
    const trimmed = sorted.slice(-60);
    return trimmed.map((r) => ({ ym: r.ym!, value: Number(r.value) }));
  }, [rows]);

  // Small preview of parsed bulk (first 8)
  const bulkPreview = useMemo(() => parsedBulk.slice(0, 8), [parsedBulk]);

  return (
    <div className="border rounded-2xl p-4 space-y-4">
      <div className="flex items-center justify-between gap-2">
        <div className="font-semibold">Time Series Points</div>
        <div className="flex items-center gap-2">
          <button
            className="px-3 py-1 rounded border"
            onClick={() => setShowChart((v) => !v)}
            title={showChart ? "Hide chart" : "Visualize series"}
          >
            {showChart ? "Hide Chart" : "Visualize Series"}
          </button>
          <button
            className="px-3 py-1 rounded border"
            onClick={load}
            disabled={loading}
            title="Refresh"
          >
            {loading ? "…" : "↻"}
          </button>
        </div>
      </div>

      {error && (
        <div className="text-sm text-red-700 bg-red-50 border border-red-200 rounded p-2">
          {error}
        </div>
      )}

      {/* Chart (hidden by default, toggled via button) */}
      {showChart && (
        <div className="border rounded-xl p-3">
          <div className="text-sm font-medium mb-2">Trend (last 60 points)</div>
          {chartData.length ? (
            <div style={{ width: "100%", height: 220 }}>
              <ResponsiveContainer>
                <LineChart data={chartData} margin={{ top: 8, right: 12, left: 0, bottom: 8 }}>
                  <CartesianGrid strokeDasharray="3 3" />
                  <XAxis dataKey="ym" tick={{ fontSize: 12 }} interval="preserveStartEnd" />
                  <YAxis tick={{ fontSize: 12 }} />
                  <Tooltip />
                  <Line type="monotone" dataKey="value" dot={false} strokeWidth={2} />
                </LineChart>
              </ResponsiveContainer>
            </div>
          ) : (
            <div className="text-xs text-gray-500">No points to visualize.</div>
          )}
        </div>
      )}

      {/* Single upsert */}
      <div className="flex flex-wrap gap-2 items-end">
        <label className="text-sm">
          Month (YYYY-MM)
          <input
            className="mt-1 border rounded px-2 py-1 w-40"
            placeholder="2025-01"
            value={ym}
            onChange={(e) => setYM(e.target.value)}
          />
        </label>
        <label className="text-sm">
          Value
          <input
            className="mt-1 border rounded px-2 py-1 w-40"
            inputMode="decimal"
            value={value}
            onChange={(e) => setValue(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === "Enter" && canSingleSubmit) {
                e.preventDefault();
                handleSingleUpsert();
              }
            }}
          />
        </label>
        <button
          className="px-3 py-2 rounded bg-indigo-600 text-white disabled:opacity-50"
          onClick={handleSingleUpsert}
          disabled={!canSingleSubmit}
        >
          Add / Update
        </button>
      </div>

      {/* Table */}
      <div className="overflow-auto">
        <table className="w-full text-sm">
          <thead>
            <tr className="text-left border-b">
              <th className="py-1 px-1 w-40">Month (YM)</th>
              <th className="py-1 px-1">Value</th>
              <th className="py-1 px-1 w-24 text-right">Actions</th>
            </tr>
          </thead>
          <tbody>
            {rows.map((r) => (
              <tr key={r.ym} className="border-b">
                <td className="py-1 px-1">{r.ym || "-"}</td>
                <td className="py-1 px-1">{r.value}</td>
                <td className="py-1 px-1 text-right">
                  <button
                    className="text-red-600"
                    onClick={() => handleDelete(r.ym!)}
                    disabled={loading || !r.ym}
                  >
                    Delete
                  </button>
                </td>
              </tr>
            ))}
            {!loading && !rows.length && (
              <tr>
                <td className="py-2 px-1 text-sm text-gray-500" colSpan={3}>
                  No records.
                </td>
              </tr>
            )}
          </tbody>
        </table>
      </div>

      {/* Pagination */}
      <div className="flex items-center justify-between text-sm">
        <div>
          Total {count} • Page {page}/{pages}
        </div>
        <div className="flex items-center gap-2">
          <select
            className="border rounded px-2 py-1"
            value={limit}
            onChange={(e) => {
              setOffset(0);
              setLimit(Number(e.target.value));
            }}
          >
            {[20, 50, 100, 200].map((n) => (
              <option key={n} value={n}>
                {n}/page
              </option>
            ))}
          </select>
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

      {/* Bulk upsert */}
      <div className="border rounded-xl p-3 space-y-2">
        <div className="font-medium">Bulk Upload</div>

        <div className="text-xs text-gray-600">
          Paste rows or choose a CSV file. Accepted formats:
          <ul className="list-disc ml-5 mt-1">
            <li><code>YYYY-MM;value</code> (or comma/TAB/space instead of semicolon)</li>
            <li><code>year;month;value</code></li>
          </ul>
          Decimals: both <code>22.5</code> and <code>22,5</code> are supported.
        </div>

        <div className="flex flex-wrap gap-2 items-center">
          <button className="px-3 py-1 rounded border" onClick={handleChooseCSV}>
            Choose CSV
          </button>
          <input
            type="file"
            accept=".csv,.txt"
            className="hidden"
            ref={fileInputRef}
            onChange={handleFileSelected}
          />
          {fileName && <span className="text-xs text-gray-600">Selected: {fileName}</span>}

          <button className="px-3 py-1 rounded border" onClick={handleDownloadTemplate}>
            Download template
          </button>

          <button className="px-3 py-1 rounded border" onClick={clearBulkArea}>
            Clear
          </button>
        </div>

        <textarea
          className="w-full h-32 border rounded px-2 py-1"
          placeholder={`YYYY-MM;value\nor\nyear;month;value`}
          value={bulkText}
          onChange={(e) => setBulkText(e.target.value)}
        />

        <div className="flex items-center justify-between">
          <div className="text-xs text-gray-500">
            Rows parsed: {parsedBulk.length}
          </div>
          <button
            className="px-3 py-2 rounded bg-gray-900 text-white disabled:opacity-50"
            onClick={handleBulkUpsert}
            disabled={!parsedBulk.length || loading}
          >
            Upload
          </button>
        </div>

        {/* tiny preview */}
        {!!parsedBulk.length && (
          <div className="overflow-auto border rounded p-2">
            <table className="w-full text-xs">
              <thead>
                <tr className="text-left border-b">
                  <th className="py-1 px-1 w-24">Year</th>
                  <th className="py-1 px-1 w-20">Month</th>
                  <th className="py-1 px-1">Value</th>
                </tr>
              </thead>
              <tbody>
                {parsedBulk.slice(0, 8).map((r, i) => (
                  <tr key={i} className="border-b">
                    <td className="py-1 px-1">{r.year}</td>
                    <td className="py-1 px-1">{String(r.month).padStart(2, "0")}</td>
                    <td className="py-1 px-1">{r.value}</td>
                  </tr>
                ))}
                {parsedBulk.length > 8 && (
                  <tr>
                    <td className="py-1 px-1 text-gray-500" colSpan={3}>
                      …and {parsedBulk.length - 8} more
                    </td>
                  </tr>
                )}
              </tbody>
            </table>
          </div>
        )}
      </div>
    </div>
  );
}
