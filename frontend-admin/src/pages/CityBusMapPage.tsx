import { ChangeEvent, Fragment, useEffect, useState } from "react";
import { Link } from "react-router-dom";

import { AdminShell } from "../components/AdminShell";
import { useDocumentTitle } from "../hooks/useDocumentTitle";
import { ApiError } from "../lib/api";
import { compareCityBusStops, getCityBusReleases, getCityBusRoutes, uploadCityBusRouteFile } from "../lib/cityBusApi";
import { formatDateTime } from "../lib/cityBusTimes";
import type { CityBusRelease, CityBusRoute, CityBusStopRef, CityBusStopsCompare } from "../lib/cityBusTypes";
import { useToast } from "../toast/ToastProvider";

type Part = "geojson" | "stops";

type CompareState =
  | { status: "loading" }
  | { status: "error"; message: string }
  | { status: "done"; data: CityBusStopsCompare };

function hasStopChanges(data: CityBusStopsCompare) {
  return data.reordered || data.added.length > 0 || data.removed.length > 0 || data.renamed.length > 0 || data.moved.length > 0;
}

function stopLabel(stop: CityBusStopRef) {
  return `${stop.nodeord ?? "-"}. ${stop.nodenm}`;
}

function StopsCompareResult({
  data,
  replacing,
  onReplace,
}: {
  data: CityBusStopsCompare;
  replacing: boolean;
  onReplace: () => void;
}) {
  const changed = hasStopChanges(data);
  const summary = [
    `저장 ${data.current_count}개`,
    `공공데이터 ${data.fetched_count}개`,
    data.added.length ? `추가 ${data.added.length}` : null,
    data.removed.length ? `삭제 ${data.removed.length}` : null,
    data.renamed.length ? `이름 변경 ${data.renamed.length}` : null,
    data.moved.length ? `위치 이동 ${data.moved.length}` : null,
    data.reordered ? "순서 변경" : null,
  ].filter(Boolean);
  return (
    <div className="space-y-2 text-sm">
      <p className="text-slate-700">{summary.join(" · ")}</p>
      <p className="text-xs text-slate-500">노선 ID {data.route_id} (도시코드 {data.city_code}) · {formatDateTime(data.fetched_at)} 조회</p>
      {!changed ? <p className="text-slate-500">저장된 정류장과 같습니다.</p> : (
        <ul className="space-y-1">
          {data.added.map((stop) => <li key={`a-${stop.nodeid}`} className="text-emerald-700">추가 {stopLabel(stop)}</li>)}
          {data.removed.map((stop) => <li key={`r-${stop.nodeid}`} className="text-rose-700">삭제 <span className="line-through">{stopLabel(stop)}</span></li>)}
          {data.renamed.map((stop) => <li key={`n-${stop.nodeid}`} className="text-slate-700">이름 변경 {stop.nodeord ?? "-"}. {stop.before} → <strong>{stop.nodenm}</strong></li>)}
          {data.moved.map((stop) => <li key={`m-${stop.nodeid}`} className="text-amber-700">위치 이동 {stopLabel(stop)} {stop.meters}m</li>)}
          {data.reordered ? <li className="text-slate-700">정류장 순서가 바뀌었습니다.</li> : null}
        </ul>
      )}
      {changed ? (
        <button
          type="button"
          disabled={replacing}
          onClick={onReplace}
          className="rounded-lg bg-slate-900 px-3 py-1.5 text-xs font-semibold text-white disabled:opacity-40"
        >
          {replacing ? "교체 중..." : "정류장 JSON 교체"}
        </button>
      ) : null}
    </div>
  );
}

const partLabels: Record<Part, string> = {
  geojson: "노선 선형(GeoJSON)",
  stops: "정류장(공공데이터 응답)",
};

