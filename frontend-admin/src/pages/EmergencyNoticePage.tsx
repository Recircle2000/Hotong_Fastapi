import { FormEvent, useEffect, useState } from "react";
import { NavLink, useNavigate } from "react-router-dom";

import { useAuth } from "../auth/AuthProvider";
import { AdminModal } from "../components/AdminModal";
import { AdminPanel } from "../components/AdminPanel";
import { ToastEditor } from "../components/ToastEditor";
import { ToastViewer } from "../components/ToastViewer";
import { useDocumentTitle } from "../hooks/useDocumentTitle";
import {
  ApiError,
  createEmergencyNotice,
  deleteEmergencyNotice,
  getEmergencyNotices,
  updateEmergencyNotice,
} from "../lib/api";
import type {
  EmergencyNotice,
  EmergencyNoticeCategory,
  EmergencyNoticePayload,
  EmergencyNoticeStatus,
} from "../lib/types";
import { useToast } from "../toast/ToastProvider";

type FormMode = "create" | "edit";

const CATEGORY_OPTIONS: Array<{ value: EmergencyNoticeCategory; label: string }> = [
  { value: "shuttle", label: "셔틀 긴급공지" },
  { value: "asan_citybus", label: "아산 시내버스 긴급공지" },
  { value: "cheonan_citybus", label: "천안 시내버스 긴급공지" },
  { value: "subway", label: "지하철 긴급공지" },
];

const STATUS_LABEL: Record<EmergencyNoticeStatus, string> = {
  pending: "대기",
  active: "활성",
  expired: "만료",
};

const STATUS_BADGE_CLASS: Record<EmergencyNoticeStatus, string> = {
  pending: "border border-amber-200 bg-amber-50 text-amber-700",
  active: "border border-emerald-200 bg-emerald-50 text-emerald-700",
  expired: "border border-rose-200 bg-rose-50 text-rose-700",
};

const CATEGORY_BADGE_CLASS: Record<EmergencyNoticeCategory, string> = {
  shuttle: "border border-blue-200 bg-blue-50 text-blue-700",
  asan_citybus: "border border-cyan-200 bg-cyan-50 text-cyan-700",
  cheonan_citybus: "border border-violet-200 bg-violet-50 text-violet-700",
  subway: "border border-slate-200 bg-slate-100 text-slate-700",
};

const EMPTY_FORM: EmergencyNoticePayload = {
  category: "shuttle",
  title: "",
  content: "",
  created_at: "",
  end_at: "",
};

function formatDateTime(value: string) {
  return new Intl.DateTimeFormat("ko-KR", {
    year: "numeric",
    month: "2-digit",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
  }).format(new Date(value));
}

function toInputDateTime(value: string) {
  return value.slice(0, 16);
}

function createDefaultForm(): EmergencyNoticePayload {
  const now = new Date();
  const end = new Date(now.getTime() + 60 * 60 * 1000);

  const toLocalInputValue = (date: Date) => {
    const offset = date.getTimezoneOffset() * 60 * 1000;
    return new Date(date.getTime() - offset).toISOString().slice(0, 16);
  };

  return {
    ...EMPTY_FORM,
    created_at: toLocalInputValue(now),
    end_at: toLocalInputValue(end),
  };
}

function SummaryCard({ label, value }: { label: string; value: string }) {
  return (
    <div className="rounded-xl border border-slate-200 bg-slate-50 px-4 py-4">
      <div className="text-xs font-medium text-slate-500">{label}</div>
      <div className="mt-2 text-2xl font-semibold text-slate-900">{value}</div>
    </div>
  );
}

