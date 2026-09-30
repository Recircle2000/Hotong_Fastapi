import { useState } from "react";

import type { AdminTaxiReportDetail, AdminTaxiSanction, TaxiSanctionLevel } from "../lib/types";

export const sanctionLevels: TaxiSanctionLevel[] = ["warning", "suspend_3d", "suspend_7d", "permanent"];

export const sanctionLevelLabels: Record<TaxiSanctionLevel, string> = {
  warning: "경고",
  suspend_3d: "3일 정지",
  suspend_7d: "7일 정지",
  permanent: "영구 정지",
};

const levelStyles: Record<TaxiSanctionLevel, string> = {
  warning: "bg-amber-50 text-amber-800 border-amber-200",
  suspend_3d: "bg-orange-50 text-orange-800 border-orange-200",
  suspend_7d: "bg-rose-50 text-rose-700 border-rose-200",
  permanent: "bg-slate-900 text-white border-slate-900",
};

function formatDateTime(value: string) {
  return new Intl.DateTimeFormat("ko-KR", { dateStyle: "short", timeStyle: "short" }).format(new Date(value));
}

export function SanctionLevelBadge({ level }: { level: TaxiSanctionLevel }) {
  return (
    <span className={`inline-flex whitespace-nowrap rounded-full border px-2.5 py-0.5 text-xs font-semibold ${levelStyles[level]}`}>
      {sanctionLevelLabels[level]}
    </span>
  );
}

export function sanctionPeriod(sanction: AdminTaxiSanction) {
  if (sanction.level === "warning") return `${formatDateTime(sanction.starts_at)} 경고`;
  if (!sanction.ends_at) return `${formatDateTime(sanction.starts_at)}부터 영구`;
  return `${formatDateTime(sanction.starts_at)} ~ ${formatDateTime(sanction.ends_at)}`;
}

export function sanctionState(sanction: AdminTaxiSanction) {
  if (sanction.revoked_at) return { label: "철회됨", className: "text-slate-500" };
  if (sanction.is_active) return { label: "적용 중", className: "font-semibold text-rose-700" };
  if (sanction.level === "warning") return { label: sanction.acknowledged_at ? "확인함" : "미확인", className: "text-slate-600" };
  return { label: "만료", className: "text-slate-500" };
}

/** 신고 상세에서 대상에게 제재를 부과하는 영역. */
export function SanctionSection({
  detail,
  saving,
  onSubmit,
}: {
  detail: AdminTaxiReportDetail;
  saving: boolean;
  onSubmit: (payload: {
    level: TaxiSanctionLevel;
    reason: string;
    admin_note: string | null;
    resolve_pending_reports: boolean;
  }) => void;
}) {
  const [level, setLevel] = useState<TaxiSanctionLevel>(detail.suggested_level);
  const [reason, setReason] = useState("");
  const [note, setNote] = useState("");
  const [resolvePending, setResolvePending] = useState(true);
  const pendingOthers = detail.other_reports.filter((report) => report.status === "pending").length;

  return (
    <div className="rounded-xl border border-slate-200 p-4">
      <h3 className="text-sm font-semibold text-slate-900">제재</h3>
      {detail.target_sanctions.length > 0 ? (
        <ul className="mt-3 space-y-1.5 text-sm">
          {detail.target_sanctions.map((sanction) => {
            const state = sanctionState(sanction);
            return (
              <li key={sanction.id} className="flex flex-wrap items-center gap-2">
                <SanctionLevelBadge level={sanction.level} />
                <span className="text-slate-600">{sanctionPeriod(sanction)}</span>
                <span className={`text-xs ${state.className}`}>{state.label}</span>
              </li>
            );
          })}
        </ul>
      ) : (
        <p className="mt-2 text-sm text-slate-500">제재 이력이 없습니다.</p>
      )}
      {detail.sanction_id ? (
        <p className="mt-3 rounded-lg bg-slate-50 p-3 text-sm text-slate-600">이 신고로 이미 제재를 부과했습니다.</p>
      ) : (
        <form
          className="mt-4 space-y-3"
          onSubmit={(event) => {
            event.preventDefault();
            onSubmit({ level, reason: reason.trim(), admin_note: note.trim() || null, resolve_pending_reports: resolvePending });
          }}
        >
          <div className="flex flex-wrap gap-2">
            {sanctionLevels.map((value) => (
              <label key={value} className={`cursor-pointer rounded-lg border px-3 py-1.5 text-sm ${level === value ? "border-slate-900 bg-slate-900 text-white" : "border-slate-300 bg-white text-slate-700"}`}>
                <input type="radio" name="sanction-level" value={value} checked={level === value} onChange={() => setLevel(value)} className="sr-only" />
                {sanctionLevelLabels[value]}{value === detail.suggested_level ? " · 추천" : ""}
              </label>
            ))}
          </div>
          <div>
            <label htmlFor="sanction-reason" className="mb-1 block text-xs font-medium text-slate-600">사용자에게 보이는 사유</label>
            <input id="sanction-reason" value={reason} onChange={(event) => setReason(event.target.value)} maxLength={300} required placeholder="예: 약속 장소에 나타나지 않았다는 신고가 확인되었습니다." className="w-full rounded-lg border border-slate-300 px-3 py-2 text-sm" />
          </div>
          <div>
            <label htmlFor="sanction-note" className="mb-1 block text-xs font-medium text-slate-600">내부 메모 (선택)</label>
            <input id="sanction-note" value={note} onChange={(event) => setNote(event.target.value)} maxLength={1000} className="w-full rounded-lg border border-slate-300 px-3 py-2 text-sm" />
          </div>
          {pendingOthers > 0 ? (
            <label className="flex items-center gap-2 text-sm text-slate-700">
              <input type="checkbox" checked={resolvePending} onChange={(event) => setResolvePending(event.target.checked)} />
              같은 대상의 대기 신고 {pendingOthers}건도 처리 완료
            </label>
          ) : null}
          <button type="submit" disabled={saving || !reason.trim()} className="rounded-lg bg-rose-600 px-4 py-2 text-sm font-semibold text-white disabled:bg-rose-300">
            {sanctionLevelLabels[level]} 부과
          </button>
        </form>
      )}
    </div>
  );
}
