// src/pages/debug/Health.tsx
import { useEffect, useState } from "react";

type Health = { status: string };

const API_BASE =
  import.meta.env?.VITE_API_BASE ??
  (window as any).__API_BASE__ ??
  "http://127.0.0.1:8000";

export default function Health() {
  const [data, setData] = useState<Health | null>(null);
  const [me, setMe] = useState<any>(null);
  const [err, setErr] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);

  async function call<T>(path: string): Promise<T> {
    const res = await fetch(`${API_BASE}${path}`, {
      credentials: "include",
      headers: { Accept: "application/json" },
    });
    const ct = res.headers.get("content-type") || "";
    const isJson = ct.includes("application/json");
    if (!res.ok) {
      const body = isJson ? await res.json().catch(() => ({})) : {};
      throw new Error(`${res.status} ${body?.detail ?? res.statusText}`);
    }
    return (isJson ? await res.json() : await res.text()) as T;
  }

  useEffect(() => {
    (async () => {
      try {
        setLoading(true);
        setErr(null);
        const h = await call<Health>("/health");
        setData(h);
      } catch (e: any) {
        setErr(e.message);
      } finally {
        setLoading(false);
      }
    })();
  }, []);

  const fetchMe = async () => {
    try {
      setErr(null);
      const m = await call("/me");
      setMe(m);
    } catch (e: any) {
      setErr(e.message);
      setMe(null);
    }
  };

  return (
    <div style={{ padding: 16 }}>
      <h1>Health Check</h1>
      <div style={{ opacity: 0.8, marginBottom: 12 }}>
        API_BASE: <code>{API_BASE}</code>
      </div>

      {loading && <div>Loading…</div>}
      {err && <div style={{ color: "crimson" }}>Error: {err}</div>}
      {data && (
        <div>
          API status: <b>{data.status}</b>
        </div>
      )}

      <hr style={{ margin: "16px 0" }} />

      <button onClick={fetchMe}>/me çağır (isteğe bağlı, login gerekiyorsa 401 döner)</button>
      {me && (
        <pre style={{ background: "#111", color: "#0f0", padding: 12, marginTop: 12 }}>
          {JSON.stringify(me, null, 2)}
        </pre>
      )}
    </div>
  );
}
