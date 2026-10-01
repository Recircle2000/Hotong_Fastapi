import { useEffect, useState } from "react";

import { AdminShell } from "../components/AdminShell";
import { useDocumentTitle } from "../hooks/useDocumentTitle";
import { ApiError, getAdminTaxiSanctions, revokeAdminTaxiSanction } from "../lib/api";
import type { AdminTaxiSanction } from "../lib/types";
import { useToast } from "../toast/ToastProvider";
import { SanctionLevelBadge, sanctionPeriod, sanctionState } from "./taxiSanctionParts";

export function TaxiSanctionsPage() {
  useDocumentTitle("택시팟 제재");
  const { showToast } = useToast();
  const [activeOnly, setActiveOnly] = useState(true);
  const [target, setTarget] = useState<string | null>(null);
  const [search, setSearch] = useState("");
  const [items, setItems] = useState<AdminTaxiSanction[]>([]);
  const [nextCursor, setNextCursor] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  async function load(cursor?: string) {
    setLoading(true);
    setError(null);
    try {
      const result = await getAdminTaxiSanctions({
        active: target ? undefined : activeOnly || undefined,
        target: target ?? undefined,
        cursor,
      });
      setItems((current) => (cursor ? [...current, ...result.items] : result.items));
      setNextCursor(result.next_cursor);
    } catch (reason) {
      setError(reason instanceof ApiError ? reason.message : "제재 내역을 불러오지 못했습니다.");
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => { void load(); }, [activeOnly, target]);

  async function revoke(item: AdminTaxiSanction) {
    const reason = window.prompt(`사용자 ${item.target_key}의 제재를 철회할 사유를 입력해주세요.\n철회하면 바로 이용 제한이 풀리고 다음 단계 계산에서도 빠집니다.`);
    if (!reason?.trim()) return;
    try {
      await revokeAdminTaxiSanction(item.id, reason.trim());
      showToast("제재를 철회했습니다.", "success");
      await load();
    } catch (cause) {
      showToast(cause instanceof ApiError ? cause.message : "제재를 철회하지 못했습니다.", "error");
    }
  }

  return (
    <AdminShell
      title="택시팟 제재"
      description="제재는 신고 상세에서 부과합니다. 이의제기는 사용자가 알려준 고유번호로 찾아 철회하세요."
    >
      <div className="mb-4 flex flex-wrap items-center gap-3">
        {target ? (
          <div className="flex items-center gap-2 rounded-lg border border-blue-200 bg-blue-50 px-3 py-2 text-sm text-blue-800">
            <span>사용자 <span className="font-mono font-semibold">{target}</span>의 제재 전체</span>
            <button type="button" onClick={() => setTarget(null)} className="rounded border border-blue-200 bg-white px-2 py-0.5 text-xs">해제</button>
          </div>
        ) : (
          <div className="flex rounded-lg border border-slate-300 bg-white p-1">
            {([[true, "적용 중"], [false, "전체"]] as const).map(([value, label]) => (
              <button
                key={label}
                type="button"
                onClick={() => setActiveOnly(value)}
                className={`rounded-md px-4 py-1.5 text-sm font-medium transition ${activeOnly === value ? "bg-slate-900 text-white" : "text-slate-600 hover:bg-slate-50"}`}
              >
                {label}
              </button>
            ))}
          </div>
        )}
        <form
          className="flex items-center gap-2"
          onSubmit={(event) => {
            event.preventDefault();
            const key = search.trim().toLowerCase();
            if (/^[0-9a-f]{6}$/.test(key)) setTarget(key);
            else showToast("고유번호는 앱 내정보에 보이는 6자리입니다.", "error");
          }}
        >
          <input value={search} onChange={(event) => setSearch(event.target.value)} maxLength={6} placeholder="고유번호 6자리" aria-label="고유번호 검색" className="w-36 rounded-lg border border-slate-300 bg-white px-3 py-2 font-mono text-sm" />
          <button type="submit" className="rounded-lg border border-slate-300 bg-white px-3 py-2 text-sm">찾기</button>
        </form>
        <button type="button" onClick={() => void load()} className="rounded-lg border border-slate-300 bg-white px-3 py-2 text-sm">새로고침</button>
      </div>
      {error ? <div className="mb-4 rounded-lg border border-rose-200 bg-rose-50 p-4 text-sm text-rose-700">{error}</div> : null}
      <section className="overflow-hidden rounded-2xl border border-slate-200 bg-white shadow-sm">
        {loading && items.length === 0 ? <div className="p-8 text-sm text-slate-500">불러오는 중입니다.</div> : items.length === 0 ? <div className="p-8 text-sm text-slate-500">{activeOnly && !target ? "적용 중인 이용 정지가 없습니다." : "제재 내역이 없습니다."}</div> : (
          <div className="overflow-x-auto">
            <table className="min-w-full text-left text-sm">
              <thead className="bg-slate-50 text-slate-600">
                <tr>
                  <th className="px-5 py-3">대상</th>
                  <th className="px-5 py-3">단계</th>
                  <th className="px-5 py-3">기간</th>
                  <th className="px-5 py-3">사유</th>
                  <th className="px-5 py-3">상태</th>
                  <th className="px-5 py-3">관리</th>
                </tr>
              </thead>
              <tbody>
                {items.map((item) => {
                  const state = sanctionState(item);
                  return (
                    <tr key={item.id} className="border-t border-slate-200 align-top">
                      <td className="whitespace-nowrap px-5 py-4">
                        <button type="button" onClick={() => setTarget(item.target_key)} className="font-mono font-semibold text-blue-700">{item.target_key}</button>
                        <div className="text-xs text-slate-500">신고 {item.report_count}건 연결</div>
                      </td>
                      <td className="px-5 py-4"><SanctionLevelBadge level={item.level} /></td>
                      <td className="whitespace-nowrap px-5 py-4 text-slate-600">{sanctionPeriod(item)}</td>
                      <td className="px-5 py-4">
                        {item.reason}
                        {item.admin_note ? <div className="mt-1 text-xs text-slate-500">메모: {item.admin_note}</div> : null}
                        {item.revoke_reason ? <div className="mt-1 text-xs text-slate-500">철회 사유: {item.revoke_reason}</div> : null}
                      </td>
                      <td className={`whitespace-nowrap px-5 py-4 ${state.className}`}>{state.label}</td>
                      <td className="px-5 py-4">
                        {!item.revoked_at ? <button type="button" onClick={() => void revoke(item)} className="rounded border border-slate-300 px-3 py-1 text-slate-700">철회</button> : "-"}
                      </td>
                    </tr>
                  );
                })}
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
    </AdminShell>
  );
}
