import type { ReactNode } from "react";
import { Navigate, useLocation } from "react-router-dom";
import { Loader2 } from "lucide-react";
import { useMe } from "@/hooks/useAuth";

function Splash({ label }: { label: string }) {
  return (
    <div
      className="flex min-h-screen flex-col items-center justify-center gap-3 bg-[#0b0e14]"
      data-testid="route-loading"
    >
      <Loader2 className="size-6 animate-spin text-amber-400" />
      <p className="text-[12px] text-slate-400">{label}</p>
    </div>
  );
}

/** Signed in, or bounce to /login remembering where they were heading. */
export function RequireAuth({ children }: { children: ReactNode }) {
  const { data: me, isLoading } = useMe();
  const location = useLocation();
  if (isLoading) return <Splash label="Checking your session…" />;
  if (!me) return <Navigate to="/login" replace state={{ from: location.pathname }} />;
  return <>{children}</>;
}

/** Signed in AND subscribed (admins always pass) — otherwise the paywall. */
export function RequireSubscription({ children }: { children: ReactNode }) {
  const { data: me, isLoading } = useMe();
  const location = useLocation();
  if (isLoading) return <Splash label="Checking your subscription…" />;
  if (!me) return <Navigate to="/login" replace state={{ from: location.pathname }} />;
  if (!me.subscribed) return <Navigate to="/subscribe" replace />;
  return <>{children}</>;
}

export function RequireAdmin({ children }: { children: ReactNode }) {
  const { data: me, isLoading } = useMe();
  if (isLoading) return <Splash label="Checking admin access…" />;
  if (!me) return <Navigate to="/login" replace />;
  if (me.role !== "admin") return <Navigate to="/" replace />;
  return <>{children}</>;
}
