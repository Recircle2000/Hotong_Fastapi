import type { ReactNode } from "react";
import { NavLink, useNavigate } from "react-router-dom";

import { useAuth } from "../auth/AuthProvider";

const links = [
  ["/notices", "공지 관리"],
  ["/emergency-notices", "긴급공지 관리"],
  ["/shuttle", "셔틀 관리"],
  ["/shuttle-stations", "정류장 관리"],
  ["/taxi-locations", "택시 거점 관리"],
  ["/taxi-parties", "택시팟 현황"],
] as const;

export function AdminShell({
  actions,
  children,
  description,
  title,
}: {
  actions?: ReactNode;
  children: ReactNode;
  description: string;
  title: string;
}) {
  const navigate = useNavigate();
  const { logout, user } = useAuth();

  async function handleLogout() {
    await logout();
    navigate("/login", { replace: true });
  }

  return (
    <div className="min-h-screen bg-slate-100 text-slate-900 lg:pl-60">
      <aside className="fixed inset-y-0 left-0 z-30 hidden w-60 border-r border-slate-200 bg-slate-900 text-white lg:flex lg:flex-col">
        <div className="border-b border-white/10 px-6 py-5 text-lg font-semibold">호통 대시보드</div>
        <nav className="min-h-0 flex-1 overflow-y-auto px-4 py-4 pb-24">
          {links.map(([path, label], index) => (
            <NavLink
              key={path}
              to={path}
              className={({ isActive }) =>
                `${index ? "mt-2 " : ""}block rounded-lg px-4 py-3 text-sm transition ${
                  isActive
                    ? "bg-white/10 text-white"
                    : "text-slate-300 hover:bg-white/10 hover:text-white"
                }`
              }
            >
              {label}
            </NavLink>
          ))}
        </nav>
        <div className="absolute inset-x-0 bottom-0 border-t border-white/10 bg-slate-900/95 p-4">
          <button type="button" onClick={handleLogout} className="w-full rounded-lg bg-white/10 px-4 py-3 text-sm">
            로그아웃
          </button>
        </div>
      </aside>

      <header className="border-b border-slate-200 bg-white">
        <div className="flex flex-col gap-4 px-4 py-4 sm:px-6 lg:px-8">
          <div className="flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
            <div>
              <h1 className="text-2xl font-semibold">{title}</h1>
              <p className="mt-1 text-sm text-slate-500">{description}</p>
            </div>
            <div className="flex flex-wrap items-center gap-2">
              <span className="rounded-lg border border-slate-200 bg-slate-50 px-3 py-2 text-sm text-slate-600">
                {user?.email}
              </span>
              {actions}
              <button type="button" onClick={handleLogout} className="rounded-lg border border-slate-300 bg-white px-4 py-2 text-sm lg:hidden">
                로그아웃
              </button>
            </div>
          </div>
          <nav className="flex gap-2 overflow-x-auto lg:hidden">
            {links.map(([path, label]) => (
              <NavLink
                key={path}
                to={path}
                className={({ isActive }) =>
                  `whitespace-nowrap rounded-lg border px-3 py-2 text-sm ${
                    isActive ? "border-slate-900 bg-slate-900 text-white" : "border-slate-300 bg-white"
                  }`
                }
              >
                {label}
              </NavLink>
            ))}
          </nav>
        </div>
      </header>
      <main className="px-4 py-6 sm:px-6 lg:px-8">{children}</main>
    </div>
  );
}
