import { useEffect, useState } from "react";

import { AdminShell } from "../components/AdminShell";
import { useDocumentTitle } from "../hooks/useDocumentTitle";
import { ApiError, cancelAdminTaxiParty, getAdminTaxiParties } from "../lib/api";
import type { AdminTaxiParty } from "../lib/types";
import { useToast } from "../toast/ToastProvider";

const statusLabels: Record<string, string> = {
  recruiting: "모집 중", full: "정원 마감", closed: "모집 마감",
  ended: "모집 종료", cancelled: "취소",
};

export function TaxiPartiesPage() {
  useDocumentTitle("택시팟 현황");
  const { showToast } = useToast();
  const [items, setItems] = useState<AdminTaxiParty[]>([]);
  const [statusFilter, setStatusFilter] = useState("");
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  async function load() {
    setLoading(true);
    setError(null);
    try {
      const result = await getAdminTaxiParties({ status_filter: statusFilter || undefined });
      setItems(result.items);
    } catch (reason) {
      setError(reason instanceof ApiError ? reason.message : "택시팟 현황을 불러오지 못했습니다.");
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => { void load(); }, [statusFilter]);

  async function cancel(item: AdminTaxiParty) {
    const reason = window.prompt("참여자에게 안내할 강제 취소 사유를 입력해주세요.");
    if (!reason?.trim()) return;
    try {
      await cancelAdminTaxiParty(item.id, reason.trim());
      showToast("택시팟을 취소했습니다.", "success");
      await load();
    } catch (cause) {
      showToast(cause instanceof ApiError ? cause.message : "택시팟을 취소하지 못했습니다.", "error");
    }
  }

  return (
    <AdminShell title="택시팟 현황" description="채팅 내용과 사용자 개인정보 없이 운영 상태만 확인합니다.">
      <div className="mb-4 flex items-center gap-3">
        <label className="text-sm font-medium">상태</label>
        <select value={statusFilter} onChange={(e) => setStatusFilter(e.target.value)} className="rounded-lg border border-slate-300 bg-white px-3 py-2 text-sm">
          <option value="">전체</option>{Object.entries(statusLabels).map(([value, label]) => <option key={value} value={value}>{label}</option>)}
        </select>
        <button type="button" onClick={() => void load()} className="rounded-lg border border-slate-300 bg-white px-3 py-2 text-sm">새로고침</button>
      </div>
      {error ? <div className="mb-4 rounded-lg border border-rose-200 bg-rose-50 p-4 text-sm text-rose-700">{error}</div> : null}
      <section className="overflow-hidden rounded-2xl border border-slate-200 bg-white shadow-sm">
        {loading ? <div className="p-8 text-sm text-slate-500">불러오는 중입니다.</div> : items.length === 0 ? <div className="p-8 text-sm text-slate-500">조건에 맞는 택시팟이 없습니다.</div> : (
          <div className="overflow-x-auto"><table className="min-w-full text-left text-sm"><thead className="bg-slate-50 text-slate-600"><tr><th className="px-5 py-3">출발 시각</th><th className="px-5 py-3">경로</th><th className="px-5 py-3">출발 안내</th><th className="px-5 py-3">인원</th><th className="px-5 py-3">상태</th><th className="px-5 py-3">관리</th></tr></thead>
            <tbody>{items.map((item) => <tr key={item.id} className="border-t border-slate-200"><td className="whitespace-nowrap px-5 py-4">{new Intl.DateTimeFormat("ko-KR", { dateStyle: "short", timeStyle: "short" }).format(new Date(item.departure_at))}</td><td className="whitespace-nowrap px-5 py-4 font-medium">{item.departure_location_name} → {item.destination_location_name}</td><td className="px-5 py-4">{item.departure_summary}</td><td className="px-5 py-4">{item.current_members}/{item.max_members}</td><td className="px-5 py-4">{statusLabels[item.status] ?? item.status}</td><td className="px-5 py-4">{!["cancelled", "ended"].includes(item.status) ? <button onClick={() => void cancel(item)} className="rounded border border-rose-200 px-3 py-1 text-rose-700">강제 취소</button> : "-"}</td></tr>)}</tbody>
          </table></div>
        )}
      </section>
    </AdminShell>
  );
}
