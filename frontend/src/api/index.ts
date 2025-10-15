// frontend/src/api/index.ts
// Minimal API helper used across the app. Prefixes all calls with "/api".
export async function api<T = any>(path: string, init: RequestInit = {}): Promise<T> {
  const url = `/api${path.startsWith("/") ? "" : "/"}${path}`;

  const headers = {
    Accept: "application/json",
    ...(init.headers || {}),
  } as Record<string, string>;

  // add JSON content-type only if body is a string (we already stringify in callers)
  if (init.body && typeof init.body === "string" && !("Content-Type" in headers)) {
    headers["Content-Type"] = "application/json";
  }

  const res = await fetch(url, { ...init, headers });
  const text = await res.text();

  let json: any = null;
  try {
    json = text ? JSON.parse(text) : null;
  } catch {
    throw new Error(`API ${res.status}: Response is not JSON: ${text.slice(0, 160)}…`);
  }

  if (!res.ok) {
    throw new Error(`API ${res.status}: ${text}`);
  }
  return json as T;
}
