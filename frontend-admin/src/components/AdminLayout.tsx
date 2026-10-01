import { useEffect, useState } from "react";
import { NavLink, Outlet, useLocation, useNavigate } from "react-router-dom";

import { useAuth } from "../auth/AuthProvider";
import { navGroups } from "../lib/navigation";

/** 로그인한 페이지 공통 레이아웃. 라우터가 한 번만 그려 페이지를 옮겨도 메뉴가 유지된다. */
export function AdminLayout() {
  const navigate = useNavigate();
  const location = useLocation();
  const { logout, user } = useAuth();
  const [drawerOpen, setDrawerOpen] = useState(false);

  // 페이지를 옮기면 모바일 메뉴를 닫는다.
  useEffect(() => { setDrawerOpen(false); }, [location.pathname]);

  useEffect(() => {
    if (!drawerOpen) return;
    const onKeyDown = (event: KeyboardEvent) => {
      if (event.key === "Escape") setDrawerOpen(false);
    };
    window.addEventListener("keydown", onKeyDown);
    return () => window.removeEventListener("keydown", onKeyDown);
  }, [drawerOpen]);

  async function handleLogout() {
    await logout();
    navigate("/login", { replace: true });
  }

  const sidebar = (
    <div className="flex h-full flex-col bg-slate-900 text-white">
      <div className="border-b border-white/10 px-6 py-5 text-lg font-semibold">호통 대시보드</div>
      <nav aria-label="대시보드 메뉴" className="min-h-0 flex-1 overflow-y-auto px-3 py-4">
        {navGroups.map((group, groupIndex) => (
          <section key={group.label} className={groupIndex ? "mt-6" : ""}>
            <h2 className="px-3 pb-2 text-xs font-semibold tracking-wide text-slate-400">{group.label}</h2>
            <ul className="space-y-1">
              {group.items.map((item) => (
                <li key={item.path}>
                  <NavLink
                    to={item.path}
                    // "/shuttle"이 "/shuttle/timetable"에서도 켜지지 않게 정확히 일치할 때만 표시한다.
                    end
                    className={({ isActive }) =>
                      `relative block rounded-lg px-3 py-2.5 text-sm transition ${
                        isActive
                          ? "bg-white/10 font-semibold text-white before:absolute before:inset-y-2 before:left-0 before:w-1 before:rounded-full before:bg-blue-400"
                          : "text-slate-300 hover:bg-white/5 hover:text-white"
                      }`
                    }
                  >
                    {item.label}
                  </NavLink>
                </li>
              ))}
            </ul>
          </section>
        ))}
      </nav>
      <div className="border-t border-white/10 p-4">
        <p className="mb-3 truncate text-xs text-slate-400" title={user?.email}>{user?.email}</p>
        <button type="button" onClick={() => void handleLogout()} className="w-full rounded-lg bg-white/10 px-4 py-2.5 text-sm transition hover:bg-white/15">
          로그아웃
        </button>
      </div>
    </div>
  );

  return (
    <div className="min-h-screen bg-slate-100 text-slate-900 lg:pl-60">
      <aside className="fixed inset-y-0 left-0 z-30 hidden w-60 border-r border-slate-200 lg:block">{sidebar}</aside>

      <div className="sticky top-0 z-20 flex items-center gap-3 border-b border-slate-800 bg-slate-900 px-4 py-3 text-white lg:hidden">
        <button
          type="button"
          onClick={() => setDrawerOpen(true)}
          aria-label="메뉴 열기"
          aria-expanded={drawerOpen}
          className="rounded-lg p-2 hover:bg-white/10"
        >
          <svg aria-hidden="true" viewBox="0 0 24 24" className="h-5 w-5" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round">
            <path d="M4 6h16M4 12h16M4 18h16" />
          </svg>
        </button>
        <span className="font-semibold">호통 대시보드</span>
      </div>

      {drawerOpen ? (
        <div className="fixed inset-0 z-40 lg:hidden" role="dialog" aria-modal="true" aria-label="대시보드 메뉴">
          <div className="modal-backdrop-motion absolute inset-0 bg-slate-950/50" onClick={() => setDrawerOpen(false)} />
          <div className="absolute inset-y-0 left-0 w-72 max-w-[85vw] shadow-xl">{sidebar}</div>
        </div>
      ) : null}

      <Outlet />
    </div>
  );
}
