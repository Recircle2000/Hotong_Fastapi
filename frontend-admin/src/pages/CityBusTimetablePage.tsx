import { FormEvent, useEffect, useMemo, useRef, useState } from "react";
import { Link } from "react-router-dom";

import { AdminModal } from "../components/AdminModal";
import { AdminShell } from "../components/AdminShell";
import { useDocumentTitle } from "../hooks/useDocumentTitle";
import { ApiError } from "../lib/api";
import {
  createCityBusRoute,
  deleteCityBusRoute,
  getCityBusBisTimetable,
  getCityBusRoutes,
  getCurrentCityBusTimetable,
  updateCityBusRoute,
} from "../lib/cityBusApi";
import { checkTimes, diffRoute, diffTimes, formatDateTime, hasRouteChanges, removedRouteKeys } from "../lib/cityBusTimes";
import type { CityBusBisTimetable, CityBusRoute, CityBusTimetableFile } from "../lib/cityBusTypes";
import { useToast } from "../toast/ToastProvider";

type Draft = { origin: string; terminus: string; timesText: string };

function toDraft(route: CityBusRoute): Draft {
  return { origin: route.origin, terminus: route.terminus, timesText: route.times.join("\n") };
}

const BIS_SOURCE_LABEL: Record<CityBusBisTimetable["source"], string> = { asan: "아산 BIS", cheonan: "천안 BIS" };

type BisState =
  | { status: "idle" }
  | { status: "loading" }
  | { status: "error"; message: string }
  | { status: "done"; data: CityBusBisTimetable };

function errorMessage(reason: unknown, fallback: string) {
  return reason instanceof ApiError ? reason.message : fallback;
}

