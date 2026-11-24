import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import * as Tooltip from "@radix-ui/react-tooltip";
import { lazy, Suspense, useEffect, useState, type ReactNode } from "react";
import { BrowserRouter, Navigate, Route, Routes } from "react-router-dom";
import { Toaster } from "sonner";
import { Skeleton } from "@/components/ui/primitives";
import { redirectToLogin, refreshSession } from "@/lib/api";
import { useSession } from "@/stores/session";
import { applyTheme, useUi } from "@/stores/ui";
import { Layout } from "./Layout";

const HomePage = lazy(() => import("@/features/home/HomePage"));
const QueuePage = lazy(() => import("@/features/queue/QueuePage"));
const ReviewPage = lazy(() => import("@/features/submission/ReviewPage"));
const ClearancePage = lazy(() => import("@/features/clearance/ClearancePage"));
const ReferralsPage = lazy(() => import("@/features/referrals/ReferralsPage"));
const DashboardsPage = lazy(() => import("@/features/dashboards/DashboardsPage"));
const AdminPage = lazy(() => import("@/features/admin/AdminPage"));
const AuditPage = lazy(() => import("@/features/audit/AuditPage"));
const ProfilePage = lazy(() => import("@/features/profile/ProfilePage"));

export const queryClient = new QueryClient({
  defaultOptions: { queries: { staleTime: 15_000, retry: 1, refetchOnWindowFocus: false } },
});

function PageFallback() {
  return (
    <div className="space-y-3" aria-busy="true" aria-label="Loading">
      <Skeleton className="h-7 w-56" />
      <Skeleton className="h-28 w-full" />
      <Skeleton className="h-64 w-full" />
    </div>
  );
}

/** Obtains an access token via the refresh cookie; refreshes it a minute before expiry. */
export function AuthGate({ children }: { children: ReactNode }) {
  const token = useSession((s) => s.token);
  const expiresAt = useSession((s) => s.expiresAt);
  const [checked, setChecked] = useState(!!token);

  useEffect(() => {
    if (token) return;
    refreshSession().then((ok) => (ok ? setChecked(true) : redirectToLogin()));
  }, [token]);

  useEffect(() => {
    if (!expiresAt) return;
    const t = setTimeout(() => void refreshSession(), Math.max(expiresAt - Date.now() - 60_000, 5_000));
    return () => clearTimeout(t);
  }, [expiresAt]);

  if (!checked || !token) {
    return <div className="grid h-full place-items-center text-sm text-subtle" role="status">Signing you in…</div>;
  }
  return <>{children}</>;
}

export function RequireRole({ roles, children }: { roles: string[]; children: ReactNode }) {
  const allowed = useSession((s) => s.has(...roles));
  return allowed ? <>{children}</> : <Navigate to="/" replace />;
}

export function App() {
  const theme = useUi((s) => s.theme);
  const setOnline = useUi((s) => s.setOnline);
  useEffect(() => applyTheme(theme), [theme]);
  useEffect(() => {
    const on = () => setOnline(true);
    const off = () => setOnline(false);
    window.addEventListener("online", on);
    window.addEventListener("offline", off);
    return () => {
      window.removeEventListener("online", on);
      window.removeEventListener("offline", off);
    };
  }, [setOnline]);

  return (
    <QueryClientProvider client={queryClient}>
      <Tooltip.Provider delayDuration={300}>
        <BrowserRouter>
          <AuthGate>
            <Routes>
              <Route element={<Layout />}>
                <Route index element={<Suspense fallback={<PageFallback />}><HomePage /></Suspense>} />
                <Route path="submissions" element={<Suspense fallback={<PageFallback />}><QueuePage /></Suspense>} />
                <Route path="submissions/:id" element={<Suspense fallback={<PageFallback />}><ReviewPage /></Suspense>} />
                <Route path="clearance" element={<Suspense fallback={<PageFallback />}><ClearancePage /></Suspense>} />
                <Route path="referrals" element={<Suspense fallback={<PageFallback />}><ReferralsPage /></Suspense>} />
                <Route path="dashboards/*" element={<Suspense fallback={<PageFallback />}><DashboardsPage /></Suspense>} />
                <Route path="admin/*" element={<RequireRole roles={["admin", "cuo"]}><Suspense fallback={<PageFallback />}><AdminPage /></Suspense></RequireRole>} />
                <Route path="audit" element={<RequireRole roles={["admin", "cuo", "underwriter", "senior_underwriter"]}><Suspense fallback={<PageFallback />}><AuditPage /></Suspense></RequireRole>} />
                <Route path="profile" element={<Suspense fallback={<PageFallback />}><ProfilePage /></Suspense>} />
                <Route path="*" element={<Navigate to="/" replace />} />
              </Route>
            </Routes>
          </AuthGate>
        </BrowserRouter>
      </Tooltip.Provider>
      <Toaster richColors position="bottom-right" closeButton />
    </QueryClientProvider>
  );
}
