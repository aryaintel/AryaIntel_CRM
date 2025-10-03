import { useState } from "react";
import { useNavigate } from "react-router-dom";
import { setToken, setRole } from "../lib/auth";
import { apiGet, apiPost, ApiError } from "../lib/api";

type Role = "admin" | "member";

const LOGIN_PATHS = ["/auth/login", "/auth/signin", "/login", "/auth/token"];
const ME_PATHS = ["/auth/me", "/me", "/users/me"];

async function tryFirst<T>(
  paths: string[],
  call: (path: string) => Promise<T>
): Promise<T> {
  let lastErr: unknown;
  for (const p of paths) {
    try {
      return await call(p);
    } catch (e) {
      lastErr = e;
      // Sadece 404'te diğer path'e geç; diğer hatalarda dur
      if (!(e instanceof ApiError && e.status === 404)) {
        throw e;
      }
    }
  }
  throw lastErr ?? new ApiError(404, "Not Found");
}

export default function LoginPage() {
  const [tenantSlug, setTenantSlug] = useState("");
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [err, setErr] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const nav = useNavigate();

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    setErr(null);

    if (!tenantSlug || !email || !password) {
      setErr("All fields are required");
      return;
    }

    try {
      setBusy(true);

      // 1) LOGIN
      const login = await tryFirst(LOGIN_PATHS, (path) =>
        apiPost<{ access_token: string; token_type?: string }>(path, {
          tenant_slug: tenantSlug,
          email,
          password,
        })
      );

      // 2) TOKEN'ı kaydet
      setToken(login.access_token);

      // 3) /me — başarısız olsa bile yönlendireceğiz (iyimser akış)
      let role: Role = "member";
      try {
        const me = await tryFirst(ME_PATHS, (path) =>
          apiGet<{ role: Role }>(path, login.access_token)
        );
        role = me.role;
      } catch {
        // App tarafı AUTH_EVENT sayesinde me'yi çekecek
      }
      setRole(role);

      // 4) Redirect
      nav(role === "admin" ? "/users" : "/accounts", { replace: true });
    } catch (e: any) {
      const msg =
        e?.message ||
        e?.payload?.detail ||
        (Array.isArray(e?.payload?.detail) && e.payload.detail[0]?.msg) ||
        "Login failed";
      setErr(String(msg));
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="max-w-3xl mx-auto">
      <h1 className="text-2xl font-semibold my-6">Login</h1>
      <div className="max-w-lg">
        <form
          onSubmit={handleSubmit}
          className="bg-white rounded-xl shadow p-6 space-y-4"
        >
          <div>
            <label className="block text-sm font-medium mb-1">
              Tenant slug
            </label>
            <input
              className="w-full border rounded-lg px-3 py-2"
              placeholder="e.g. arya"
              value={tenantSlug}
              onChange={(e) => setTenantSlug(e.target.value)}
            />
          </div>
          <div>
            <label className="block text-sm font-medium mb-1">Email</label>
            <input
              type="email"
              className="w-full border rounded-lg px-3 py-2"
              placeholder="user@example.com"
              value={email}
              onChange={(e) => setEmail(e.target.value)}
              autoComplete="username"
            />
          </div>
          <div>
            <label className="block text-sm font-medium mb-1">Password</label>
            <input
              type="password"
              className="w-full border rounded-lg px-3 py-2"
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              autoComplete="current-password"
            />
          </div>

          {err && (
            <div className="text-red-600 text-sm bg-red-50 border border-red-200 rounded px-3 py-2">
              {err}
            </div>
          )}

          <button
            type="submit"
            disabled={busy}
            className="w-full bg-indigo-600 hover:bg-indigo-700 text-white rounded-lg py-2 font-medium disabled:opacity-50"
          >
            {busy ? "Signing in…" : "Sign in"}
          </button>
        </form>
      </div>
    </div>
  );
}
