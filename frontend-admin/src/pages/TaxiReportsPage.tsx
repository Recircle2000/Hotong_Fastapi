import { useEffect, useState } from "react";

import { AdminModal } from "../components/AdminModal";
import { AdminShell } from "../components/AdminShell";
import { useDocumentTitle } from "../hooks/useDocumentTitle";
import {
  ApiError,
  createAdminTaxiSanction,
  getAdminTaxiReport,
  getAdminTaxiReports,
  updateAdminTaxiReport,
} from "../lib/api";
import type {
  AdminTaxiReport,
  AdminTaxiReportDetail,
  TaxiReportReason,
  TaxiReportStatus,
  TaxiSanctionLevel,
} from "../lib/types";
import { useToast } from "../toast/ToastProvider";
import { SanctionSection, sanctionLevelLabels } from "./taxiSanctionParts";

const reasonLabels: Record<TaxiReportReason, string> = {
  no_show: "노쇼",
  abuse: "욕설·비매너",
  payment: "정산 문제",
  other: "기타",
};

const reasonStyles: Record<TaxiReportReason, string> = {
  no_show: "bg-amber-50 text-amber-800 border-amber-200",
  abuse: "bg-rose-50 text-rose-700 border-rose-200",
  payment: "bg-violet-50 text-violet-700 border-violet-200",
  other: "bg-slate-50 text-slate-700 border-slate-200",
};

const statusTabs: [TaxiReportStatus, string][] = [
  ["pending", "대기"],
  ["resolved", "처리"],
  ["dismissed", "기각"],
];

const statusLabels: Record<TaxiReportStatus, string> = {
  pending: "대기",
  resolved: "처리 완료",
  dismissed: "기각",
};

// 서로 다른 신고자가 이만큼 모이면 반복 신고로 보고 강조한다.
const REPEATED_REPORTER_THRESHOLD = 3;

function formatDateTime(value: string | null) {
  if (!value) return "-";
  return new Intl.DateTimeFormat("ko-KR", { dateStyle: "short", timeStyle: "short" }).format(new Date(value));
}

function formatTime(value: string) {
  return new Intl.DateTimeFormat("ko-KR", { month: "numeric", day: "numeric", hour: "2-digit", minute: "2-digit" }).format(new Date(value));
}

function route(report: AdminTaxiReport) {
  if (!report.departure_location_name) return "삭제된 택시팟";
  return `${report.departure_location_name} → ${report.destination_location_name}`;
}

function ReasonBadge({ reason }: { reason: TaxiReportReason }) {
  return (
    <span className={`inline-flex whitespace-nowrap rounded-full border px-2.5 py-0.5 text-xs font-semibold ${reasonStyles[reason]}`}>
      {reasonLabels[reason] ?? reason}
    </span>
  );
}

function TargetCount({ report }: { report: AdminTaxiReport }) {
  const { total_reports, distinct_reporters } = report.target_stats;
  const repeated = distinct_reporters >= REPEATED_REPORTER_THRESHOLD;
  return (
    <span className={repeated ? "font-semibold text-rose-700" : "text-slate-600"}>
      {total_reports}건 · 신고자 {distinct_reporters}명
    </span>
  );
}

