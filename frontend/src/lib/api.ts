// src/lib/api.ts
import { getToken } from "./auth";

/** ---------- Config ---------- */
const API_BASE_RAW = import.meta.env.VITE_API_BASE ?? "http://127.0.0.1:8000";
export const API_BASE = API_BASE_RAW.replace(/\/+$/, ""); // trailing slash temizle
const DEFAULT_TIMEOUT_MS = Number(import.meta.env.VITE_API_TIMEOUT_MS ?? 15000);
const DEBUG = (import.meta.env.VITE_DEBUG_API ?? "false") === "true";

/** ---------- Helpers ---------- */
function joinUrl(path: string) {
  if (/^https?:\/\//i.test(path)) return path; // absolute URL ise dokunma
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

  // JSON dene
  try {
    payload = await res.clone().json();
    const p = payload as any;

    // FastAPI tipik hata formatları
    if (p?.detail) {
      if (typeof p.detail === "string") {
        message = p.detail;
      } else if (Array.isArray(p.detail)) {
        // validation errors
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
    // Text dene
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

  // Body varsa Content-Type (FormData/Blob değilse)
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
    // Cookie tabanlı oturum kullanıyorsanız yorum kaldırın:
    // credentials: "include",
  };

  if (DEBUG) {
    // eslint-disable-next-line no-console
    console.debug(`[API] ${method} ${url}`, { headers, body });
  }

  let res: Response;
  try {
    res = await fetch(url, fetchInit);
  } catch (err: any) {
    clearTimeout(timer);
    // Fetch "TypeError: Failed to fetch" -> çoğunlukla CORS ya da sunucu kapalı
    if (err?.name === "AbortError") {
      throw new ApiError(
        0,
        `Request timed out after ${timeoutMs}ms`,
        err,
        method,
        url
      );
    }
    const hint =
      err?.name === "TypeError"
        ? " (possible CORS issue or server is unreachable)"
        : "";
    throw new ApiError(0, (err?.message || "Network request failed") + hint, err, method, url);
  }

  clearTimeout(timer);

  if (!res.ok) {
    const { message, payload } = await readPayload(res);
    const decorated = `[${res.status}] ${method} ${url} → ${message}`;
    throw new ApiError(res.status, decorated, payload, method, url);
  }

  // 204/205 No Content
  if (res.status === 204 || res.status === 205) {
    return undefined as unknown as T;
  }

  // İçerik tipine göre parse et
  const ct = res.headers.get("content-type") || "";
  if (ct.includes("application/json")) {
    const data = (await res.json()) as T;
    if (DEBUG) {
      // eslint-disable-next-line no-console
      console.debug(`[API] ${method} ${url} ← OK`, data);
    }
    return data;
  }

  // JSON dönmeyen başarı yanıtlarını void kabul et
  return undefined as unknown as T;
}

/** ---------- Shorthands ---------- */
// body'yi opsiyonel yaptık → mark-services-ready gibi gövdesiz POST'lar sorunsuz çalışır.
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
export function apiDelete(path: string, token?: string | null, timeoutMs?: number) {
  return request<void>("DELETE", path, undefined, token, timeoutMs);
}

/** ---------- Optional helpers ---------- */
/** Backend 1.0.4'te current user → /me  */
export function apiMe<T = any>() {
  return apiGet<T>("/me");
}
