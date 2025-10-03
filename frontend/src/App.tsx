// src/App.tsx
import {
  NavLink,
  Routes,
  Route,
  useLocation,
  Navigate,
  useNavigate,
} from "react-router-dom";
import {
  Suspense,
  lazy,
  useEffect,
  useState,
  useCallback,
  type ReactNode,
} from "react";

import DashboardPage from "./pages/Dashboard";
import AccountsPage from "./pages/Accounts";
import AccountDetailPage from "./pages/AccountDetail";
import ContactsPage from "./pages/Contacts";
import DealsPage from "./pages/Deals";
import OpportunityDetailPage from "./pages/OpportunityDetail";
import LeadsPage from "./pages/Leads";
import LoginPage from "./pages/Login";
import LeadDetailPage from "./pages/LeadDetail";

// NEW
import BusinessCasePage from "./pages/BusinessCase";
// Tabs’lı senaryo sayfası
import ScenarioPage from "./pages/scenario/Scenario";

// NEW: Products
import ProductsPage from "./pages/ProductsPage";

// NEW: Debug health page
import Health from "./pages/debug/Health";

import { apiGet, ApiError } from "./lib/api";
import { clearToken, getToken, AUTH_EVENT } from "./lib/auth";

const UsersPage = lazy(() => import("./pages/Users"));
const RolesPage = lazy(() => import("./pages/Roles"));

type Me = { id: number; email: string; role: "admin" | "member" };

function usePageTitle() {
  const { pathname } = useLocation();
  if (pathname.startsWith("/accounts")) return "Accounts";
  if (pathname.startsWith("/contacts")) return "Contacts";
  if (pathname.startsWith("/leads")) return "Leads";
  if (pathname.startsWith("/deals")) return "Opportunities";
  if (pathname.startsWith("/business-cases")) return "Business Cases";
  if (pathname.startsWith("/scenarios")) return "Scenario";
  if (pathname.startsWith("/products")) return "Products"; // ← eklendi
  if (pathname.startsWith("/users")) return "Users";
  if (pathname.startsWith("/roles")) return "Roles";
  if (pathname.startsWith("/login")) return "Login";
  if (pathname.startsWith("/debug/health")) return "Health";
  return "Dashboard";
}

function RequireAuth({ children }: { children: ReactNode }) {
  if (!getToken()) return <Navigate to="/login" replace />;
  return <>{children}</>;
}

const ME_PATHS = ["/auth/me", "/me", "/users/me"] as const;

