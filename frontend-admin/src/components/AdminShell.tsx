import type { ReactNode } from "react";

/** 페이지 제목 헤더와 본문. 메뉴와 로그아웃은 AdminLayout이 맡는다. */
export function AdminShell({
  actions,
  children,
  description,
  summary,
  title,
}: {
  actions?: ReactNode;
  children: ReactNode;
  description: string;
  /** 헤더 아래에 붙는 요약 카드 같은 영역 */
  summary?: ReactNode;
  title: string;
}) {
  return (
    <div className="min-w-0">
      <header className="border-b border-slate-200 bg-white">
        <div className="flex flex-col gap-4 px-4 py-4 sm:px-6 lg:px-8">
          <div className="motion-enter flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
            <div>
              <h1 className="text-2xl font-semibold text-slate-900">{title}</h1>
              <p className="mt-1 text-sm text-slate-500">{description}</p>
            </div>
            {actions ? <div className="flex flex-wrap items-center gap-2">{actions}</div> : null}
          </div>
          {summary ? <div className="motion-enter motion-enter-delay-1">{summary}</div> : null}
        </div>
      </header>
      <main className="motion-enter motion-enter-delay-2 px-4 py-6 sm:px-6 lg:px-8">{children}</main>
    </div>
  );
}
