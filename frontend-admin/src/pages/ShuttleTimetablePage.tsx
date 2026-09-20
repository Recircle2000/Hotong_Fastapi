import { useCallback, useEffect, useMemo, useState } from "react";
import { NavLink, useNavigate } from "react-router-dom";

import { useAuth } from "../auth/AuthProvider";
import { AdminPanel } from "../components/AdminPanel";
import { useDocumentTitle } from "../hooks/useDocumentTitle";
import { ApiError, getAdminShuttleTimetable } from "../lib/api";
import type { ShuttleTimetableSection } from "../lib/shuttleTypes";

const DESKTOP_NAV_CLASS = ({ isActive }: { isActive: boolean }) =>
  `mt-2 block rounded-lg px-4 py-3 text-sm transition ${
    isActive
      ? "bg-white/10 text-white"
      : "text-slate-300 hover:bg-white/10 hover:text-white"
  }`;

export function ShuttleTimetablePage() {
  const navigate = useNavigate();
  const { logout, user } = useAuth();
  useDocumentTitle("전체 셔틀 시간표");

  const [sections, setSections] = useState<ShuttleTimetableSection[]>([]);
  const [isLoading, setIsLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const totals = useMemo(
    () => ({
      routeCount: sections.reduce((sum, section) => sum + section.route_count, 0),
      scheduleCount: sections.reduce((sum, section) => sum + section.schedule_count, 0),
    }),
    [sections],
  );

  const loadTimetable = useCallback(async () => {
    setError(null);
    setIsLoading(true);

    try {
      setSections(await getAdminShuttleTimetable());
    } catch (loadError) {
      if (loadError instanceof ApiError && loadError.status === 401) {
        await logout();
        navigate("/login", {
          replace: true,
          state: { from: "/shuttle/timetable" },
        });
        return;
      }

      setError(
        loadError instanceof ApiError
          ? loadError.message
          : "전체 시간표를 불러오지 못했습니다.",
      );
    } finally {
      setIsLoading(false);
    }
  }, [logout, navigate]);

  useEffect(() => {
    void loadTimetable();
  }, [loadTimetable]);

  async function handleLogout() {
    await logout();
    navigate("/login", { replace: true });
  }

  return (
    <div className="min-h-screen bg-slate-100 text-slate-900 lg:pl-60">
      <aside className="fixed inset-y-0 left-0 z-30 hidden w-60 border-r border-slate-200 bg-slate-900 text-white lg:flex lg:flex-col">
        <div className="border-b border-white/10 px-6 py-5 text-lg font-semibold">
          호통 대시보드
        </div>
        <nav className="min-h-0 flex-1 overflow-y-auto px-4 py-4 pb-24">
          <NavLink
            to="/notices"
            className={({ isActive }) =>
              `block rounded-lg px-4 py-3 text-sm transition ${
                isActive
                  ? "bg-white/10 text-white"
                  : "text-slate-300 hover:bg-white/10 hover:text-white"
              }`
            }
          >
            공지 관리
          </NavLink>
          <NavLink to="/emergency-notices" className={DESKTOP_NAV_CLASS}>
            긴급공지 관리
          </NavLink>
          <NavLink to="/shuttle" end className={DESKTOP_NAV_CLASS}>
            셔틀 관리
          </NavLink>
          <NavLink to="/shuttle-stations" className={DESKTOP_NAV_CLASS}>
            정류장 관리
          </NavLink>
          <NavLink to="/shuttle/timetable" className={DESKTOP_NAV_CLASS}>
            전체 시간표
          </NavLink>
        </nav>
        <div className="absolute inset-x-0 bottom-0 border-t border-white/10 bg-slate-900/95 p-4 backdrop-blur">
          <button
            type="button"
            onClick={() => void handleLogout()}
            className="w-full rounded-lg bg-white/10 px-4 py-3 text-sm font-medium text-white transition hover:bg-white/15"
          >
            로그아웃
          </button>
        </div>
      </aside>

      <div className="min-h-screen">
        <header className="border-b border-slate-200 bg-white">
          <div className="flex flex-col gap-4 px-4 py-5 sm:px-6 lg:px-8">
            <div className="motion-enter flex flex-col gap-4 sm:flex-row sm:items-center sm:justify-between">
              <div>
                <h1 className="text-2xl font-semibold text-slate-900">
                  전체 셔틀버스 시간표
                </h1>
                <p className="mt-1 text-sm text-slate-500">
                  일정 유형별로 모든 노선의 정류장 도착 시간을 확인합니다.
                </p>
              </div>
              <div className="flex flex-wrap items-center gap-2">
                <NavLink
                  to="/shuttle"
                  className="rounded-lg border border-slate-300 bg-white px-4 py-2 text-sm font-medium text-slate-700 transition hover:bg-slate-50"
                >
                  셔틀 관리로 돌아가기
                </NavLink>
                <div className="rounded-lg border border-slate-200 bg-slate-50 px-3 py-2 text-sm text-slate-600">
                  {user?.email}
                </div>
                <button
                  type="button"
                  onClick={() => void handleLogout()}
                  className="rounded-lg border border-slate-300 bg-white px-4 py-2 text-sm font-medium text-slate-700 transition hover:bg-slate-50 lg:hidden"
                >
                  로그아웃
                </button>
              </div>
            </div>

            {!isLoading && !error && sections.length > 0 ? (
              <div className="motion-enter motion-enter-delay-1 grid gap-3 sm:grid-cols-3 xl:max-w-3xl">
                <Summary label="일정 유형" value={`${sections.length}개`} />
                <Summary label="노선 표" value={`${totals.routeCount}개`} />
                <Summary label="전체 운행" value={`${totals.scheduleCount}회`} />
              </div>
            ) : null}
          </div>
        </header>

        <main className="motion-enter motion-enter-delay-2 px-4 py-6 sm:px-6 lg:px-8">
          {isLoading ? (
            <AdminPanel title="전체 시간표 로딩">
              <div className="text-sm text-slate-500">
                노선과 정류장별 시간을 불러오는 중입니다.
              </div>
            </AdminPanel>
          ) : error ? (
            <AdminPanel title="시간표를 불러오지 못했습니다">
              <div className="flex flex-col items-start gap-4">
                <p className="text-sm text-rose-600">{error}</p>
                <button
                  type="button"
                  onClick={() => void loadTimetable()}
                  className="rounded-lg bg-blue-600 px-4 py-2 text-sm font-semibold text-white transition hover:bg-blue-700"
                >
                  다시 시도
                </button>
              </div>
            </AdminPanel>
          ) : sections.length === 0 ? (
            <AdminPanel title="등록된 시간표가 없습니다">
              <p className="text-sm text-slate-500">
                셔틀 관리에서 시간표를 등록하면 이곳에 표시됩니다.
              </p>
            </AdminPanel>
          ) : (
            <>
              <section className="rounded-2xl border border-slate-200 bg-white p-5 shadow-sm">
                <h2 className="text-base font-semibold text-slate-900">일정 유형 바로가기</h2>
                <nav
                  className="mt-4 flex flex-wrap gap-2"
                  aria-label="일정 유형 바로가기"
                >
                  {sections.map((section) => (
                    <a
                      key={section.schedule_type}
                      href={`#${section.anchor_id}`}
                      className="inline-flex items-center gap-2 rounded-full border border-blue-200 bg-blue-50 px-4 py-2 text-sm font-semibold text-blue-700 transition hover:border-blue-600 hover:bg-blue-600 hover:text-white"
                    >
                      <span>{section.schedule_type_name}</span>
                      <span className="rounded-full bg-white/80 px-2 py-0.5 text-xs text-blue-700">
                        {section.schedule_count}
                      </span>
                    </a>
                  ))}
                </nav>
              </section>

              <div className="mt-6 space-y-8">
                {sections.map((section) => (
                  <section
                    key={section.schedule_type}
                    id={section.anchor_id}
                    className="scroll-mt-6"
                  >
                    <div className="mb-4 flex flex-col gap-2 sm:flex-row sm:items-end sm:justify-between">
                      <div className="flex flex-wrap items-center gap-2">
                        <h2 className="text-xl font-semibold text-slate-900">
                          {section.schedule_type_name}
                        </h2>
                        {!section.is_active ? (
                          <span className="rounded-full border border-amber-200 bg-amber-50 px-2.5 py-1 text-xs font-semibold text-amber-700">
                            비활성
                          </span>
                        ) : null}
                      </div>
                      <p className="text-sm text-slate-500">
                        {section.route_count}개 노선 · {section.schedule_count}회 운행
                      </p>
                    </div>

                    <div className="space-y-5">
                      {section.routes.map((route) => (
                        <article
                          key={`${section.schedule_type}-${route.route_id}`}
                          className="overflow-hidden rounded-2xl border border-slate-200 bg-white shadow-sm"
                        >
                          <div className="flex flex-col gap-1 border-b border-slate-200 bg-slate-50 px-5 py-4 sm:flex-row sm:items-center sm:justify-between">
                            <h3 className="font-semibold text-slate-900">{route.route_name}</h3>
                            <span className="text-sm text-slate-500">
                              {route.schedule_count}회 운행
                            </span>
                          </div>

                          <div
                            className="max-w-full overflow-x-auto"
                            role="region"
                            aria-label={`${section.schedule_type_name} ${route.route_name} 시간표`}
                            tabIndex={0}
                          >
                            <table className="min-w-max border-separate border-spacing-0 text-sm">
                              <thead>
                                <tr>
                                  <th
                                    scope="col"
                                    className="sticky left-0 top-0 z-30 min-w-16 border-b border-r border-slate-200 bg-blue-100 px-4 py-3 text-center font-semibold text-slate-800"
                                  >
                                    회차
                                  </th>
                                  {route.stations.map((station) => (
                                    <th
                                      key={station.station_id}
                                      scope="col"
                                      className="sticky top-0 z-20 min-w-32 max-w-48 border-b border-r border-slate-200 bg-blue-50 px-4 py-3 text-center font-semibold text-slate-800 last:border-r-0"
                                    >
                                      <span className="whitespace-normal break-keep">
                                        {station.station_name}
                                      </span>
                                    </th>
                                  ))}
                                </tr>
                              </thead>
                              <tbody>
                                {route.rows.map((row) => (
                                  <tr key={row.schedule_id} className="group">
                                    <th
                                      scope="row"
                                      className="sticky left-0 z-10 border-b border-r border-slate-200 bg-slate-50 px-4 py-3 text-center font-semibold text-blue-700 group-last:border-b-0 group-hover:bg-blue-50"
                                    >
                                      {row.number}
                                    </th>
                                    {row.times.map((time, index) => (
                                      <td
                                        key={`${row.schedule_id}-${route.stations[index]?.station_id ?? index}`}
                                        className={`border-b border-r border-slate-200 px-4 py-3 text-center last:border-r-0 group-last:border-b-0 group-hover:bg-blue-50/40 ${
                                          time === "—" ? "text-slate-300" : "text-slate-700"
                                        }`}
                                      >
                                        {time}
                                      </td>
                                    ))}
                                  </tr>
                                ))}
                              </tbody>
                            </table>
                          </div>
                        </article>
                      ))}
                    </div>
                  </section>
                ))}
              </div>
            </>
          )}
        </main>
      </div>
    </div>
  );
}

function Summary({ label, value }: { label: string; value: string }) {
  return (
    <div className="rounded-xl border border-slate-200 bg-slate-50 px-4 py-3">
      <div className="text-xs font-medium text-slate-500">{label}</div>
      <div className="mt-1 text-lg font-semibold text-slate-900">{value}</div>
    </div>
  );
}
