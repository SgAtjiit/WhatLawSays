import { Navigate, Outlet, useLocation } from "react-router";

import { Splash } from "@/components/Splash";
import { SetupNeeded } from "@/components/SetupNeeded";
import { needsVerification, useAuth } from "./AuthProvider";

export function RequireAuth() {
  const { user, status } = useAuth();
  const location = useLocation();
  const here = `${location.pathname}${location.search}${location.hash}`;

  if (status === "unconfigured") return <SetupNeeded />;
  if (status === "loading") return <Splash />;
  if (!user) return <Navigate to={`/sign-in?next=${encodeURIComponent(here)}`} replace />;
  if (needsVerification(user)) {
    return <Navigate to={`/verify-email?next=${encodeURIComponent(here)}`} replace />;
  }
  return <Outlet />;
}

/** Where to go after signing in: only ever a path inside this app. */
export function safeNext(search) {
  const next = new URLSearchParams(search).get("next");
  return next && next.startsWith("/") && !next.startsWith("//") ? next : "/";
}
