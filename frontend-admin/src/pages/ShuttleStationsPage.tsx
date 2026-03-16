import { FormEvent, useEffect, useState } from "react";
import { NavLink, useNavigate } from "react-router-dom";

import { useAuth } from "../auth/AuthProvider";
import { AdminModal } from "../components/AdminModal";
import { AdminPanel } from "../components/AdminPanel";
import { useDocumentTitle } from "../hooks/useDocumentTitle";
import {
  ApiError,
  createAdminShuttleStation,
  deleteAdminShuttleStation,
  getAdminShuttleStations,
  updateAdminShuttleStation,
} from "../lib/api";
import type {
  AdminShuttleStation,
  AdminShuttleStationPayload,
} from "../lib/types";
import { useToast } from "../toast/ToastProvider";

type FormMode = "create" | "edit";

type StationFormState = {
  name: string;
  latitude: string;
  longitude: string;
  description: string;
  image_url: string;
  is_active: boolean;
};

const EMPTY_FORM: StationFormState = {
  name: "",
  latitude: "",
  longitude: "",
  description: "",
  image_url: "",
  is_active: true,
};

function SummaryCard({ label, value }: { label: string; value: string }) {
  return (
    <div className="rounded-xl border border-slate-200 bg-slate-50 px-4 py-4">
      <div className="text-xs font-medium text-slate-500">{label}</div>
      <div className="mt-2 text-2xl font-semibold text-slate-900">{value}</div>
    </div>
  );
}

function formatCoordinate(value: number) {
  return value.toFixed(6);
}

function toFormState(station: AdminShuttleStation): StationFormState {
  return {
    name: station.name,
    latitude: String(station.latitude),
    longitude: String(station.longitude),
    description: station.description ?? "",
    image_url: station.image_url ?? "",
    is_active: station.is_active,
  };
}

function toPayload(formState: StationFormState): AdminShuttleStationPayload | null {
  const latitude = Number(formState.latitude);
  const longitude = Number(formState.longitude);

  if (!Number.isFinite(latitude) || !Number.isFinite(longitude)) {
    return null;
  }

  return {
    name: formState.name.trim(),
    latitude,
    longitude,
    description: formState.description.trim() || null,
    image_url: formState.image_url.trim() || null,
    is_active: formState.is_active,
  };
}

