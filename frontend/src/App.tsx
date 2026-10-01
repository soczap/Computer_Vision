import { lazy, Suspense, type ReactNode } from "react";
import { BrowserRouter, Navigate, Route, Routes, useLocation, useNavigate } from "react-router-dom";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { AuthProvider, useAuth } from "./lib/auth";
import { ToastProvider } from "./lib/toast";
import { StreamProvider } from "./lib/stream";
import { DataModeProvider } from "./lib/datamode";
import Layout from "./components/Layout";
import Login from "./pages/Login";
import { Spinner } from "./components/ui";
import type { Role } from "./lib/api";

const CommandCenter = lazy(() => import("./pages/CommandCenter"));
const LiveWall = lazy(() => import("./pages/Live").then((m) => ({ default: m.LiveWall })));
const LiveCamera = lazy(() => import("./pages/Live").then((m) => ({ default: m.LiveCamera })));
const Incidents = lazy(() => import("./pages/Incidents"));
const IncidentDetail = lazy(() => import("./pages/IncidentDetail"));
const Events = lazy(() => import("./pages/Events"));
const Identities = lazy(() => import("./pages/Identities"));
const IdentityProfile = lazy(() => import("./pages/IdentityProfile"));
const SearchPage = lazy(() => import("./pages/Search"));
const Analytics = lazy(() => import("./pages/Analytics"));
const Agents = lazy(() => import("./pages/Agents"));
const Cameras = lazy(() => import("./pages/Cameras"));
const SettingsPage = lazy(() => import("./pages/Settings"));
const SystemPage = lazy(() => import("./pages/System"));
const Webcam = lazy(() => import("./pages/Webcam"));
const FrsConsole = lazy(() => import("./pages/frs/Console"));
const FrsIdentities = lazy(() => import("./pages/frs/Identities"));
const FrsIdentity = lazy(() => import("./pages/frs/Identity"));
const FrsEnroll = lazy(() => import("./pages/frs/Enroll"));
const FrsWatchlist = lazy(() => import("./pages/frs/Watchlist"));
const FrsCriminal = lazy(() => import("./pages/frs/Criminal"));
const FrsSearches = lazy(() => import("./pages/frs/Searches"));
const FrsStats = lazy(() => import("./pages/frs/Stats"));

const qc = new QueryClient({
  defaultOptions: {
    queries: {
      staleTime: 10_000,
      retry: (n, err: any) => (err?.status === 401 || err?.status === 403 || err?.status === 404 ? false : n < 2),
      refetchOnWindowFocus: false,
    },
  },
});

function Loading() {
  return (
    <div className="flex h-full items-center justify-center">
      <Spinner size={20} />
    </div>
  );
}

function Protected({ children, role }: { children: ReactNode; role?: Role }) {
  const { me, loading, can } = useAuth();
  const loc = useLocation();
  if (loading) return <Loading />;
  if (!me) return <Navigate to="/login" replace state={{ from: loc.pathname + loc.search }} />;
  if (role && !can(role)) return <Navigate to="/" replace />;
  return <>{children}</>;
}

function Shell() {
  const { me } = useAuth();
  const nav = useNavigate();
  return (
    <ToastProvider onNavigate={(h) => nav(h)}>
      <DataModeProvider enabled={!!me}>
      <StreamProvider enabled={!!me}>
        <Suspense fallback={<Loading />}>
          <Routes>
            <Route path="/login" element={<Login />} />
            <Route element={<Protected><Layout /></Protected>}>
              <Route index element={<CommandCenter />} />
              <Route path="live" element={<LiveWall />} />
              <Route path="live/:cameraId" element={<LiveCamera />} />
              <Route path="incidents" element={<Incidents />} />
              <Route path="incidents/:id" element={<IncidentDetail />} />
              <Route path="events" element={<Events />} />
              <Route path="identities" element={<Identities />} />
              <Route path="identities/:id" element={<IdentityProfile />} />
              <Route path="search" element={<SearchPage />} />
              <Route path="analytics" element={<Analytics />} />
              <Route path="agents" element={<Agents />} />
              <Route path="cameras" element={<Protected role="analyst"><Cameras /></Protected>} />
              <Route path="settings" element={<Protected role="admin"><SettingsPage /></Protected>} />
              <Route path="system" element={<SystemPage />} />
              <Route path="webcam" element={<Webcam />} />
              <Route path="frs" element={<FrsConsole />} />
              <Route path="frs/identities" element={<FrsIdentities />} />
              <Route path="frs/identities/:id" element={<FrsIdentity />} />
              <Route path="frs/enroll" element={<FrsEnroll />} />
              <Route path="frs/watchlist" element={<FrsWatchlist />} />
              <Route path="frs/watchlist/:criminalId" element={<FrsCriminal />} />
              <Route path="frs/searches" element={<FrsSearches />} />
              <Route path="frs/stats" element={<FrsStats />} />
              <Route path="*" element={<Navigate to="/" replace />} />
            </Route>
          </Routes>
        </Suspense>
      </StreamProvider>
      </DataModeProvider>
    </ToastProvider>
  );
}

export default function App() {
  return (
    <QueryClientProvider client={qc}>
      <BrowserRouter>
        <AuthProvider>
          <Shell />
        </AuthProvider>
      </BrowserRouter>
    </QueryClientProvider>
  );
}
