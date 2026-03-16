import { FormEvent, type ReactNode, useEffect, useState } from "react";
import { NavLink, useNavigate } from "react-router-dom";

import { useAuth } from "../auth/AuthProvider";
import { ToastEditor } from "../components/ToastEditor";
import { ToastViewer } from "../components/ToastViewer";
import { useDocumentTitle } from "../hooks/useDocumentTitle";
import {
  ApiError,
  createNotice,
  deleteNotice,
  getNotices,
  updateNotice,
} from "../lib/api";
import type { Notice, NoticePayload, NoticeType } from "../lib/types";
import { useToast } from "../toast/ToastProvider";

const NOTICE_TYPE_OPTIONS: Array<{ value: NoticeType; label: string }> = [
  { value: "App", label: "앱" },
  { value: "update", label: "업데이트" },
  { value: "shuttle", label: "셔틀버스" },
  { value: "citybus", label: "시내버스" },
];

const TYPE_BADGE_CLASS: Record<NoticeType, string> = {
  App: "bg-blue-50 text-blue-700 border border-blue-200",
  update: "bg-cyan-50 text-cyan-700 border border-cyan-200",
  shuttle: "bg-amber-50 text-amber-700 border border-amber-200",
  citybus: "bg-emerald-50 text-emerald-700 border border-emerald-200",
};

type FormMode = "create" | "edit";

const EMPTY_FORM: NoticePayload = {
  title: "",
  content: "",
  notice_type: "App",
  is_pinned: false,
};

function formatDate(value: string | null) {
  if (!value) {
    return "-";
  }

  return new Intl.DateTimeFormat("ko-KR", {
    year: "numeric",
    month: "2-digit",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
  }).format(new Date(value));
}

