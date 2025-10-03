// src/lib/auth.ts
// Token & rol & tenant yönetimi + güvenli "auth changed" olayı

const TOKEN_KEY = "aryaintel_token";
const ROLE_KEY = "aryaintel_role";
const TENANT_KEY = "aryaintel_tenant";

export type RoleName = "admin" | "member" | "guest";

/** App tarafından dinlenecek global event adı */
export const AUTH_EVENT = "arya:auth-changed";

/** window korumalı ve her ortamda güvenli event yayını */
function emitAuthChanged() {
  try {
    if (typeof window === "undefined" || !("dispatchEvent" in window)) return;
    // queueMicrotask bazı ortamlarda yok → setTimeout(0) kullan
    setTimeout(() => {
      try {
        window.dispatchEvent(new CustomEvent(AUTH_EVENT));
      } catch {
        /* no-op */
      }
    }, 0);
  } catch {
    /* no-op */
  }
}

/* ---------- Token ---------- */
export function getToken(): string | null {
  try {
    return localStorage.getItem(TOKEN_KEY);
  } catch {
    return null;
  }
}
export function setToken(tok: string) {
  try {
    localStorage.setItem(TOKEN_KEY, tok);
  } finally {
    emitAuthChanged();
  }
}
export function clearToken() {
  try {
    localStorage.removeItem(TOKEN_KEY);
  } finally {
    emitAuthChanged();
  }
}

/* ---------- Role ---------- */
export function getRole(): RoleName {
  try {
    return (localStorage.getItem(ROLE_KEY) as RoleName) || "guest";
  } catch {
    return "guest";
  }
}
export function setRole(role: RoleName) {
  try {
    localStorage.setItem(ROLE_KEY, role);
  } finally {
    emitAuthChanged();
  }
}
export function clearRole() {
  try {
    localStorage.removeItem(ROLE_KEY);
  } finally {
    emitAuthChanged();
  }
}

/* ---------- Tenant ---------- */
export function getTenantSlug(): string | null {
  try {
    return localStorage.getItem(TENANT_KEY);
  } catch {
    return null;
  }
}
export function setTenantSlug(slug: string) {
  try {
    localStorage.setItem(TENANT_KEY, slug);
  } finally {
    emitAuthChanged();
  }
}
export function clearTenantSlug() {
  try {
    localStorage.removeItem(TENANT_KEY);
  } finally {
    emitAuthChanged();
  }
}

/* ---------- Headers / helpers ---------- */
export function getAuthHeader(): Record<string, string> {
  const t = getToken();
  return t ? { Authorization: `Bearer ${t}` } : {};
}

export function isAuthenticated(): boolean {
  return !!getToken();
}

/** Tek seferde oturum verilerini kurar */
export function loginSuccess(opts: { token: string; role: RoleName; tenant?: string }) {
  setToken(opts.token);
  setRole(opts.role);
  if (opts.tenant) setTenantSlug(opts.tenant);
}

/** Logout: tüm oturum verilerini temizle */
export function logout() {
  clearToken();
  clearRole();
  clearTenantSlug();
}