function UploadButton({ label, onFile }: { label: string; onFile: (file: File) => void }) {
  function handleChange(event: ChangeEvent<HTMLInputElement>) {
    const file = event.target.files?.[0];
    event.target.value = "";
    if (file) onFile(file);
  }
  return (
    <label className="cursor-pointer rounded border border-slate-300 px-3 py-1 text-sm text-slate-700 hover:bg-slate-50">
      {label}
      <input type="file" accept=".json,.geojson,application/json" className="hidden" onChange={handleChange} />
    </label>
  );
}

export function CityBusMapPage() {
  useDocumentTitle("시내버스 노선도");
  const { showToast } = useToast();
  const [routes, setRoutes] = useState<CityBusRoute[]>([]);
  const [lastStatic, setLastStatic] = useState<CityBusRelease | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [compares, setCompares] = useState<Record<string, CompareState>>({});
  const [replacingKey, setReplacingKey] = useState<string | null>(null);

  async function load() {
    setLoading(true);
    setError(null);
    try {
      const [nextRoutes, releases] = await Promise.all([getCityBusRoutes(), getCityBusReleases("static")]);
      setRoutes(nextRoutes);
      setLastStatic(releases[0] ?? null);
    } catch (reason) {
      setError(reason instanceof ApiError ? reason.message : "노선도를 불러오지 못했습니다.");
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => { void load(); }, []);

  async function upload(route: CityBusRoute, part: Part, file: File) {
    let data: unknown;
    try {
      data = JSON.parse(await file.text());
    } catch {
      showToast(`${file.name}은 JSON 파일이 아닙니다.`, "error");
      return;
    }
    try {
      const updated = await uploadCityBusRouteFile(route.route_key, part, data);
      setRoutes((items) => items.map((item) => (item.route_key === updated.route_key ? updated : item)));
      showToast(`${route.route_key} ${partLabels[part]}을 바꿨습니다. 앱에는 배포해야 반영됩니다.`, "success");
    } catch (reason) {
      showToast(reason instanceof ApiError ? reason.message : "올리지 못했습니다.", "error");
    }
  }

  function setCompare(routeKey: string, state: CompareState | null) {
    setCompares((items) => {
      const next = { ...items };
      if (state) next[routeKey] = state;
      else delete next[routeKey];
      return next;
    });
  }

  // 누를 때마다 이 노선 하나만 공공데이터에 물어본다.
  async function compare(route: CityBusRoute) {
    setCompare(route.route_key, { status: "loading" });
    try {
      setCompare(route.route_key, { status: "done", data: await compareCityBusStops(route.route_key) });
    } catch (reason) {
      setCompare(route.route_key, {
        status: "error",
        message: reason instanceof ApiError ? reason.message : "공공데이터 정류장을 불러오지 못했습니다.",
      });
    }
  }

  async function replaceStops(route: CityBusRoute, data: CityBusStopsCompare) {
    if (!window.confirm(`${route.route_key} 정류장 JSON을 공공데이터 응답(${data.fetched_count}개)으로 바꿀까요? 노선 선형은 그대로입니다.`)) return;
    setReplacingKey(route.route_key);
    try {
      const updated = await uploadCityBusRouteFile(route.route_key, "stops", data.fetched);
      setRoutes((items) => items.map((item) => (item.route_key === updated.route_key ? updated : item)));
      setCompare(route.route_key, null);
      showToast(`${route.route_key} 정류장을 공공데이터로 바꿨습니다. 앱에는 배포해야 반영됩니다.`, "success");
    } catch (reason) {
      showToast(reason instanceof ApiError ? reason.message : "정류장을 바꾸지 못했습니다.", "error");
    } finally {
      setReplacingKey(null);
    }
  }

  const lastPublishedAt =lastStatic ? new Date(lastStatic.published_at).getTime() : null;

  return (
    <AdminShell
      title="시내버스 노선도"
      description="노선별 선형 GeoJSON과 정류장 JSON을 파일로 바꿉니다. 배포하면 한 파일로 묶여 Storage에 올라갑니다."
      actions={<Link to="/city-bus/releases" className="rounded-lg bg-blue-600 px-4 py-2 text-sm font-semibold text-white">배포하기</Link>}
      summary={
        <p className="text-sm text-slate-600">
          마지막 노선도 배포 <strong className="text-slate-900">{lastStatic ? `${lastStatic.version} (${formatDateTime(lastStatic.published_at)})` : "없음"}</strong>
          <span className="ml-2 text-slate-400">· 노선 추가·삭제는 시간표 화면에서 합니다.</span>
        </p>
      }
    >
      {error ? <div className="mb-4 rounded-lg border border-rose-200 bg-rose-50 p-4 text-sm text-rose-700">{error}</div> : null}
      <section className="overflow-hidden rounded-2xl border border-slate-200 bg-white shadow-sm">
        {loading && !routes.length ? <div className="p-8 text-sm text-slate-500">불러오는 중입니다.</div> : (
          <div className="overflow-x-auto">
            <table className="min-w-full text-left text-sm">
              <thead className="bg-slate-50 text-slate-600">
                <tr>
                  <th className="px-5 py-3">노선</th>
                  <th className="px-5 py-3">선형</th>
                  <th className="px-5 py-3">정류장</th>
                  <th className="px-5 py-3">마지막 수정</th>
                  <th className="px-5 py-3">파일 바꾸기</th>
                </tr>
              </thead>
              <tbody>
                {routes.map((route) => {
                  const updatedAt = route.updated_at ? new Date(route.updated_at).getTime() : null;
                  const maybeChanged = updatedAt !== null && (lastPublishedAt === null || updatedAt > lastPublishedAt);
                  const compareState = compares[route.route_key];
                  return (
                    <Fragment key={route.route_key}>
                    <tr className="border-t border-slate-200">
                      <td className="px-5 py-3 font-medium text-slate-900">{route.route_key}</td>
                      <td className="px-5 py-3">{route.geojson_feature_count ? `${route.geojson_feature_count}개 구간` : <span className="text-slate-400">없음</span>}</td>
                      <td className="px-5 py-3">{route.stop_count ? `${route.stop_count}개` : <span className="text-slate-400">없음</span>}</td>
                      <td className="px-5 py-3 text-slate-600">
                        {formatDateTime(route.updated_at)}
                        {maybeChanged ? <span className="ml-2 rounded-full bg-amber-50 px-2 py-0.5 text-xs text-amber-700" title="시간표 수정도 포함됩니다">배포 이후 수정</span> : null}
                      </td>
                      <td className="px-5 py-3">
                        <div className="flex gap-2">
                          <UploadButton label="선형" onFile={(file) => void upload(route, "geojson", file)} />
                          <UploadButton label="정류장" onFile={(file) => void upload(route, "stops", file)} />
                          <button
                            type="button"
                            disabled={compareState?.status === "loading"}
                            onClick={() => void compare(route)}
                            className="rounded border border-slate-300 px-3 py-1 text-sm text-slate-700 hover:bg-slate-50 disabled:opacity-40"
                          >
                            {compareState?.status === "loading" ? "불러오는 중..." : "공공데이터와 비교"}
                          </button>
                        </div>
                      </td>
                    </tr>
                    {compareState ? (
                      <tr className="bg-slate-50">
                        <td colSpan={5} className="px-5 py-3">
                          <div className="flex items-start justify-between gap-4">
                            {compareState.status === "loading" ? (
                              <p className="text-sm text-slate-500">공공데이터에서 정류장 목록을 받아오는 중입니다.</p>
                            ) : compareState.status === "error" ? (
                              <p className="text-sm text-rose-700">{compareState.message}</p>
                            ) : (
                              <StopsCompareResult
                                data={compareState.data}
                                replacing={replacingKey === route.route_key}
                                onReplace={() => void replaceStops(route, compareState.data)}
                              />
                            )}
                            <button type="button" onClick={() => setCompare(route.route_key, null)} className="shrink-0 text-xs text-slate-500 hover:text-slate-800">닫기</button>
                          </div>
                        </td>
                      </tr>
                    ) : null}
                    </Fragment>
                  );
                })}
              </tbody>
            </table>
          </div>
        )}
      </section>
    </AdminShell>
  );
}