export function NoticesPage() {
  const navigate = useNavigate();
  const { logout, user } = useAuth();
  const { showToast } = useToast();
  useDocumentTitle("공지 관리");
  const [notices, setNotices] = useState<Notice[]>([]);
  const [isLoading, setIsLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [detailNotice, setDetailNotice] = useState<Notice | null>(null);
  const [formMode, setFormMode] = useState<FormMode>("create");
  const [editingNotice, setEditingNotice] = useState<Notice | null>(null);
  const [formState, setFormState] = useState<NoticePayload>(EMPTY_FORM);
  const [isFormOpen, setIsFormOpen] = useState(false);
  const [isSaving, setIsSaving] = useState(false);
  const [formError, setFormError] = useState<string | null>(null);

  const pinnedCount = notices.filter((notice) => notice.is_pinned).length;

  async function handleUnauthorized() {
    await logout();
    navigate("/login", { replace: true, state: { from: "/notices" } });
  }

  async function loadNotices() {
    setError(null);
    setIsLoading(true);

    try {
      const nextNotices = await getNotices();
      setNotices(nextNotices);
    } catch (loadError) {
      if (loadError instanceof ApiError) {
        if (loadError.status === 401) {
          await handleUnauthorized();
          return;
        }
        setError(loadError.message);
      } else {
        setError("공지 목록을 불러오지 못했습니다.");
      }
    } finally {
      setIsLoading(false);
    }
  }

  useEffect(() => {
    void loadNotices();
  }, []);

  function openCreateModal() {
    setFormMode("create");
    setEditingNotice(null);
    setFormState(EMPTY_FORM);
    setFormError(null);
    setIsFormOpen(true);
  }

  function openEditModal(notice: Notice) {
    setFormMode("edit");
    setEditingNotice(notice);
    setFormState({
      title: notice.title,
      content: notice.content,
      notice_type: notice.notice_type,
      is_pinned: notice.is_pinned,
    });
    setFormError(null);
    setIsFormOpen(true);
  }

  async function handleDelete(notice: Notice) {
    if (!window.confirm(`"${notice.title}" 공지를 삭제하시겠습니까?`)) {
      return;
    }

    try {
      await deleteNotice(notice.id);
      showToast("공지를 삭제했습니다.", "success");
      await loadNotices();
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
        showToast("공지 삭제 중 오류가 발생했습니다.", "error");
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
    setIsSaving(true);

    try {
      if (formMode === "create") {
        await createNotice(formState);
        showToast("공지를 등록했습니다.", "success");
      } else if (editingNotice) {
        await updateNotice(editingNotice.id, formState);
        showToast("공지를 수정했습니다.", "success");
      }

      setIsFormOpen(false);
      await loadNotices();
    } catch (submitError) {
      if (submitError instanceof ApiError) {
        if (submitError.status === 401) {
          await handleUnauthorized();
          return;
        }
        setFormError(submitError.message);
      } else {
        setFormError("공지 저장 중 오류가 발생했습니다.");
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
        <div className="min-w-0">
          <header className="border-b border-slate-200 bg-white">
            <div className="flex flex-col gap-4 px-4 py-4 sm:px-6 lg:px-8">
              <div className="motion-enter flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
                <div>
                  <h1 className="text-2xl font-semibold text-slate-900">공지 관리</h1>
                  <p className="mt-1 text-sm text-slate-500">공지 등록, 수정, 삭제</p>
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
                    새 공지
                  </button>
                </div>
              </div>

              <div className="motion-enter motion-enter-delay-1 grid gap-3 sm:grid-cols-2 xl:max-w-xl">
                <SummaryCard label="전체 공지" value={String(notices.length)} />
                <SummaryCard label="상단 고정" value={String(pinnedCount)} />
              </div>
            </div>
          </header>

          <main className="motion-enter motion-enter-delay-2 px-4 py-6 sm:px-6 lg:px-8">
            {error ? (
              <div className="mb-4 rounded-lg border border-rose-200 bg-rose-50 px-4 py-3 text-sm text-rose-700">
                {error}
              </div>
            ) : null}

            <section className="overflow-hidden rounded-2xl border border-slate-200 bg-white shadow-sm">
              <div className="border-b border-slate-200 px-5 py-4">
                <div className="text-base font-semibold text-slate-900">공지 목록</div>
              </div>

              {isLoading ? (
                <div className="px-5 py-10 text-sm text-slate-500">공지 목록을 불러오는 중입니다.</div>
              ) : notices.length === 0 ? (
                <div className="px-5 py-10 text-sm text-slate-500">등록된 공지가 없습니다.</div>
              ) : (
                <>
                  <div className="hidden overflow-x-auto lg:block">
                    <table className="min-w-full text-left text-sm">
                      <thead className="bg-slate-50 text-slate-600">
                        <tr>
                          <th className="px-5 py-3 font-medium">제목</th>
                          <th className="px-5 py-3 font-medium">유형</th>
                          <th className="px-5 py-3 font-medium">상태</th>
                          <th className="px-5 py-3 font-medium">작성일</th>
                          <th className="px-5 py-3 font-medium">관리</th>
                        </tr>
                      </thead>
                      <tbody>
                        {notices.map((notice) => (
                          <tr key={notice.id} className="border-t border-slate-200">
                            <td className="px-5 py-4">
                              <button
                                type="button"
                                className="max-w-[460px] truncate text-left font-medium text-slate-900 hover:text-blue-700"
                                onClick={() => setDetailNotice(notice)}
                              >
                                {notice.title}
                              </button>
                            </td>
                            <td className="px-5 py-4">
                              <span
                                className={`inline-flex rounded-full px-3 py-1 text-xs font-semibold ${TYPE_BADGE_CLASS[notice.notice_type]}`}
                              >
                                {NOTICE_TYPE_OPTIONS.find((item) => item.value === notice.notice_type)?.label}
                              </span>
                            </td>
                            <td className="px-5 py-4">
                              <span className="inline-flex rounded-full border border-slate-200 bg-slate-50 px-3 py-1 text-xs font-medium text-slate-700">
                                {notice.is_pinned ? "상단 고정" : "일반"}
                              </span>
                            </td>
                            <td className="px-5 py-4 text-slate-500">
                              {formatDate(notice.created_at)}
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

                  <div className="grid gap-3 p-4 lg:hidden">
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
                          <span className="shrink-0 text-xs text-slate-500">
                            {formatDate(notice.created_at)}
                          </span>
                        </div>

                        <div className="mt-3 flex flex-wrap gap-2">
                          <span
                            className={`inline-flex rounded-full px-3 py-1 text-xs font-semibold ${TYPE_BADGE_CLASS[notice.notice_type]}`}
                          >
                            {NOTICE_TYPE_OPTIONS.find((item) => item.value === notice.notice_type)?.label}
                          </span>
                          <span className="inline-flex rounded-full border border-slate-200 bg-white px-3 py-1 text-xs font-medium text-slate-700">
                            {notice.is_pinned ? "상단 고정" : "일반"}
                          </span>
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
            </section>
          </main>
        </div>
      </div>

      {isFormOpen ? (
        <Modal
          title={formMode === "create" ? "공지 작성" : "공지 수정"}
          onClose={() => setIsFormOpen(false)}
        >
          <form className="space-y-5" onSubmit={handleSubmit}>
            <label className="block">
              <span className="mb-2 block text-sm font-medium text-slate-700">제목</span>
              <input
                className="w-full rounded-lg border border-slate-300 bg-white px-4 py-3 text-sm text-slate-900 outline-none transition focus:border-blue-500 focus:ring-4 focus:ring-blue-100"
                value={formState.title}
                onChange={(event) =>
                  setFormState((current) => ({ ...current, title: event.target.value }))
                }
                placeholder="공지 제목을 입력하세요."
                required
              />
            </label>

            <div className="grid gap-4 md:grid-cols-[1fr_auto] md:items-end">
              <label className="block">
                <span className="mb-2 block text-sm font-medium text-slate-700">유형</span>
                <select
                  className="w-full rounded-lg border border-slate-300 bg-white px-4 py-3 text-sm text-slate-900 outline-none transition focus:border-blue-500 focus:ring-4 focus:ring-blue-100"
                  value={formState.notice_type}
                  onChange={(event) =>
                    setFormState((current) => ({
                      ...current,
                      notice_type: event.target.value as NoticeType,
                    }))
                  }
                >
                  {NOTICE_TYPE_OPTIONS.map((option) => (
                    <option key={option.value} value={option.value}>
                      {option.label}
                    </option>
                  ))}
                </select>
              </label>

              <label className="inline-flex items-center gap-3 rounded-lg border border-slate-300 bg-slate-50 px-4 py-3 text-sm text-slate-700">
                <input
                  type="checkbox"
                  className="h-4 w-4 rounded border-slate-300 text-blue-600"
                  checked={formState.is_pinned}
                  onChange={(event) =>
                    setFormState((current) => ({
                      ...current,
                      is_pinned: event.target.checked,
                    }))
                  }
                />
                상단 고정
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
                {isSaving ? "저장 중..." : formMode === "create" ? "작성" : "저장"}
              </button>
            </div>
          </form>
        </Modal>
      ) : null}

      {detailNotice ? (
        <Modal title={detailNotice.title} onClose={() => setDetailNotice(null)} wide>
          <div className="mb-5 flex flex-wrap items-center gap-2 text-sm text-slate-600">
            <span
              className={`inline-flex rounded-full px-3 py-1 text-xs font-semibold ${TYPE_BADGE_CLASS[detailNotice.notice_type]}`}
            >
              {NOTICE_TYPE_OPTIONS.find((item) => item.value === detailNotice.notice_type)?.label}
            </span>
            <span className="inline-flex rounded-full border border-slate-200 bg-slate-50 px-3 py-1 text-xs font-medium text-slate-700">
              {detailNotice.is_pinned ? "상단 고정" : "일반"}
            </span>
            <span>{formatDate(detailNotice.created_at)}</span>
          </div>
          <ToastViewer value={detailNotice.content} />
        </Modal>
      ) : null}
    </div>
  );
}

function SummaryCard({ label, value }: { label: string; value: string }) {
  return (
    <div className="panel-motion rounded-xl border border-slate-200 bg-slate-50 px-4 py-4">
      <div className="text-xs font-medium text-slate-500">{label}</div>
      <div className="mt-2 text-2xl font-semibold text-slate-900">{value}</div>
    </div>
  );
}

function Modal({
  children,
  onClose,
  title,
  wide = false,
}: {
  children: ReactNode;
  onClose: () => void;
  title: string;
  wide?: boolean;
}) {
  return (
    <div
      className="modal-backdrop-motion fixed inset-0 z-50 flex items-center justify-center bg-slate-950/40 p-4"
      onClick={onClose}
    >
      <div
        className={`modal-shell-motion max-h-[90vh] w-full overflow-y-auto rounded-2xl border border-slate-200 bg-white p-6 shadow-xl ${
          wide ? "max-w-5xl" : "max-w-4xl"
        }`}
        onClick={(event) => event.stopPropagation()}
      >
        <div className="mb-5 flex items-center justify-between gap-4">
          <h2 className="text-xl font-semibold text-slate-900">{title}</h2>
          <button
            type="button"
            onClick={onClose}
            className="rounded-lg border border-slate-300 bg-white px-3 py-2 text-sm text-slate-700 transition hover:bg-slate-50"
          >
            닫기
          </button>
        </div>
        {children}
      </div>
    </div>
  );
}