export function EmergencyNoticePage() {
  const navigate = useNavigate();
  const { logout, user } = useAuth();
  const { showToast } = useToast();
  useDocumentTitle("긴급공지 관리");

  const [notices, setNotices] = useState<EmergencyNotice[]>([]);
  const [isLoading, setIsLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [detailNotice, setDetailNotice] = useState<EmergencyNotice | null>(null);
  const [formMode, setFormMode] = useState<FormMode>("create");
  const [editingNotice, setEditingNotice] = useState<EmergencyNotice | null>(null);
  const [formState, setFormState] = useState<EmergencyNoticePayload>(createDefaultForm);
  const [isFormOpen, setIsFormOpen] = useState(false);
  const [isSaving, setIsSaving] = useState(false);
  const [formError, setFormError] = useState<string | null>(null);

  const activeCount = notices.filter((notice) => notice.status === "active").length;
  const pendingCount = notices.filter((notice) => notice.status === "pending").length;

  async function handleUnauthorized() {
    await logout();
    navigate("/login", { replace: true, state: { from: "/emergency-notices" } });
  }

  async function loadEmergencyNotices() {
    setError(null);
    setIsLoading(true);

    try {
      const nextNotices = await getEmergencyNotices();
      setNotices(nextNotices);
    } catch (loadError) {
      if (loadError instanceof ApiError) {
        if (loadError.status === 401) {
          await handleUnauthorized();
          return;
        }
        setError(loadError.message);
      } else {
        setError("긴급공지 목록을 불러오지 못했습니다.");
      }
    } finally {
      setIsLoading(false);
    }
  }

  useEffect(() => {
    void loadEmergencyNotices();
  }, []);

  function openCreateModal() {
    setFormMode("create");
    setEditingNotice(null);
    setFormState(createDefaultForm());
    setFormError(null);
    setIsFormOpen(true);
  }

  function openEditModal(notice: EmergencyNotice) {
    setFormMode("edit");
    setEditingNotice(notice);
    setFormState({
      category: notice.category,
      title: notice.title,
      content: notice.content,
      created_at: toInputDateTime(notice.created_at),
      end_at: toInputDateTime(notice.end_at),
    });
    setFormError(null);
    setIsFormOpen(true);
  }

  async function handleDelete(notice: EmergencyNotice) {
    if (!window.confirm(`"${notice.title}" 긴급공지를 삭제하시겠습니까?`)) {
      return;
    }

    try {
      await deleteEmergencyNotice(notice.id);
      showToast("긴급공지를 삭제했습니다.", "success");
      await loadEmergencyNotices();
      if (detailNotice?.id === notice.id) {
        setDetailNotice(null);
      }
    } catch (deleteError) {
      if (deleteError instanceof ApiError) {
        if (deleteError.status === 401) {
          await handleUnauthorized();
          return;
        }
        showToast(deleteError.message, "error");
      } else {
        showToast("긴급공지 삭제 중 오류가 발생했습니다.", "error");
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

    if (new Date(formState.created_at).getTime() > new Date(formState.end_at).getTime()) {
      setFormError("생성 시각은 종료 시각보다 늦을 수 없습니다.");
      return;
    }

    setIsSaving(true);

    try {
      if (formMode === "create") {
        await createEmergencyNotice(formState);
        showToast("긴급공지를 등록했습니다.", "success");
      } else if (editingNotice) {
        await updateEmergencyNotice(editingNotice.id, formState);
        showToast("긴급공지를 수정했습니다.", "success");
      }

      setIsFormOpen(false);
      await loadEmergencyNotices();
    } catch (submitError) {
      if (submitError instanceof ApiError) {
        if (submitError.status === 401) {
          await handleUnauthorized();
          return;
        }
        setFormError(submitError.message);
      } else {
        setFormError("긴급공지 저장 중 오류가 발생했습니다.");
      }
    } finally {
      setIsSaving(false);
    }
  }

  return (
    <div className="min-h-screen bg-slate-100 text-slate-900 lg:pl-60">
      <aside className="hidden fixed inset-y-0 left-0 z-30 w-60 border-r border-slate-200 bg-slate-900 text-white lg:flex lg:flex-col">
        <div className="border-b border-white/10 px-6 py-5">
          <div className="text-lg font-semibold">호통 대시보드</div>
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
                <h1 className="text-2xl font-semibold text-slate-900">긴급공지 관리</h1>
                <p className="mt-1 text-sm text-slate-500">카테고리별 긴급공지 노출 시간을 관리합니다.</p>
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
                  긴급공지 등록
                </button>
              </div>
            </div>

            <div className="motion-enter motion-enter-delay-1 grid gap-3 sm:grid-cols-3 xl:max-w-3xl">
              <SummaryCard label="전체 긴급공지" value={String(notices.length)} />
              <SummaryCard label="현재 활성" value={String(activeCount)} />
              <SummaryCard label="대기 중" value={String(pendingCount)} />
            </div>
          </div>
        </header>

        <main className="motion-enter motion-enter-delay-2 px-4 py-6 sm:px-6 lg:px-8">
          {error ? (
            <div className="mb-4 rounded-lg border border-rose-200 bg-rose-50 px-4 py-3 text-sm text-rose-700">
              {error}
            </div>
          ) : null}

          <AdminPanel title="긴급공지 목록">
            {isLoading ? (
              <div className="py-10 text-sm text-slate-500">긴급공지 목록을 불러오는 중입니다.</div>
            ) : notices.length === 0 ? (
              <div className="py-10 text-sm text-slate-500">등록된 긴급공지가 없습니다.</div>
            ) : (
              <>
                <div className="hidden overflow-x-auto lg:block">
                  <table className="min-w-full text-left text-sm">
                    <thead className="bg-slate-50 text-slate-600">
                      <tr>
                        <th className="px-5 py-3 font-medium">카테고리</th>
                        <th className="px-5 py-3 font-medium">제목</th>
                        <th className="px-5 py-3 font-medium">상태</th>
                        <th className="px-5 py-3 font-medium">생성 시각</th>
                        <th className="px-5 py-3 font-medium">종료 시각</th>
                        <th className="px-5 py-3 font-medium">관리</th>
                      </tr>
                    </thead>
                    <tbody>
                      {notices.map((notice) => (
                        <tr key={notice.id} className="border-t border-slate-200">
                          <td className="px-5 py-4">
                            <span
                              className={`inline-flex rounded-full px-3 py-1 text-xs font-semibold ${CATEGORY_BADGE_CLASS[notice.category]}`}
                            >
                              {notice.category_label}
                            </span>
                          </td>
                          <td className="px-5 py-4">
                            <button
                              type="button"
                              className="max-w-[420px] truncate text-left font-medium text-slate-900 hover:text-blue-700"
                              onClick={() => setDetailNotice(notice)}
                            >
                              {notice.title}
                            </button>
                          </td>
                          <td className="px-5 py-4">
                            <span
                              className={`inline-flex rounded-full px-3 py-1 text-xs font-semibold ${STATUS_BADGE_CLASS[notice.status]}`}
                            >
                              {STATUS_LABEL[notice.status]}
                            </span>
                          </td>
                          <td className="px-5 py-4 text-slate-500">
                            {formatDateTime(notice.created_at)}
                          </td>
                          <td className="px-5 py-4 text-slate-500">
                            {formatDateTime(notice.end_at)}
                          </td>
                          <td className="px-5 py-4">
                            <div className="flex gap-2">
                              <button
                                type="button"
                                onClick={() => openEditModal(notice)}
                                className="rounded-lg border border-slate-300 bg-white px-3 py-2 text-xs font-medium text-slate-700 transition hover:bg-slate-50"
                              >
                                수정
                              </button>
                              <button
                                type="button"
                                onClick={() => handleDelete(notice)}
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
                  {notices.map((notice) => (
                    <article
                      key={notice.id}
                      className="rounded-xl border border-slate-200 bg-slate-50 p-4"
                    >
                      <div className="flex items-start justify-between gap-3">
                        <button
                          type="button"
                          className="text-left text-base font-semibold text-slate-900"
                          onClick={() => setDetailNotice(notice)}
                        >
                          {notice.title}
                        </button>
                        <span
                          className={`inline-flex rounded-full px-3 py-1 text-xs font-semibold ${STATUS_BADGE_CLASS[notice.status]}`}
                        >
                          {STATUS_LABEL[notice.status]}
                        </span>
                      </div>

                      <div className="mt-3 flex flex-wrap gap-2">
                        <span
                          className={`inline-flex rounded-full px-3 py-1 text-xs font-semibold ${CATEGORY_BADGE_CLASS[notice.category]}`}
                        >
                          {notice.category_label}
                        </span>
                      </div>

                      <div className="mt-3 space-y-1 text-sm text-slate-500">
                        <div>생성: {formatDateTime(notice.created_at)}</div>
                        <div>종료: {formatDateTime(notice.end_at)}</div>
                      </div>

                      <div className="mt-4 flex gap-2">
                        <button
                          type="button"
                          onClick={() => openEditModal(notice)}
                          className="rounded-lg border border-slate-300 bg-white px-3 py-2 text-xs font-medium text-slate-700 transition hover:bg-slate-100"
                        >
                          수정
                        </button>
                        <button
                          type="button"
                          onClick={() => handleDelete(notice)}
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
          title={formMode === "create" ? "긴급공지 등록" : "긴급공지 수정"}
          onClose={() => setIsFormOpen(false)}
          wide
        >
          <form className="space-y-5" onSubmit={handleSubmit}>
            <div className="grid gap-4 md:grid-cols-2">
              <label className="block">
                <span className="mb-2 block text-sm font-medium text-slate-700">카테고리</span>
                <select
                  className="w-full rounded-lg border border-slate-300 bg-white px-4 py-3 text-sm text-slate-900 outline-none transition focus:border-blue-500 focus:ring-4 focus:ring-blue-100"
                  value={formState.category}
                  onChange={(event) =>
                    setFormState((current) => ({
                      ...current,
                      category: event.target.value as EmergencyNoticeCategory,
                    }))
                  }
                >
                  {CATEGORY_OPTIONS.map((option) => (
                    <option key={option.value} value={option.value}>
                      {option.label}
                    </option>
                  ))}
                </select>
              </label>

              <label className="block">
                <span className="mb-2 block text-sm font-medium text-slate-700">제목</span>
                <input
                  className="w-full rounded-lg border border-slate-300 bg-white px-4 py-3 text-sm text-slate-900 outline-none transition focus:border-blue-500 focus:ring-4 focus:ring-blue-100"
                  value={formState.title}
                  onChange={(event) =>
                    setFormState((current) => ({ ...current, title: event.target.value }))
                  }
                  required
                />
              </label>
            </div>

            <div className="grid gap-4 md:grid-cols-2">
              <label className="block">
                <span className="mb-2 block text-sm font-medium text-slate-700">생성 시각</span>
                <input
                  type="datetime-local"
                  className="w-full rounded-lg border border-slate-300 bg-white px-4 py-3 text-sm text-slate-900 outline-none transition focus:border-blue-500 focus:ring-4 focus:ring-blue-100"
                  value={formState.created_at}
                  onChange={(event) =>
                    setFormState((current) => ({ ...current, created_at: event.target.value }))
                  }
                  required
                />
              </label>

              <label className="block">
                <span className="mb-2 block text-sm font-medium text-slate-700">종료 시각</span>
                <input
                  type="datetime-local"
                  className="w-full rounded-lg border border-slate-300 bg-white px-4 py-3 text-sm text-slate-900 outline-none transition focus:border-blue-500 focus:ring-4 focus:ring-blue-100"
                  value={formState.end_at}
                  onChange={(event) =>
                    setFormState((current) => ({ ...current, end_at: event.target.value }))
                  }
                  required
                />
              </label>
            </div>

            <div>
              <div className="mb-2 text-sm font-medium text-slate-700">내용</div>
              <ToastEditor
                value={formState.content}
                onChange={(content) =>
                  setFormState((current) => ({
                    ...current,
                    content,
                  }))
                }
              />
            </div>

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
                {isSaving ? "저장 중..." : formMode === "create" ? "등록" : "저장"}
              </button>
            </div>
          </form>
        </AdminModal>
      ) : null}

      {detailNotice ? (
        <AdminModal title={detailNotice.title} onClose={() => setDetailNotice(null)} wide>
          <div className="mb-5 flex flex-wrap items-center gap-2 text-sm text-slate-600">
            <span
              className={`inline-flex rounded-full px-3 py-1 text-xs font-semibold ${CATEGORY_BADGE_CLASS[detailNotice.category]}`}
            >
              {detailNotice.category_label}
            </span>
            <span
              className={`inline-flex rounded-full px-3 py-1 text-xs font-semibold ${STATUS_BADGE_CLASS[detailNotice.status]}`}
            >
              {STATUS_LABEL[detailNotice.status]}
            </span>
            <span>생성 {formatDateTime(detailNotice.created_at)}</span>
            <span>종료 {formatDateTime(detailNotice.end_at)}</span>
          </div>
          <ToastViewer value={detailNotice.content} />
        </AdminModal>
      ) : null}
    </div>
  );
}