export function TaxiReportsPage() {
  useDocumentTitle("택시팟 신고");
  const { showToast } = useToast();
  const [status, setStatus] = useState<TaxiReportStatus>("pending");
  const [target, setTarget] = useState<string | null>(null);
  const [items, setItems] = useState<AdminTaxiReport[]>([]);
  const [nextCursor, setNextCursor] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [detail, setDetail] = useState<AdminTaxiReportDetail | null>(null);
  const [note, setNote] = useState("");
  const [saving, setSaving] = useState(false);

  async function load(cursor?: string) {
    setLoading(true);
    setError(null);
    try {
      // 같은 대상의 신고를 모아 볼 때는 상태와 관계없이 전부 보여준다.
      const result = await getAdminTaxiReports({
        status: target ? undefined : status,
        target: target ?? undefined,
        cursor,
      });
      setItems((current) => (cursor ? [...current, ...result.items] : result.items));
      setNextCursor(result.next_cursor);
    } catch (reason) {
      setError(reason instanceof ApiError ? reason.message : "신고 목록을 불러오지 못했습니다.");
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => { void load(); }, [status, target]);

  async function open(id: number) {
    try {
      const result = await getAdminTaxiReport(id);
      setDetail(result);
      setNote(result.admin_note ?? "");
    } catch (cause) {
      showToast(cause instanceof ApiError ? cause.message : "신고 내용을 불러오지 못했습니다.", "error");
    }
  }

  async function review(nextStatus: TaxiReportStatus) {
    if (!detail) return;
    const messages: Record<TaxiReportStatus, string> = {
      resolved: "이 신고를 처리 완료로 바꿀까요?\n처리 후 1년이 지나면 저장된 채팅 증거가 삭제됩니다.",
      dismissed: "이 신고를 기각할까요?\n기각 후 1년이 지나면 저장된 채팅 증거가 삭제됩니다.",
      pending: "이 신고를 다시 대기 상태로 되돌릴까요?",
    };
    if (!window.confirm(messages[nextStatus])) return;
    setSaving(true);
    try {
      const updated = await updateAdminTaxiReport(detail.id, {
        status: nextStatus,
        admin_note: note.trim() || null,
      });
      setDetail(updated);
      showToast(`신고를 ${statusLabels[nextStatus]} 상태로 바꿨습니다.`, "success");
      await load();
    } catch (cause) {
      showToast(cause instanceof ApiError ? cause.message : "신고 상태를 바꾸지 못했습니다.", "error");
    } finally {
      setSaving(false);
    }
  }

  async function sanction(payload: {
    level: TaxiSanctionLevel;
    reason: string;
    admin_note: string | null;
    resolve_pending_reports: boolean;
  }) {
    if (!detail) return;
    const label = sanctionLevelLabels[payload.level];
    const message = payload.level === "permanent"
      ? `사용자 ${detail.target_key}에게 영구 정지를 부과할까요?\n택시팟을 다시 만들거나 참여할 수 없게 됩니다.`
      : `사용자 ${detail.target_key}에게 ${label}를 부과할까요?`;
    if (!window.confirm(message)) return;
    setSaving(true);
    try {
      const updated = await createAdminTaxiSanction(detail.id, payload);
      setDetail(updated);
      showToast(`${label}를 부과했습니다.`, "success");
      await load();
    } catch (cause) {
      showToast(cause instanceof ApiError ? cause.message : "제재를 부과하지 못했습니다.", "error");
    } finally {
      setSaving(false);
    }
  }

  function showTarget(key: string) {
    setDetail(null);
    setTarget(key);
  }

  return (
    <AdminShell
      title="택시팟 신고"
      description="신고 대상은 익명 ID로만 표시합니다. 같은 ID는 같은 사용자입니다."
    >
      <div className="mb-4 flex flex-wrap items-center gap-3">
        {target ? (
          <div className="flex items-center gap-2 rounded-lg border border-blue-200 bg-blue-50 px-3 py-2 text-sm text-blue-800">
            <span>사용자 <span className="font-mono font-semibold">{target}</span>의 신고 전체</span>
            <button type="button" onClick={() => setTarget(null)} className="rounded border border-blue-200 bg-white px-2 py-0.5 text-xs">해제</button>
          </div>
        ) : (
          <div className="flex rounded-lg border border-slate-300 bg-white p-1">
            {statusTabs.map(([value, label]) => (
              <button
                key={value}
                type="button"
                onClick={() => setStatus(value)}
                className={`rounded-md px-4 py-1.5 text-sm font-medium transition ${status === value ? "bg-slate-900 text-white" : "text-slate-600 hover:bg-slate-50"}`}
              >
                {label}
              </button>
            ))}
          </div>
        )}
        <button type="button" onClick={() => void load()} className="rounded-lg border border-slate-300 bg-white px-3 py-2 text-sm">새로고침</button>
      </div>
      {error ? <div className="mb-4 rounded-lg border border-rose-200 bg-rose-50 p-4 text-sm text-rose-700">{error}</div> : null}
      <section className="overflow-hidden rounded-2xl border border-slate-200 bg-white shadow-sm">
        {loading && items.length === 0 ? <div className="p-8 text-sm text-slate-500">불러오는 중입니다.</div> : items.length === 0 ? <div className="p-8 text-sm text-slate-500">해당하는 신고가 없습니다.</div> : (
          <div className="overflow-x-auto">
            <table className="min-w-full text-left text-sm">
              <thead className="bg-slate-50 text-slate-600">
                <tr>
                  <th className="px-5 py-3">신고일</th>
                  <th className="px-5 py-3">사유</th>
                  <th className="px-5 py-3">대상</th>
                  <th className="px-5 py-3">누적</th>
                  <th className="px-5 py-3">택시팟</th>
                  <th className="px-5 py-3">상태</th>
                </tr>
              </thead>
              <tbody>
                {items.map((item) => (
                  <tr key={item.id} onClick={() => void open(item.id)} className="cursor-pointer border-t border-slate-200 hover:bg-slate-50">
                    <td className="whitespace-nowrap px-5 py-4">{formatDateTime(item.created_at)}</td>
                    <td className="px-5 py-4"><ReasonBadge reason={item.reason} /></td>
                    <td className="whitespace-nowrap px-5 py-4"><span className="font-mono font-semibold">{item.target_key}</span> <span className="text-slate-500">({item.target_label})</span></td>
                    <td className="whitespace-nowrap px-5 py-4"><TargetCount report={item} /></td>
                    <td className="whitespace-nowrap px-5 py-4">{route(item)}<div className="text-xs text-slate-500">{formatDateTime(item.departure_at)} 출발</div></td>
                    <td className="px-5 py-4">{statusLabels[item.status]}</td>
                  </tr>
                ))}
              </tbody>
            </table>
            {nextCursor ? (
              <div className="border-t border-slate-200 p-4 text-center">
                <button type="button" disabled={loading} onClick={() => void load(nextCursor)} className="rounded-lg border border-slate-300 bg-white px-4 py-2 text-sm disabled:opacity-50">더 보기</button>
              </div>
            ) : null}
          </div>
        )}
      </section>

      {detail ? (
        <AdminModal title={`신고 #${detail.id}`} onClose={() => setDetail(null)} wide>
          <div className="grid gap-6 lg:grid-cols-[1fr_1.2fr]">
            <div className="space-y-5">
              <dl className="grid grid-cols-[88px_1fr] gap-y-2 text-sm">
                <dt className="text-slate-500">사유</dt><dd><ReasonBadge reason={detail.reason} /></dd>
                <dt className="text-slate-500">대상</dt>
                <dd>
                  <span className="font-mono font-semibold">{detail.target_key}</span> ({detail.target_label}) · <TargetCount report={detail} />
                </dd>
                <dt className="text-slate-500">신고자</dt><dd className="font-mono">{detail.reporter_key}</dd>
                <dt className="text-slate-500">택시팟</dt><dd>{route(detail)}<div className="text-xs text-slate-500">{formatDateTime(detail.departure_at)} 출발 · {detail.departure_summary ?? "-"}</div></dd>
                <dt className="text-slate-500">신고일</dt><dd>{formatDateTime(detail.created_at)}</dd>
                <dt className="text-slate-500">상태</dt><dd>{statusLabels[detail.status]}{detail.reviewed_at ? ` · ${formatDateTime(detail.reviewed_at)}` : ""}</dd>
              </dl>
              <div>
                <h3 className="mb-2 text-sm font-semibold text-slate-900">신고 내용</h3>
                <p className="whitespace-pre-wrap rounded-lg bg-slate-50 p-3 text-sm text-slate-700">{detail.evidence_purged ? "보관 기간이 지나 삭제되었습니다." : detail.detail ?? "작성한 내용이 없습니다."}</p>
              </div>
              <div>
                <div className="mb-2 flex items-center justify-between">
                  <h3 className="text-sm font-semibold text-slate-900">같은 대상의 다른 신고 {detail.other_reports.length}건</h3>
                  {detail.other_reports.length > 0 ? <button type="button" onClick={() => showTarget(detail.target_key)} className="text-xs text-blue-700">목록에서 모아 보기</button> : null}
                </div>
                <ul className="space-y-1.5 text-sm">
                  {detail.other_reports.map((other) => (
                    <li key={other.id}>
                      <button type="button" onClick={() => void open(other.id)} className="flex w-full items-center gap-2 rounded-lg border border-slate-200 px-3 py-2 text-left hover:bg-slate-50">
                        <ReasonBadge reason={other.reason} />
                        <span className="flex-1 truncate">{route(other)}</span>
                        <span className="text-xs text-slate-500">{statusLabels[other.status]}</span>
                      </button>
                    </li>
                  ))}
                </ul>
              </div>
              <SanctionSection key={detail.id} detail={detail} saving={saving} onSubmit={(payload) => void sanction(payload)} />
              <div>
                <label htmlFor="report-note" className="mb-2 block text-sm font-semibold text-slate-900">관리자 메모</label>
                <textarea id="report-note" value={note} onChange={(event) => setNote(event.target.value)} maxLength={1000} rows={3} placeholder="검토 내용이나 조치 계획을 남겨두세요." className="w-full rounded-lg border border-slate-300 px-3 py-2 text-sm" />
                <div className="mt-3 flex flex-wrap gap-2">
                  {detail.status !== "resolved" ? <button type="button" disabled={saving} onClick={() => void review("resolved")} className="rounded-lg bg-blue-600 px-4 py-2 text-sm font-semibold text-white disabled:bg-blue-300">처리 완료</button> : null}
                  {detail.status !== "dismissed" ? <button type="button" disabled={saving} onClick={() => void review("dismissed")} className="rounded-lg border border-slate-300 bg-white px-4 py-2 text-sm font-semibold text-slate-700 disabled:opacity-50">기각</button> : null}
                  {detail.status !== "pending" ? <button type="button" disabled={saving} onClick={() => void review("pending")} className="rounded-lg border border-slate-300 bg-white px-4 py-2 text-sm text-slate-600 disabled:opacity-50">대기로 되돌리기</button> : null}
                </div>
              </div>
            </div>
            <div>
              <h3 className="mb-2 text-sm font-semibold text-slate-900">신고 시점 채팅</h3>
              <div className="max-h-[60vh] space-y-2 overflow-y-auto rounded-xl bg-slate-50 p-3">
                {detail.evidence_purged ? <p className="p-4 text-center text-sm text-slate-500">보관 기간이 지나 채팅 증거가 삭제되었습니다.</p> : detail.messages.length === 0 ? <p className="p-4 text-center text-sm text-slate-500">신고 당시 남아 있는 채팅이 없었습니다.</p> : detail.messages.map((message) => (
                  message.type === "system" ? (
                    <p key={message.id} className="py-1 text-center text-xs text-slate-500">{message.content}</p>
                  ) : (
                    <div key={message.id} className={`rounded-lg border px-3 py-2 text-sm ${message.id === detail.reported_message_id ? "border-rose-400 bg-rose-50 ring-2 ring-rose-200" : message.is_target ? "border-amber-200 bg-amber-50" : "border-slate-200 bg-white"}`}>
                      <div className="mb-0.5 flex items-center gap-2 text-xs">
                        <span className={`font-semibold ${message.is_target ? "text-amber-800" : "text-slate-700"}`}>{message.label ?? "참여자"}</span>
                        <span className="text-slate-400">{formatTime(message.created_at)}</span>
                        {message.id === detail.reported_message_id ? <span className="font-semibold text-rose-700">신고된 메시지</span> : null}
                      </div>
                      <p className="whitespace-pre-wrap text-slate-800">{message.content}</p>
                    </div>
                  )
                ))}
              </div>
              <p className="mt-2 text-xs text-slate-500">노란색은 신고 대상이 보낸 메시지입니다.</p>
            </div>
          </div>
        </AdminModal>
      ) : null}
    </AdminShell>
  );
}
