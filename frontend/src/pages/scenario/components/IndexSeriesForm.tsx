// frontend/src/pages/scenario/components/IndexSeriesForm.tsx
import React, { useEffect, useMemo, useState } from "react";
import {
  createSeries,
  updateSeries,
  type IndexSeries,
  type IndexSeriesCreate,
  type IndexSeriesUpdate,
} from "../api/indexSeries";

type Mode = "create" | "edit";

type Props = {
  mode: Mode;
  /** required in edit mode */
  value?: IndexSeries | null;
  /** fires after create/update with the saved series */
  onSaved?: (series: IndexSeries) => void;
  /** optional cancel handler to hide the form */
  onCancel?: () => void;
};

export default function IndexSeriesForm({
  mode,
  value = null,
  onSaved,
  onCancel,
}: Props) {
  // Build the "initial" form model from props
  const initial: IndexSeriesCreate | IndexSeriesUpdate = useMemo(() => {
    if (mode === "edit" && value) {
      const {
        code,
        name,
        unit = null,
        country = null,
        currency = null,
        source = null,
        fetch_adapter = null,
        fetch_config = null,
        is_active = true,
        description = null,
      } = value;
      return {
        code,
        name,
        unit,
        country,
        currency,
        source,
        fetch_adapter,
        fetch_config,
        is_active,
        description,
      };
    }
    // defaults for create
    return {
      code: "",
      name: "",
      unit: null,
      country: null,
      currency: null,
      source: null,
      fetch_adapter: null,
      fetch_config: null,
      is_active: true,
      description: null,
    };
  }, [mode, value]);

  // Local form state
  const [form, setForm] = useState<IndexSeriesCreate | IndexSeriesUpdate>(initial);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  // 🔧 KEY FIX: whenever mode/value (i.e., `initial`) changes, reset the form
  useEffect(() => {
    setForm(initial);
  }, [initial]);

  const canSubmit =
    !!String((form as IndexSeriesCreate).code || "").trim() &&
    !!String((form as IndexSeriesCreate).name || "").trim() &&
    !busy;

  async function handleSave() {
    setError(null);
    setBusy(true);
    try {
      let saved: IndexSeries;
      if (mode === "create") {
        const payload: IndexSeriesCreate = {
          code: String((form as IndexSeriesCreate).code || "").trim(),
          name: String((form as IndexSeriesCreate).name || "").trim(),
          unit: (form as IndexSeriesCreate).unit ?? null,
          country: (form as IndexSeriesCreate).country ?? null,
          currency: (form as IndexSeriesCreate).currency ?? null,
          source: (form as IndexSeriesCreate).source ?? null,
          fetch_adapter: (form as IndexSeriesCreate).fetch_adapter ?? null,
          fetch_config: (form as IndexSeriesCreate).fetch_config ?? null,
          is_active: (form as IndexSeriesCreate).is_active ?? true,
          description: (form as IndexSeriesCreate).description ?? null,
        };
        saved = await createSeries(payload);
      } else {
        if (!value) throw new Error("Edit mode requires value.");
        const payload: IndexSeriesUpdate = {
          code: (form as IndexSeriesUpdate).code,
          name: (form as IndexSeriesUpdate).name,
          unit: (form as IndexSeriesUpdate).unit,
          country: (form as IndexSeriesUpdate).country,
          currency: (form as IndexSeriesUpdate).currency,
          source: (form as IndexSeriesUpdate).source,
          fetch_adapter: (form as IndexSeriesUpdate).fetch_adapter,
          fetch_config: (form as IndexSeriesUpdate).fetch_config ?? null,
          is_active: (form as IndexSeriesUpdate).is_active,
          description: (form as IndexSeriesUpdate).description,
        };
        saved = await updateSeries(value.id, payload);
      }
      onSaved?.(saved);
    } catch (e: any) {
      const status = e?.status ?? e?.response?.status;
      if (status === 409) setError("This code already exists. Please enter a unique code.");
      else if (status === 400) setError("Invalid request. Please check the fields.");
      else setError(e?.message || "An error occurred while saving.");
    } finally {
      setBusy(false);
    }
  }

  function bind<K extends keyof IndexSeriesCreate & keyof IndexSeriesUpdate>(key: K) {
    return {
      value: (form as any)[key] ?? "",
      onChange: (e: React.ChangeEvent<HTMLInputElement | HTMLTextAreaElement>) =>
        setForm((f) => ({ ...(f as any), [key]: e.target.value })),
    };
  }

  return (
    <div className="border rounded-2xl p-4 space-y-4">
      <div className="flex items-center justify-between">
        <div className="font-semibold">
          {mode === "create" ? "New Index Series" : `Edit Series${value ? `: ${value.name}` : ""}`}
        </div>
        {onCancel && (
          <button
            className="text-sm px-3 py-1 rounded border"
            onClick={onCancel}
            disabled={busy}
          >
            Cancel
          </button>
        )}
      </div>

      {error && (
        <div className="text-sm text-red-700 bg-red-50 border border-red-200 rounded p-2">
          {error}
        </div>
      )}

      <div className="grid grid-cols-1 md:grid-cols-3 gap-3">
        <label className="text-sm">
          Code <span className="text-red-600">*</span>
          <input
            className="mt-1 w-full border rounded px-2 py-1"
            placeholder="CPI_TR_ALL"
            {...bind("code")}
          />
        </label>

        <label className="text-sm md:col-span-2">
          Name <span className="text-red-600">*</span>
          <input
            className="mt-1 w-full border rounded px-2 py-1"
            placeholder="Turkey CPI (All)"
            {...bind("name")}
          />
        </label>

        <label className="text-sm">
          Currency
          <input className="mt-1 w-full border rounded px-2 py-1" placeholder="USD" {...bind("currency")} />
        </label>

        <label className="text-sm">
          Unit
          <input className="mt-1 w-full border rounded px-2 py-1" placeholder="index" {...bind("unit")} />
        </label>

        <label className="text-sm">
          Country
          <input className="mt-1 w-full border rounded px-2 py-1" placeholder="TR" {...bind("country")} />
        </label>

        <label className="text-sm">
          Source
          <input className="mt-1 w-full border rounded px-2 py-1" placeholder="TUIK / FRED / Manual" {...bind("source")} />
        </label>

        <label className="text-sm md:col-span-3">
          Description
          <textarea
            className="mt-1 w-full border rounded px-2 py-1"
            placeholder="Short description…"
            {...bind("description")}
          />
        </label>

        <label className="text-sm flex items-center gap-2 md:col-span-3">
          <input
            type="checkbox"
            checked={Boolean((form as any).is_active ?? true)}
            onChange={(e) => setForm((f) => ({ ...(f as any), is_active: e.target.checked }))}
          />
          Active
        </label>
      </div>

      <div className="flex gap-2">
        <button
          className="px-4 py-2 rounded bg-indigo-600 text-white disabled:opacity-50"
          onClick={handleSave}
          disabled={!canSubmit}
        >
          {busy ? "Saving…" : "Save"}
        </button>
        {onCancel && (
          <button
            className="px-4 py-2 rounded border"
            onClick={onCancel}
            disabled={busy}
          >
            Cancel
          </button>
        )}
      </div>
    </div>
  );
}