export function CityBusTimetablePage() {
  useDocumentTitle("시내버스 시간표");
  const { showToast } = useToast();
  const [routes, setRoutes] = useState<CityBusRoute[]>([]);
  const [published, setPublished] = useState<CityBusTimetableFile | null>(null);
  const [selectedKey, setSelectedKey] = useState<string | null>(null);
  const [draft, setDraft] = useState<Draft>({ origin: "", terminus: "", timesText: "" });
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [creating, setCreating] = useState(false);
  const [newKey, setNewKey] = useState("");
  const [bis, setBis] = useState<BisState>({ status: "idle" });
  // BIS 응답이 오기 전에 다른 노선으로 옮겼으면 그 응답은 버린다.
  const selectedKeyRef = useRef(selectedKey);
  selectedKeyRef.current = selectedKey;

  async function load(keepKey?: string | null) {
    setLoading(true);
    setError(null);
    try {
      const [nextRoutes, nextPublished] = await Promise.all([getCityBusRoutes(), getCurrentCityBusTimetable()]);
      setRoutes(nextRoutes);
      setPublished(nextPublished);
      const key = keepKey && nextRoutes.some((route) => route.route_key === keepKey) ? keepKey : nextRoutes[0]?.route_key ?? null;
      setSelectedKey(key);
      setBis({ status: "idle" });
      const route = nextRoutes.find((item) => item.route_key === key);
      if (route) setDraft(toDraft(route));
    } catch (reason) {
      setError(errorMessage(reason, "시간표를 불러오지 못했습니다."));
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => { void load(); }, []);

  const selected = routes.find((route) => route.route_key === selectedKey) ?? null;
  const check = useMemo(() => checkTimes(draft.timesText), [draft.timesText]);
  const dirty = selected
    ? selected.origin !== draft.origin || selected.terminus !== draft.terminus || selected.times.join(",") !== check.times.join(",")
    : false;
  const changedRoutes = routes.filter((route) => hasRouteChanges(diffRoute(route, published)));
  const removedKeys = removedRouteKeys(routes, published);
  const pendingCount = changedRoutes.length + removedKeys.length;

  // 저장하기 전 편집 내용까지 반영해 게시본과 비교한다.
  const bisDiff = bis.status === "done" ? diffTimes(check.times, bis.data.times) : null;
  const selectedDiff = selected
    ? diffRoute({ ...selected, origin: draft.origin, terminus: draft.terminus, times: check.times }, published)
    : null;

  function select(route: CityBusRoute) {
    if (dirty && !window.confirm("저장하지 않은 변경 사항이 있습니다. 다른 노선으로 이동할까요?")) return;
    setSelectedKey(route.route_key);
    setDraft(toDraft(route));
    setBis({ status: "idle" });
  }

  // 누를 때마다 이 노선 하나만 BIS에 물어본다.
  async function compareWithBis() {
    if (!selected) return;
    const routeKey = selected.route_key;
    setBis({ status: "loading" });
    let next: BisState;
    try {
      next = { status: "done", data: await getCityBusBisTimetable(routeKey) };
    } catch (reason) {
      next = { status: "error", message: errorMessage(reason, "BIS 시간표를 불러오지 못했습니다.") };
    }
    if (selectedKeyRef.current === routeKey) setBis(next);
  }

  function applyBisTimes(times: string[]) {
    setDraft({ ...draft, timesText: times.join("\n") });
    showToast("BIS 시각을 편집기에 넣었습니다. 초안 저장을 눌러야 저장됩니다.", "success");
  }

  async function save(event: FormEvent) {
    event.preventDefault();
    if (!selected) return;
    if (check.invalid.length) {
      showToast(`존재하지 않는 시각이 있습니다: ${check.invalid.join(", ")}`, "error");
      return;
    }
    setSaving(true);
    try {
      const updated = await updateCityBusRoute(selected.route_key, {
        origin: draft.origin.trim(),
        terminus: draft.terminus.trim(),
        times: check.times,
      });
      setRoutes((items) => items.map((item) => (item.route_key === updated.route_key ? updated : item)));
      setDraft(toDraft(updated));
      showToast(`${updated.route_key} 초안을 저장했습니다. 앱에는 배포해야 반영됩니다.`, "success");
    } catch (reason) {
      showToast(errorMessage(reason, "저장하지 못했습니다."), "error");
    } finally {
      setSaving(false);
    }
  }

  async function create(event: FormEvent) {
    event.preventDefault();
    try {
      const route = await createCityBusRoute({ route_key: newKey.trim(), origin: "", terminus: "", times: [] });
      setCreating(false);
      setNewKey("");
      showToast(`${route.route_key} 노선을 추가했습니다.`, "success");
      await load(route.route_key);
    } catch (reason) {
      showToast(errorMessage(reason, "노선을 추가하지 못했습니다."), "error");
    }
  }

  async function remove() {
    if (!selected) return;
    if (!window.confirm(`${selected.route_key} 노선을 지울까요? 노선도 데이터도 함께 지워지고, 다음 배포부터 앱에서 빠집니다.`)) return;
    try {
      await deleteCityBusRoute(selected.route_key);
      showToast(`${selected.route_key} 노선을 지웠습니다.`, "success");
      await load();
    } catch (reason) {
      showToast(errorMessage(reason, "노선을 지우지 못했습니다."), "error");
    }
  }

  return (
    <AdminShell
      title="시내버스 시간표"
      description="노선별 출발지·종점·출발 시각을 고칩니다. 저장은 초안이고, 배포해야 앱에 반영됩니다."
      actions={
        <>
          <button type="button" onClick={() => setCreating(true)} className="rounded-lg border border-slate-300 px-4 py-2 text-sm font-semibold text-slate-700">노선 추가</button>
          <Link to="/city-bus/releases" className="rounded-lg bg-blue-600 px-4 py-2 text-sm font-semibold text-white">배포하기</Link>
        </>
      }
      summary={
        <div className="flex flex-wrap items-center gap-x-6 gap-y-1 text-sm text-slate-600">
          <span>게시된 버전 <strong className="text-slate-900">{published?.version ?? "없음"}</strong></span>
          <span>
            배포 안 된 변경{" "}
            <strong className={pendingCount ? "text-amber-700" : "text-slate-900"}>{pendingCount}개 노선</strong>
            {removedKeys.length ? ` (삭제 ${removedKeys.join(", ")})` : ""}
          </span>
        </div>
      }
    >
      {error ? <div className="mb-4 rounded-lg border border-rose-200 bg-rose-50 p-4 text-sm text-rose-700">{error}</div> : null}
      {loading && !routes.length ? <div className="p-8 text-sm text-slate-500">불러오는 중입니다.</div> : (
        <div className="grid gap-6 lg:grid-cols-[16rem_minmax(0,1fr)]">
          <nav className="h-fit overflow-hidden rounded-2xl border border-slate-200 bg-white shadow-sm">
            {routes.map((route) => {
              const changed = hasRouteChanges(diffRoute(route, published));
              const active = route.route_key === selectedKey;
              return (
                <button
                  key={route.route_key}
                  type="button"
                  onClick={() => select(route)}
                  className={`flex w-full items-center justify-between border-b border-slate-100 px-4 py-2.5 text-left text-sm last:border-b-0 ${active ? "bg-slate-100 font-semibold text-slate-900" : "text-slate-700 hover:bg-slate-50"}`}
                >
                  <span>{route.route_key}</span>
                  <span className="flex items-center gap-2 text-xs text-slate-400">
                    {changed ? <span className="h-2 w-2 rounded-full bg-amber-500" title="배포 안 된 변경" /> : null}
                    {route.times.length ? `${route.times.length}회` : "노선도만"}
                  </span>
                </button>
              );
            })}
          </nav>

          {selected ? (
            <form onSubmit={save} className="space-y-5 rounded-2xl border border-slate-200 bg-white p-5 shadow-sm">
              <div className="flex flex-wrap items-center justify-between gap-2">
                <h2 className="text-lg font-semibold text-slate-900">{selected.route_key}</h2>
                <span className="text-xs text-slate-400">마지막 저장 {formatDateTime(selected.updated_at)}</span>
              </div>
              <div className="grid gap-4 sm:grid-cols-2">
                <label className="block text-sm font-medium text-slate-700">출발지
                  <input maxLength={100} value={draft.origin} onChange={(e) => setDraft({ ...draft, origin: e.target.value })} className="mt-2 w-full rounded-lg border border-slate-300 px-3 py-2" />
                </label>
                <label className="block text-sm font-medium text-slate-700">종점
                  <input maxLength={100} value={draft.terminus} onChange={(e) => setDraft({ ...draft, terminus: e.target.value })} className="mt-2 w-full rounded-lg border border-slate-300 px-3 py-2" />
                </label>
              </div>
              <div className="grid gap-4 md:grid-cols-[minmax(0,1fr)_minmax(0,1fr)]">
                <label className="block text-sm font-medium text-slate-700">출발 시각
                  <textarea
                    rows={14}
                    value={draft.timesText}
                    onChange={(e) => setDraft({ ...draft, timesText: e.target.value })}
                    placeholder={"06:50\n07:20\n...\n엑셀·PDF에서 복사한 표를 그대로 붙여넣어도 됩니다."}
                    className="mt-2 w-full rounded-lg border border-slate-300 px-3 py-2 font-mono text-sm"
                  />
                  <span className="mt-1 block text-xs font-normal text-slate-500">
                    시각 {check.times.length}개를 인식했습니다. 저장하면 정렬되고 중복은 하나로 합칩니다.
                  </span>
                  {check.duplicates.length ? <span className="mt-1 block text-xs font-normal text-amber-700">중복: {check.duplicates.join(", ")}</span> : null}
                  {check.invalid.length ? <span className="mt-1 block text-xs font-normal text-rose-600">존재하지 않는 시각: {check.invalid.join(", ")}</span> : null}
                </label>
                <div className="text-sm">
                  <p className="font-medium text-slate-700">게시본과 비교</p>
                  <div className="mt-2 rounded-lg border border-slate-200 bg-slate-50 p-3">
                    {!selectedDiff || !hasRouteChanges(selectedDiff) ? (
                      <p className="text-slate-500">게시된 시간표와 같습니다.</p>
                    ) : (
                      <div className="space-y-2">
                        {selectedDiff.isNew ? <p className="text-slate-700">게시본에 없는 새 노선입니다.</p> : null}
                        {selectedDiff.infoChanged ? <p className="text-slate-700">출발지·종점이 바뀌었습니다.</p> : null}
                        {selectedDiff.added.length && !selectedDiff.isNew ? (
                          <p className="text-emerald-700">추가 <span className="font-mono">{selectedDiff.added.join(" ")}</span></p>
                        ) : null}
                        {selectedDiff.removed.length ? (
                          <p className="text-rose-700">삭제 <span className="font-mono line-through">{selectedDiff.removed.join(" ")}</span></p>
                        ) : null}
                      </div>
                    )}
                  </div>
                  <div className="mt-4 flex items-center justify-between gap-2">
                    <p className="font-medium text-slate-700">BIS 시간표와 비교</p>
                    <button
                      type="button"
                      disabled={bis.status === "loading"}
                      onClick={() => void compareWithBis()}
                      className="rounded-lg border border-slate-300 px-3 py-1.5 text-xs font-semibold text-slate-700 disabled:opacity-40"
                    >
                      {bis.status === "loading" ? "불러오는 중..." : bis.status === "idle" ? "BIS와 비교" : "다시 비교"}
                    </button>
                  </div>
                  <div className="mt-2 rounded-lg border border-slate-200 bg-slate-50 p-3">
                    {bis.status === "idle" ? (
                      <p className="text-slate-500">누르면 이 노선의 아산·천안 BIS 평일 시간표를 받아와 지금 편집 중인 시각과 비교합니다.</p>
                    ) : bis.status === "loading" ? (
                      <p className="text-slate-500">BIS에서 시간표를 받아오는 중입니다.</p>
                    ) : bis.status === "error" ? (
                      <p className="text-rose-700">{bis.message}</p>
                    ) : (
                      <div className="space-y-2">
                        <p className="text-xs text-slate-500">
                          <a href={bis.data.source_url} target="_blank" rel="noreferrer" className="font-semibold text-blue-700 underline">{BIS_SOURCE_LABEL[bis.data.source]}</a>
                          {" "}평일 {bis.data.times.length}회 · {formatDateTime(bis.data.fetched_at)} 조회
                        </p>
                        {bisDiff && (bisDiff.added.length || bisDiff.removed.length) ? (
                          <>
                            {bisDiff.added.length ? (
                              <p className="text-emerald-700">BIS에만 있음 <span className="font-mono">{bisDiff.added.join(" ")}</span></p>
                            ) : null}
                            {bisDiff.removed.length ? (
                              <p className="text-rose-700">초안에만 있음 <span className="font-mono line-through">{bisDiff.removed.join(" ")}</span></p>
                            ) : null}
                            <button
                              type="button"
                              onClick={() => applyBisTimes(bis.data.times)}
                              className="rounded-lg bg-slate-900 px-3 py-1.5 text-xs font-semibold text-white"
                            >
                              편집기에 반영
                            </button>
                          </>
                        ) : (
                          <p className="text-slate-500">편집 중인 시각과 같습니다.</p>
                        )}
                      </div>
                    )}
                  </div>
                  <p className="mt-3 text-xs text-slate-500">
                    출발지·종점·시각을 모두 비우면 시간표 없이 노선도만 있는 노선으로 취급해 시간표 배포에서 빠집니다.
                  </p>
                </div>
              </div>
              <div className="flex flex-wrap items-center justify-between gap-3 border-t border-slate-100 pt-4">
                <button type="button" onClick={() => void remove()} className="rounded-lg border border-rose-200 px-4 py-2 text-sm text-rose-700">노선 삭제</button>
                <div className="flex gap-2">
                  <button type="button" disabled={!dirty} onClick={() => setDraft(toDraft(selected))} className="rounded-lg border border-slate-300 px-4 py-2 text-sm disabled:opacity-40">되돌리기</button>
                  <button disabled={saving || !dirty} className="rounded-lg bg-blue-600 px-5 py-2 text-sm font-semibold text-white disabled:bg-blue-300">{saving ? "저장 중..." : "초안 저장"}</button>
                </div>
              </div>
            </form>
          ) : (
            <div className="rounded-2xl border border-slate-200 bg-white p-8 text-sm text-slate-500 shadow-sm">노선이 없습니다. 노선을 추가해 주세요.</div>
          )}
        </div>
      )}

      {creating ? (
        <AdminModal title="노선 추가" onClose={() => setCreating(false)}>
          <form onSubmit={create} className="space-y-4">
            <label className="block text-sm font-medium">노선 키
              <input required autoFocus maxLength={32} value={newKey} onChange={(e) => setNewKey(e.target.value)} placeholder="예: 810_UP, 순환5_DOWN" className="mt-2 w-full rounded-lg border border-slate-300 px-3 py-2" />
              <span className="mt-1 block text-xs font-normal text-slate-500">번호 뒤에 상행은 _UP, 하행은 _DOWN을 붙입니다. 앱 노선 화면이 이 키로 데이터를 찾습니다.</span>
            </label>
            <button disabled={!newKey.trim()} className="w-full rounded-lg bg-blue-600 px-4 py-3 font-semibold text-white disabled:bg-blue-300">추가</button>
          </form>
        </AdminModal>
      ) : null}
    </AdminShell>
  );
}
