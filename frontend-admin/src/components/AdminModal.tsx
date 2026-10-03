import type { ReactNode } from "react";
import { createPortal } from "react-dom";

export function AdminModal({
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
  // 페이지 본문(main)은 등장 애니메이션의 transform이 남아 fixed 기준이 되므로 body에 띄운다.
  return createPortal(
    <div
      className="modal-backdrop-motion fixed inset-0 z-50 flex items-center justify-center bg-slate-950/40 p-4"
      onClick={onClose}
    >
      <div
        className={`modal-shell-motion max-h-[90vh] w-full overflow-y-auto rounded-2xl border border-slate-200 bg-white p-6 shadow-xl ${
          wide ? "max-w-5xl" : "max-w-3xl"
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
    </div>,
    document.body,
  );
}
