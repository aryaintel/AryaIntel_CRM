// Pathway: C:/Dev/AryaIntel_CRM/frontend/src/lib/api.ts
import { getToken } from "./auth";

/** ---------- Config ---------- */
const API_BASE_RAW = import.meta.env.VITE_API_BASE ?? "http://127.0.0.1:8000";
export const API_BASE = API_BASE_RAW.replace(/\/+$/, ""); // trailing slash temizle
const DEFAULT_TIMEOUT_MS = Number(import.meta.env.VITE_API_TIMEOUT_MS ?? 15000);
const DEBUG = (import.meta.env.VITE_DEBUG_API ?? "false") === "true";

/** ---------- Helpers ---------- */
function joinUrl(path: string) {
  // absolute URL ise dokunma
  if (/^https?:\/\//i.test(path)) return path;

  // "/api/..." veya "/..." ya da "relative" tüm durumları API_BASE'e bağla
  const p = path.startsWith("/") ? path : `/${path}`;
  return `${API_BASE}${p}`;
}

export class ApiError extends Error {
  status: number;
  payload?: unknown;
  method?: string;
  url?: string;
  constructor(
    status: number,
    message: string,
    payload?: unknown,
    method?: string,
    url?: string
  ) {
    super(message);
    this.status = status;
    this.payload = payload;
    this.method = method;
    this.url = url;
  }
}
export const isApiError = (e: unknown): e is ApiError =>
  e instanceof ApiError && typeof e.status === "number";

function authHeader(token?: string | null): Record<string, string> {
  const t = token === undefined ? getToken() : token;
  return t ? { Authorization: `Bearer ${t}` } : {};
}

async function readPayload(res: Response): Promise<{ message: string; payload: unknown }> {
  let payload: unknown = null;
  let message = res.statusText || "Request failed";

  try {
    payload = await res.clone().json();
    const p = payload as any;

    if (p?.detail) {
      if (typeof p.detail === "string") {
        message = p.detail;
      } else if (Array.isArray(p.detail)) {
        const first = p.detail[0];
        if (first?.msg) {
          const loc = Array.isArray(first?.loc) ? first.loc.join(".") : "";
          message = loc ? `${loc}: ${first.msg}` : first.msg;
        } else {
          message = JSON.stringify(p.detail);
        }
      }
    } else if (p?.message && typeof p.message === "string") {
      message = p.message;
    }
    return { message, payload };
  } catch {
    try {
      const txt = await res.text();
      payload = txt;
      if (txt) message = txt.length > 600 ? txt.slice(0, 600) + "..." : txt;
    } catch {
      /* no-op */
    }
  }
  return { message, payload };
}

type HttpMethod = "GET" | "POST" | "PUT" | "PATCH" | "DELETE";

async function request<T>(
  method: HttpMethod,
  path: string,
  body?: unknown,
  token?: string | null,
  timeoutMs: number = DEFAULT_TIMEOUT_MS
): Promise<T> {
  const url = joinUrl(path);
  const headers: Record<string, string> = {
    Accept: "application/json",
    ...authHeader(token),
  };

  const isFormData = typeof FormData !== "undefined" && body instanceof FormData;
  if (body !== undefined && !isFormData) {
    headers["Content-Type"] = "application/json";
  }

  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), timeoutMs);

  const fetchInit: RequestInit = {
    method,
    headers,
    body:
      body === undefined
        ? undefined
        : isFormData
        ? (body as any)
        : JSON.stringify(body),
    signal: controller.signal,
    // ÇOK ÖNEMLİ: Cookie tabanlı oturumlar için çerezi gönder
    credentials: "include",
  };

  if (DEBUG) {
    // eslint-disable-next-line no-console
    console.debug(`[API] ${method} ${url}`, { headers, body: isFormData ? "[FormData]" : body });
  }

  let res: Response;
  try {
    res = await fetch(url, fetchInit);
  } catch (err: any) {
    clearTimeout(timer);
    if (err?.name === "AbortError") {
      throw new ApiError(0, `Request timed out after ${timeoutMs}ms`, err, method, url);
    }
    const hint =
      err?.name === "TypeError"
        ? " (possible CORS issue or server is unreachable)"
        : "";
    throw new ApiError(0, (err?.message || "Network request failed") + hint, err, method, url);
  } finally {
    // fetch tamamlanınca/abort olunca mutlaka temizle
    clearTimeout(timer);
  }

  if (!res.ok) {
    const { message, payload } = await readPayload(res);
    const decorated = `[${res.status}] ${method} ${url} → ${message}`;

    // Global 401 bildirimi (opsiyonel olarak route değiştirilebilir)
    if (res.status === 401 && typeof window !== "undefined") {
      window.dispatchEvent(
        new CustomEvent("auth:unauthorized", { detail: { method, url, message, payload } })
      );
      // Örn: otomatik logout ya da login'e atmak istersen:
      // window.location.assign("/login");
    }

    throw new ApiError(res.status, decorated, payload, method, url);
  }

  if (res.status === 204 || res.status === 205) {
    return undefined as unknown as T;
  }

  const ct = res.headers.get("content-type") || "";
  if (ct.includes("application/json")) {
    const data = (await res.json()) as T;
    if (DEBUG) {
      // eslint-disable-next-line no-console
      console.debug(`[API] ${method} ${url} ← OK`, data);
    }
    return data;
  }

  // Başka content-type ise, çağıran taraf belirlesin (şimdilik undefined)
  return undefined as unknown as T;
}

/** ---------- Shorthands ---------- */
export function apiGet<T>(path: string, token?: string | null, timeoutMs?: number) {
  return request<T>("GET", path, undefined, token, timeoutMs);
}
export function apiPost<T>(path: string, body?: unknown, token?: string | null, timeoutMs?: number) {
  return request<T>("POST", path, body, token, timeoutMs);
}
export function apiPut<T>(path: string, body?: unknown, token?: string | null, timeoutMs?: number) {
  return request<T>("PUT", path, body, token, timeoutMs);
}
export function apiPatch<T>(path: string, body?: unknown, token?: string | null, timeoutMs?: number) {
  return request<T>("PATCH", path, body, token, timeoutMs);
}
/** GENERIC DELETE */
export function apiDelete<T = void>(path: string, token?: string | null, timeoutMs?: number) {
  return request<T>("DELETE", path, undefined, token, timeoutMs);
}

/** ---------- Optional helpers ---------- */
export function apiMe<T = any>() {
  return apiGet<T>("/me");
}