export default function App() {
  const title = usePageTitle();
  const nav = useNavigate();
  const [me, setMe] = useState<Me | null>(null);

  const fetchMe = useCallback(async (token: string): Promise<Me> => {
    let lastErr: unknown;
    for (const p of ME_PATHS) {
      try {
        return await apiGet<Me>(p, token);
      } catch (e) {
        lastErr = e;
        if (e instanceof ApiError) {
          if (e.status === 401 || e.status === 403) throw e;
          if (e.status === 404) continue;
        }
        continue;
      }
    }
    throw lastErr instanceof ApiError
      ? lastErr
      : new ApiError(404, "me endpoint not found");
  }, []);

  const loadMe = useCallback(async () => {
    const token = getToken();
    if (!token) {
      setMe(null);
      return;
    }
    try {
      const data = await fetchMe(token);
      setMe(data ?? null);
    } catch (e) {
      if (e instanceof ApiError && (e.status === 401 || e.status === 403)) {
        clearToken();
        setMe(null);
      } else {
        setMe(null);
      }
    }
  }, [fetchMe]);

  useEffect(() => {
    loadMe();
  }, [loadMe]);

  useEffect(() => {
    const handler = () => loadMe();
    window.addEventListener(AUTH_EVENT, handler);
    return () => window.removeEventListener(AUTH_EVENT, handler);
  }, [loadMe]);

  const onLogout = () => {
    clearToken();
    setMe(null);
    nav("/login", { replace: true });
  };

  const isAdmin = me?.role === "admin";

  return (
    <div className="flex h-screen bg-gray-100 text-gray-900">
      <aside className="w-64 bg-white border-r shadow-sm flex flex-col">
        <div className="h-16 flex items-center justify-center border-b font-bold text-indigo-600">
          Aryaintel CRM
        </div>
        <nav className="flex-1 p-4 space-y-2">
          <NavLink
            to="/"
            end
            className={({ isActive }) =>
              `block px-3 py-2 rounded-lg hover:bg-indigo-50 ${
                isActive ? "bg-indigo-100 text-indigo-700" : ""
              }`
            }
          >
            Dashboard
          </NavLink>
          <NavLink
            to="/accounts"
            className={({ isActive }) =>
              `block px-3 py-2 rounded-lg hover:bg-indigo-50 ${
                isActive ? "bg-indigo-100 text-indigo-700" : ""
              }`
            }
          >
            Accounts
          </NavLink>
          <NavLink
            to="/contacts"
            className={({ isActive }) =>
              `block px-3 py-2 rounded-lg hover:bg-indigo-50 ${
                isActive ? "bg-indigo-100 text-indigo-700" : ""
              }`
            }
          >
            Contacts
          </NavLink>
          <NavLink
            to="/leads"
            className={({ isActive }) =>
              `block px-3 py-2 rounded-lg hover:bg-indigo-50 ${
                isActive ? "bg-indigo-100 text-indigo-700" : ""
              }`
            }
          >
            Leads
          </NavLink>
          <NavLink
            to="/deals"
            className={({ isActive }) =>
              `block px-3 py-2 rounded-lg hover:bg-indigo-50 ${
                isActive ? "bg-indigo-100 text-indigo-700" : ""
              }`
            }
          >
            Opportunities
          </NavLink>

          {/* NEW: Products */}
          <NavLink
            to="/products"
            className={({ isActive }) =>
              `block px-3 py-2 rounded-lg hover:bg-indigo-50 ${
                isActive ? "bg-indigo-100 text-indigo-700" : ""
              }`
            }
          >
            Products
          </NavLink>

          {/* Business Case / Scenario menüden değil, detaydan gidiliyor */}
          {isAdmin && (
            <>
              <NavLink
                to="/users"
                className={({ isActive }) =>
                  `block px-3 py-2 rounded-lg hover:bg-indigo-50 ${
                    isActive ? "bg-indigo-100 text-indigo-700" : ""
                  }`
                }
              >
                Users
              </NavLink>
              <NavLink
                to="/roles"
                className={({ isActive }) =>
                  `block px-3 py-2 rounded-lg hover:bg-indigo-50 ${
                    isActive ? "bg-indigo-100 text-indigo-700" : ""
                  }`
                }
              >
                Roles
              </NavLink>
            </>
          )}
        </nav>
      </aside>

      <div className="flex-1 flex flex-col">
        <header className="h-16 bg-white border-b shadow-sm flex items-center justify-between px-6">
          <h1 className="text-xl font-semibold">{title}</h1>
          <div className="flex items-center gap-3 text-sm text-gray-600">
            <span>{me ? `${me.email} (${me.role})` : "guest"}</span>
            {getToken() ? (
              <button
                onClick={onLogout}
                className="px-2 py-1 rounded border hover:bg-gray-50"
              >
                Logout
              </button>
            ) : (
              <NavLink to="/login" className="px-2 py-1 rounded border hover:bg-gray-50">
                Login
              </NavLink>
            )}
          </div>
        </header>

        <main className="flex-1 p-6">
          <Routes>
            <Route path="/login" element={<LoginPage />} />

            {/* PUBLIC: Debug health (CORS & bağlantı kontrolü) */}
            <Route path="/debug/health" element={<Health />} />

            <Route
              path="/"
              element={
                <RequireAuth>
                  <DashboardPage />
                </RequireAuth>
              }
            />
            <Route
              path="/accounts"
              element={
                <RequireAuth>
                  <AccountsPage />
                </RequireAuth>
              }
            />
            <Route
              path="/accounts/:id"
              element={
                <RequireAuth>
                  <AccountDetailPage />
                </RequireAuth>
              }
            />
            <Route
              path="/contacts"
              element={
                <RequireAuth>
                  <ContactsPage />
                </RequireAuth>
              }
            />
            <Route
              path="/leads"
              element={
                <RequireAuth>
                  <LeadsPage />
                </RequireAuth>
              }
            />
            <Route
              path="/deals"
              element={
                <RequireAuth>
                  <DealsPage />
                </RequireAuth>
              }
            />
            <Route
              path="/deals/:id"
              element={
                <RequireAuth>
                  <OpportunityDetailPage />
                </RequireAuth>
              }
            />
            <Route
              path="/leads/:id"
              element={
                <RequireAuth>
                  <LeadDetailPage />
                </RequireAuth>
              }
            />

            {/* NEW: Business Case & Scenario detay rotaları */}
            <Route
              path="/business-cases/:businessCaseId"
              element={
                <RequireAuth>
                  <BusinessCasePage />
                </RequireAuth>
              }
            />
            <Route
              path="/scenarios/:scenarioId"
              element={
                <RequireAuth>
                  <ScenarioPage />
                </RequireAuth>
              }
            />

            {/* NEW: Products rotası */}
            <Route
              path="/products"
              element={
                <RequireAuth>
                  <ProductsPage />
                </RequireAuth>
              }
            />

            {/* Lazy admin sayfaları */}
            <Route
              path="/users"
              element={
                <RequireAuth>
                  <Suspense fallback={<div className="text-sm text-gray-600">Loading…</div>}>
                    <UsersPage />
                  </Suspense>
                </RequireAuth>
              }
            />
            <Route
              path="/roles"
              element={
                <RequireAuth>
                  <Suspense fallback={<div className="text-sm text-gray-600">Loading…</div>}>
                    <RolesPage />
                  </Suspense>
                </RequireAuth>
              }
            />

            {/* Catch-all → Dashboard */}
            <Route path="*" element={<Navigate to="/" replace />} />
          </Routes>
        </main>
      </div>
    </div>
  );
}
