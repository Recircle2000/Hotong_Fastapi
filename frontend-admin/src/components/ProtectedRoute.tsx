import { Navigate, Outlet, useLocation } from "react-router-dom";

import { useAuth } from "../auth/AuthProvider";

export function ProtectedRoute() {
  const location = useLocation();
  const { isLoading, user } = useAuth();

  if (isLoading) {
    return (
      <div className="min-h-screen bg-slate-950 text-slate-100">
        <div className="mx-auto flex min-h-screen max-w-2xl items-center justify-center px-6">
          <div className="rounded-3xl border border-white/10 bg-white/5 px-6 py-5 text-sm text-slate-300 shadow-2xl shadow-slate-950/40">
            세션을 확인하고 있습니다.
          </div>
        </div>
      </div>
    );
  }

  if (!user) {
    return (
      <Navigate
        to="/login"
        replace
        state={{ from: `${location.pathname}${location.search}` }}
      />
    );
  }

  return <Outlet />;
}