export function ShuttleStationsPage() {
  const navigate = useNavigate();
  const { logout, user } = useAuth();
  const { showToast } = useToast();
  useDocumentTitle("셔틀 정류장 관리");

  const [stations, setStations] = useState<AdminShuttleStation[]>([]);
  const [isLoading, setIsLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [detailStation, setDetailStation] = useState<AdminShuttleStation | null>(null);
  const [formMode, setFormMode] = useState<FormMode>("create");
  const [editingStation, setEditingStation] = useState<AdminShuttleStation | null>(null);
  const [formState, setFormState] = useState<StationFormState>(EMPTY_FORM);
  const [isFormOpen, setIsFormOpen] = useState(false);
  const [isSaving, setIsSaving] = useState(false);
  const [formError, setFormError] = useState<string | null>(null);

  const activeCount = stations.filter((station) => station.is_active).length;
  const inactiveCount = stations.length - activeCount;

  async function handleUnauthorized() {
    await logout();
    navigate("/login", { replace: true, state: { from: "/shuttle-stations" } });
  }

  async function loadStations() {
    setError(null);
    setIsLoading(true);

    try {
      const nextStations = await getAdminShuttleStations();
      setStations(nextStations);
    } catch (loadError) {
      if (loadError instanceof ApiError) {
        if (loadError.status === 401) {
          await handleUnauthorized();
          return;
        }
        setError(loadError.message);
      } else {
        setError("정류장 목록을 불러오지 못했습니다.");
      }
    } finally {
      setIsLoading(false);
    }
  }

  useEffect(() => {
    void loadStations();
  }, []);

  function openCreateModal() {
    setFormMode("create");
    setEditingStation(null);
    setFormState(EMPTY_FORM);
    setFormError(null);
    setIsFormOpen(true);
  }

  function openEditModal(station: AdminShuttleStation) {
    setFormMode("edit");
    setEditingStation(station);
    setFormState(toFormState(station));
    setFormError(null);
    setIsFormOpen(true);
  }

  async function handleDelete(station: AdminShuttleStation) {
    if (!window.confirm(`"${station.name}" 정류장을 삭제하시겠습니까?`)) {
      return;
    }

    try {
      await deleteAdminShuttleStation(station.id);
      showToast("정류장을 삭제했습니다.", "success");
      await loadStations();
      if (detailStation?.id === station.id) {
        setDetailStation(null);
      }
    } catch (deleteError) {
      if (deleteError instanceof ApiError) {
        if (deleteError.status === 401) {
          await handleUnauthorized();
          return;
        }
        showToast(deleteError.message, "error");
      } else {
        showToast("정류장 삭제 중 오류가 발생했습니다.", "error");
      }
    }
  }

  async function handleLogout() {
    await logout();
    navigate("/login", { replace: true });
  }

  async function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setFormError(null);

    if (!formState.name.trim()) {
      setFormError("정류장 이름을 입력해주세요.");
      return;
    }

    const payload = toPayload(formState);
    if (!payload) {
      setFormError("위도와 경도는 숫자로 입력해주세요.");
      return;
    }

    setIsSaving(true);

    try {
      if (formMode === "create") {
        await createAdminShuttleStation(payload);
        showToast("정류장을 등록했습니다.", "success");
      } else if (editingStation) {
        await updateAdminShuttleStation(editingStation.id, payload);
        showToast("정류장을 수정했습니다.", "success");
      }

      setIsFormOpen(false);
      await loadStations();
    } catch (submitError) {
      if (submitError instanceof ApiError) {
        if (submitError.status === 401) {
          await handleUnauthorized();
          return;
        }
        setFormError(submitError.message);
      } else {
        setFormError("정류장 저장 중 오류가 발생했습니다.");
      }
    } finally {
      setIsSaving(false);
    }
  }

  return (
    <div className="min-h-screen bg-slate-100 text-slate-900 lg:pl-60">
      <aside className="fixed inset-y-0 left-0 z-30 hidden w-60 flex-col border-r border-slate-200 bg-slate-900 text-white lg:flex">
        <div className="border-b border-white/10 px-6 py-5">
          <div className="text-lg font-semibold">교통 대시보드</div>
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
          <NavLink
            to="/emergency-notices"
            className={({ isActive }) =>
              `mt-2 block rounded-lg px-4 py-3 text-sm transition ${
                isActive
                  ? "bg-white/10 text-white"
                  : "text-slate-300 hover:bg-white/10 hover:text-white"
              }`
            }
          >
            긴급공지 관리
          </NavLink>
          <NavLink
            to="/shuttle"
            className={({ isActive }) =>
              `mt-2 block rounded-lg px-4 py-3 text-sm transition ${
                isActive
                  ? "bg-white/10 text-white"
                  : "text-slate-300 hover:bg-white/10 hover:text-white"
              }`
            }
          >
            셔틀 관리
          </NavLink>
          <NavLink
            to="/shuttle-stations"
            className={({ isActive }) =>
              `mt-2 block rounded-lg px-4 py-3 text-sm transition ${
                isActive
                  ? "bg-white/10 text-white"
                  : "text-slate-300 hover:bg-white/10 hover:text-white"
              }`
            }
          >
            정류장 관리
          </NavLink>
        </nav>
        <div className="absolute inset-x-0 bottom-0 border-t border-white/10 bg-slate-900/95 p-4 backdrop-blur">
          <button
            type="button"
            onClick={handleLogout}
            className="w-full rounded-lg bg-white/10 px-4 py-3 text-sm font-medium text-white transition hover:bg-white/15"
          >
            로그아웃
          </button>
        </div>
      </aside>

      <div className="min-h-screen min-w-0">
        <header className="border-b border-slate-200 bg-white">
          <div className="flex flex-col gap-4 px-4 py-4 sm:px-6 lg:px-8">
            <div className="motion-enter flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
              <div>
                <h1 className="text-2xl font-semibold text-slate-900">셔틀 정류장 관리</h1>
                <p className="mt-1 text-sm text-slate-500">
                  셔틀 정류장 정보와 활성 상태를 관리합니다.
                </p>
              </div>
              <div className="flex flex-wrap items-center gap-2">
                <div className="rounded-lg border border-slate-200 bg-slate-50 px-3 py-2 text-sm text-slate-600">
                  {user?.email}
                </div>
                <NavLink
                  to="/notices"
                  className={({ isActive }) =>
                    `rounded-lg border px-4 py-2 text-sm font-medium transition lg:hidden ${
                      isActive
                        ? "border-slate-900 bg-slate-900 text-white"
                        : "border-slate-300 bg-white text-slate-700 hover:bg-slate-50"
                    }`
                  }
                >
                  공지
                </NavLink>
                <NavLink
                  to="/emergency-notices"
                  className={({ isActive }) =>
                    `rounded-lg border px-4 py-2 text-sm font-medium transition lg:hidden ${
                      isActive
                        ? "border-slate-900 bg-slate-900 text-white"
                        : "border-slate-300 bg-white text-slate-700 hover:bg-slate-50"
                    }`
                  }
                >
                  긴급공지
                </NavLink>
                <NavLink
                  to="/shuttle"
                  className={({ isActive }) =>
                    `rounded-lg border px-4 py-2 text-sm font-medium transition lg:hidden ${
                      isActive
                        ? "border-slate-900 bg-slate-900 text-white"
                        : "border-slate-300 bg-white text-slate-700 hover:bg-slate-50"
                    }`
                  }
                >
                  셔틀
                </NavLink>
                <NavLink
                  to="/shuttle-stations"
                  className={({ isActive }) =>
                    `rounded-lg border px-4 py-2 text-sm font-medium transition lg:hidden ${
                      isActive
                        ? "border-slate-900 bg-slate-900 text-white"
                        : "border-slate-300 bg-white text-slate-700 hover:bg-slate-50"
                    }`
                  }
                >
                  정류장
                </NavLink>
                <button
                  type="button"
                  onClick={handleLogout}
                  className="rounded-lg border border-slate-300 bg-white px-4 py-2 text-sm font-medium text-slate-700 transition hover:bg-slate-50 lg:hidden"
                >
                  로그아웃
                </button>
                <button
                  type="button"
                  onClick={openCreateModal}
                  className="rounded-lg bg-blue-600 px-4 py-2 text-sm font-semibold text-white transition hover:bg-blue-700"
                >
                  정류장 추가
                </button>
              </div>
            </div>

            <div className="motion-enter motion-enter-delay-1 grid gap-3 sm:grid-cols-3 xl:max-w-3xl">
              <SummaryCard label="전체 정류장" value={String(stations.length)} />
              <SummaryCard label="활성 정류장" value={String(activeCount)} />
              <SummaryCard label="비활성 정류장" value={String(inactiveCount)} />
            </div>
          </div>
        </header>

        <main className="motion-enter motion-enter-delay-2 px-4 py-6 sm:px-6 lg:px-8">
          {error ? (
            <div className="mb-4 rounded-lg border border-rose-200 bg-rose-50 px-4 py-3 text-sm text-rose-700">
              {error}
            </div>
          ) : null}

          <AdminPanel title="셔틀 정류장 목록">
            {isLoading ? (
              <div className="py-10 text-sm text-slate-500">정류장 목록을 불러오는 중입니다.</div>
            ) : stations.length === 0 ? (
              <div className="py-10 text-sm text-slate-500">등록된 정류장이 없습니다.</div>
            ) : (
              <>
                <div className="hidden overflow-x-auto lg:block">
                  <table className="min-w-full text-left text-sm">
                    <thead className="bg-slate-50 text-slate-600">
                      <tr>
                        <th className="px-5 py-3 font-medium">정류장</th>
                        <th className="px-5 py-3 font-medium">상태</th>
                        <th className="px-5 py-3 font-medium">좌표</th>
                        <th className="px-5 py-3 font-medium">설명</th>
                        <th className="px-5 py-3 font-medium">이미지</th>
                        <th className="px-5 py-3 font-medium">관리</th>
                      </tr>
                    </thead>
                    <tbody>
                      {stations.map((station) => (
                        <tr key={station.id} className="border-t border-slate-200">
                          <td className="px-5 py-4">
                            <button
                              type="button"
                              className="font-medium text-slate-900 hover:text-blue-700"
                              onClick={() => setDetailStation(station)}
                            >
                              {station.name}
                            </button>
                          </td>
                          <td className="px-5 py-4">
                            <span
                              className={`inline-flex rounded-full px-3 py-1 text-xs font-semibold ${
                                station.is_active
                                  ? "border border-emerald-200 bg-emerald-50 text-emerald-700"
                                  : "border border-slate-200 bg-slate-100 text-slate-600"
                              }`}
                            >
                              {station.is_active ? "활성" : "비활성"}
                            </span>
                          </td>
                          <td className="px-5 py-4 text-slate-500">
                            {formatCoordinate(station.latitude)}, {formatCoordinate(station.longitude)}
                          </td>
                          <td className="px-5 py-4 text-slate-500">
                            <div className="max-w-[320px] truncate">
                              {station.description ?? "-"}
                            </div>
                          </td>
                          <td className="px-5 py-4 text-slate-500">
                            {station.image_url ? "등록됨" : "-"}
                          </td>
                          <td className="px-5 py-4">
                            <div className="flex gap-2">
                              <button
                                type="button"
                                onClick={() => openEditModal(station)}
                                className="rounded-lg border border-slate-300 bg-white px-3 py-2 text-xs font-medium text-slate-700 transition hover:bg-slate-50"
                              >
                                수정
                              </button>
                              <button
                                type="button"
                                onClick={() => handleDelete(station)}
                                className="rounded-lg border border-rose-200 bg-rose-50 px-3 py-2 text-xs font-medium text-rose-700 transition hover:bg-rose-100"
                              >
                                삭제
                              </button>
                            </div>
                          </td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>

                <div className="grid gap-3 lg:hidden">
                  {stations.map((station) => (
                    <article
                      key={station.id}
                      className="rounded-xl border border-slate-200 bg-slate-50 p-4"
                    >
                      <div className="flex items-start justify-between gap-3">
                        <button
                          type="button"
                          className="text-left text-base font-semibold text-slate-900"
                          onClick={() => setDetailStation(station)}
                        >
                          {station.name}
                        </button>
                        <span
                          className={`inline-flex rounded-full px-3 py-1 text-xs font-semibold ${
                            station.is_active
                              ? "border border-emerald-200 bg-emerald-50 text-emerald-700"
                              : "border border-slate-200 bg-slate-100 text-slate-600"
                          }`}
                        >
                          {station.is_active ? "활성" : "비활성"}
                        </span>
                      </div>

                      <div className="mt-3 text-sm text-slate-500">
                        좌표: {formatCoordinate(station.latitude)}, {formatCoordinate(station.longitude)}
                      </div>
                      <div className="mt-2 text-sm text-slate-500">
                        {station.description ?? "설명 없음"}
                      </div>

                      <div className="mt-2 text-sm text-slate-500">
                        이미지: {station.image_url ? "등록됨" : "없음"}
                      </div>

                      <div className="mt-4 flex gap-2">
                        <button
                          type="button"
                          onClick={() => openEditModal(station)}
                          className="rounded-lg border border-slate-300 bg-white px-3 py-2 text-xs font-medium text-slate-700 transition hover:bg-slate-100"
                        >
                          수정
                        </button>
                        <button
                          type="button"
                          onClick={() => handleDelete(station)}
                          className="rounded-lg border border-rose-200 bg-rose-50 px-3 py-2 text-xs font-medium text-rose-700 transition hover:bg-rose-100"
                        >
                          삭제
                        </button>
                      </div>
                    </article>
                  ))}
                </div>
              </>
            )}
          </AdminPanel>
        </main>
      </div>

      {isFormOpen ? (
        <AdminModal
          title={formMode === "create" ? "정류장 등록" : "정류장 수정"}
          onClose={() => setIsFormOpen(false)}
          wide
        >
          <form className="space-y-5" onSubmit={handleSubmit}>
            <label className="block">
              <span className="mb-2 block text-sm font-medium text-slate-700">정류장 이름</span>
              <input
                className="w-full rounded-lg border border-slate-300 bg-white px-4 py-3 text-sm text-slate-900 outline-none transition focus:border-blue-500 focus:ring-4 focus:ring-blue-100"
                value={formState.name}
                onChange={(event) =>
                  setFormState((current) => ({ ...current, name: event.target.value }))
                }
                placeholder="정류장 이름을 입력하세요."
                required
              />
            </label>

            <div className="grid gap-4 md:grid-cols-2">
              <label className="block">
                <span className="mb-2 block text-sm font-medium text-slate-700">위도</span>
                <input
                  type="number"
                  step="any"
                  className="w-full rounded-lg border border-slate-300 bg-white px-4 py-3 text-sm text-slate-900 outline-none transition focus:border-blue-500 focus:ring-4 focus:ring-blue-100"
                  value={formState.latitude}
                  onChange={(event) =>
                    setFormState((current) => ({ ...current, latitude: event.target.value }))
                  }
                  placeholder="36.769100"
                  required
                />
              </label>

              <label className="block">
                <span className="mb-2 block text-sm font-medium text-slate-700">경도</span>
                <input
                  type="number"
                  step="any"
                  className="w-full rounded-lg border border-slate-300 bg-white px-4 py-3 text-sm text-slate-900 outline-none transition focus:border-blue-500 focus:ring-4 focus:ring-blue-100"
                  value={formState.longitude}
                  onChange={(event) =>
                    setFormState((current) => ({ ...current, longitude: event.target.value }))
                  }
                  placeholder="127.073900"
                  required
                />
              </label>
            </div>

            <label className="block">
              <span className="mb-2 block text-sm font-medium text-slate-700">이미지 URL</span>
              <input
                className="w-full rounded-lg border border-slate-300 bg-white px-4 py-3 text-sm text-slate-900 outline-none transition focus:border-blue-500 focus:ring-4 focus:ring-blue-100"
                value={formState.image_url}
                onChange={(event) =>
                  setFormState((current) => ({ ...current, image_url: event.target.value }))
                }
                placeholder="https://example.com/station.jpg"
              />
            </label>

            {formState.image_url.trim() ? (
              <div className="rounded-xl border border-slate-200 bg-slate-50 p-3">
                <div className="mb-2 text-sm font-medium text-slate-700">이미지 미리보기</div>
                <img
                  src={formState.image_url}
                  alt={formState.name || "station-preview"}
                  className="h-48 w-full rounded-lg border border-slate-200 object-cover"
                />
              </div>
            ) : null}

            <label className="block">
              <span className="mb-2 block text-sm font-medium text-slate-700">설명</span>
              <textarea
                className="min-h-28 w-full rounded-lg border border-slate-300 bg-white px-4 py-3 text-sm text-slate-900 outline-none transition focus:border-blue-500 focus:ring-4 focus:ring-blue-100"
                value={formState.description}
                onChange={(event) =>
                  setFormState((current) => ({ ...current, description: event.target.value }))
                }
                placeholder="정류장 설명을 입력하세요."
              />
            </label>

            <label className="inline-flex items-center gap-3 rounded-lg border border-slate-300 bg-slate-50 px-4 py-3 text-sm text-slate-700">
              <input
                type="checkbox"
                className="h-4 w-4 rounded border-slate-300 text-blue-600"
                checked={formState.is_active}
                onChange={(event) =>
                  setFormState((current) => ({
                    ...current,
                    is_active: event.target.checked,
                  }))
                }
              />
              활성 정류장으로 사용
            </label>

            {formError ? (
              <div className="rounded-lg border border-rose-200 bg-rose-50 px-4 py-3 text-sm text-rose-700">
                {formError}
              </div>
            ) : null}

            <div className="flex flex-col-reverse gap-3 sm:flex-row sm:justify-end">
              <button
                type="button"
                onClick={() => setIsFormOpen(false)}
                className="rounded-lg border border-slate-300 bg-white px-4 py-3 text-sm font-medium text-slate-700 transition hover:bg-slate-50"
              >
                취소
              </button>
              <button
                type="submit"
                className="rounded-lg bg-blue-600 px-4 py-3 text-sm font-semibold text-white transition hover:bg-blue-700 disabled:cursor-not-allowed disabled:bg-blue-300"
                disabled={isSaving}
              >
                {isSaving ? "저장 중..." : formMode === "create" ? "등록" : "수정"}
              </button>
            </div>
          </form>
        </AdminModal>
      ) : null}

      {detailStation ? (
        <AdminModal title={detailStation.name} onClose={() => setDetailStation(null)} wide>
          <div className="grid gap-5 lg:grid-cols-[minmax(0,1fr)_280px]">
            <div>
              <div className="mb-4 flex flex-wrap items-center gap-2 text-sm text-slate-600">
                <span
                  className={`inline-flex rounded-full px-3 py-1 text-xs font-semibold ${
                    detailStation.is_active
                      ? "border border-emerald-200 bg-emerald-50 text-emerald-700"
                      : "border border-slate-200 bg-slate-100 text-slate-600"
                  }`}
                >
                  {detailStation.is_active ? "활성" : "비활성"}
                </span>
                <span>ID {detailStation.id}</span>
              </div>

              <dl className="grid gap-4 sm:grid-cols-2">
                <div className="rounded-xl border border-slate-200 bg-slate-50 p-4">
                  <dt className="text-xs font-medium text-slate-500">위도</dt>
                  <dd className="mt-2 text-sm font-semibold text-slate-900">
                    {formatCoordinate(detailStation.latitude)}
                  </dd>
                </div>
                <div className="rounded-xl border border-slate-200 bg-slate-50 p-4">
                  <dt className="text-xs font-medium text-slate-500">경도</dt>
                  <dd className="mt-2 text-sm font-semibold text-slate-900">
                    {formatCoordinate(detailStation.longitude)}
                  </dd>
                </div>
              </dl>

              <div className="mt-5 rounded-xl border border-slate-200 bg-slate-50 p-4">
                <div className="text-xs font-medium text-slate-500">설명</div>
                <div className="mt-2 whitespace-pre-wrap text-sm text-slate-700">
                  {detailStation.description ?? "설명이 없습니다."}
                </div>
              </div>
            </div>

            <div className="rounded-xl border border-slate-200 bg-slate-50 p-4">
              <div className="mb-3 text-xs font-medium text-slate-500">정류장 이미지</div>
              {detailStation.image_url ? (
                <img
                  src={detailStation.image_url}
                  alt={detailStation.name}
                  className="h-64 w-full rounded-lg border border-slate-200 object-cover"
                />
              ) : (
                <div className="flex h-64 items-center justify-center rounded-lg border border-dashed border-slate-300 bg-white text-sm text-slate-400">
                  이미지가 없습니다.
                </div>
              )}
            </div>
          </div>
        </AdminModal>
      ) : null}
    </div>
  );
}
