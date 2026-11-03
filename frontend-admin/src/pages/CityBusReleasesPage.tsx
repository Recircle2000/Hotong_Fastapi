import { useEffect, useState } from "react";

import { AdminShell } from "../components/AdminShell";
import { useDocumentTitle } from "../hooks/useDocumentTitle";
import { ApiError } from "../lib/api";
import {
  getCityBusReleases,
  getCityBusRoutes,
  getCityBusTimetableFile,
  publishCityBusRelease,
} from "../lib/cityBusApi";
import { diffRoute, formatDateTime, hasRouteChanges, removedRouteKeys } from "../lib/cityBusTimes";
import type { CityBusRelease, CityBusReleaseKind, CityBusRoute, CityBusTimetableFile } from "../lib/cityBusTypes";
import { useToast } from "../toast/ToastProvider";

// 구버전 앱은 깃허브 페이지에서 받으므로, 전환 기간에는 같은 파일을 여기에도 올린다.
const GITHUB_STATIC_URL = "https://recircle2000.github.io/hotong_station_image/bus_static_data.json";

const kindLabels: Record<CityBusReleaseKind, string> = { timetable: "시간표", static: "노선도" };

function errorMessage(reason: unknown, fallback: string) {
  return reason instanceof ApiError ? reason.message : fallback;
}

function saveJsonFile(data: unknown, fileName: string) {
  const blob = new Blob([JSON.stringify(data, null, 2)], { type: "application/json" });
  const url = URL.createObjectURL(blob);
  const link = document.createElement("a");
  link.href = url;
  link.download = fileName;
  link.click();
  URL.revokeObjectURL(url);
}

function githubManifest(release: CityBusRelease) {
  return JSON.stringify(
    {
      version: release.version,
      ...(release.effective_from ? { effectiveFrom: release.effective_from } : {}),
      downloadUrl: GITHUB_STATIC_URL,
    },
    null,
    2,
  );
}

function StatusBadge({ release }: { release: CityBusRelease }) {
  if (release.is_current) return <span className="rounded-full bg-emerald-50 px-2.5 py-0.5 text-xs font-semibold text-emerald-700">적용 중</span>;
  if (release.is_scheduled) return <span className="rounded-full bg-blue-50 px-2.5 py-0.5 text-xs font-semibold text-blue-700">예약</span>;
  return <span className="rounded-full bg-slate-100 px-2.5 py-0.5 text-xs text-slate-500">이전</span>;
}

function PublishCard({
  kind,
  pendingText,
  canPublish,
  onPublished,
}: {
  kind: CityBusReleaseKind;
  pendingText: string;
  canPublish: boolean;
  onPublished: () => Promise<void>;
}) {
  const { showToast } = useToast();
  const [scheduleAt, setScheduleAt] = useState("");
  const [note, setNote] = useState("");
  const [publishing, setPublishing] = useState(false);

  async function publish() {
    const effectiveFrom = scheduleAt ? new Date(scheduleAt).toISOString() : null;
    const when = scheduleAt ? `${new Date(scheduleAt).toLocaleString("ko-KR")}부터` : "지금 바로";
    if (!window.confirm(`${kindLabels[kind]}을 ${when} 앱에 배포할까요?`)) return;
    setPublishing(true);
    try {
      const release = await publishCityBusRelease(kind, effectiveFrom, note.trim() || null);
      showToast(`${kindLabels[kind]} ${release.version}을 배포했습니다.`, "success");
      setScheduleAt("");
      setNote("");
      await onPublished();
    } catch (reason) {
      showToast(errorMessage(reason, "배포하지 못했습니다."), "error");
    } finally {
      setPublishing(false);
    }
  }

  return (
    <div className="rounded-2xl border border-slate-200 bg-white p-5 shadow-sm">
      <h2 className="text-base font-semibold text-slate-900">{kindLabels[kind]} 배포</h2>
      <p className="mt-1 text-sm text-slate-600">{pendingText}</p>
      <div className="mt-4 flex flex-wrap items-end gap-3">
        <label className="min-w-0 flex-1 basis-56 text-sm text-slate-700">변경 메모 (앱 변경이력에 표시, 선택)
          <input
            maxLength={200}
            value={note}
            onChange={(e) => setNote(e.target.value)}
            placeholder="예: 동계 방학 감차 반영"
            className="mt-1 block w-full rounded-lg border border-slate-300 px-3 py-2"
          />
        </label>
        <label className="text-sm text-slate-700">적용 시각 (비우면 즉시)
          <input type="datetime-local" value={scheduleAt} onChange={(e) => setScheduleAt(e.target.value)} className="mt-1 block rounded-lg border border-slate-300 px-3 py-2" />
        </label>
        <button type="button" disabled={publishing || !canPublish} onClick={() => void publish()} className="rounded-lg bg-blue-600 px-5 py-2 text-sm font-semibold text-white disabled:bg-blue-300">
          {publishing ? "배포 중..." : scheduleAt ? "예약 배포" : "배포"}
        </button>
      </div>
    </div>
  );
}

export function CityBusReleasesPage() {
  useDocumentTitle("시내버스 배포");
  const { showToast } = useToast();
  const [routes, setRoutes] = useState<CityBusRoute[]>([]);
  const [releases, setReleases] = useState<CityBusRelease[]>([]);
  const [currentTimetable, setCurrentTimetable] = useState<CityBusTimetableFile | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  async function load() {
    setLoading(true);
    setError(null);
    try {
      const [nextRoutes, nextReleases] = await Promise.all([getCityBusRoutes(), getCityBusReleases()]);
      setRoutes(nextRoutes);
      setReleases(nextReleases);
      // 변경 비교는 가장 최근 게시본(예약 포함) 기준이다. 서버도 같은 기준으로 "변경 없음"을 막는다.
      const latest = nextReleases.find((release) => release.kind === "timetable");
      setCurrentTimetable(latest ? await getCityBusTimetableFile(latest.id) : null);
    } catch (reason) {
      setError(errorMessage(reason, "배포 정보를 불러오지 못했습니다."));
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => { void load(); }, []);

  const changed = routes.filter((route) => hasRouteChanges(diffRoute(route, currentTimetable)));
  const removed = removedRouteKeys(routes, currentTimetable);
  const timetableChanges = [...changed.map((route) => route.route_key), ...removed.map((key) => `${key}(삭제)`)];

  const lastStatic = releases.find((release) => release.kind === "static");
  const lastStaticAt = lastStatic ? new Date(lastStatic.published_at).getTime() : null;
  const staticTouched = routes.filter((route) => route.updated_at && (lastStaticAt === null || new Date(route.updated_at).getTime() > lastStaticAt));

  async function downloadTimetable(release: CityBusRelease) {
    try {
      saveJsonFile(await getCityBusTimetableFile(release.id), "bus_times.json");
    } catch (reason) {
      showToast(errorMessage(reason, "파일을 받지 못했습니다."), "error");
    }
  }

  async function copyManifest(release: CityBusRelease) {
    try {
      await navigator.clipboard.writeText(githubManifest(release));
      showToast("bus_static_manifest.json 내용을 복사했습니다.", "success");
    } catch {
      showToast("클립보드에 복사하지 못했습니다.", "error");
    }
  }

  return (
    <AdminShell
      title="시내버스 배포"
      description="저장한 초안을 앱에 배포합니다. 앱은 실행·복귀할 때 /api/app-config의 버전을 보고 새 버전만 내려받습니다."
    >
      {error ? <div className="mb-4 rounded-lg border border-rose-200 bg-rose-50 p-4 text-sm text-rose-700">{error}</div> : null}
      {loading && !releases.length ? <div className="p-8 text-sm text-slate-500">불러오는 중입니다.</div> : (
        <div className="space-y-6">
          <div className="grid gap-6 lg:grid-cols-2">
            <PublishCard
              kind="timetable"
              canPublish={timetableChanges.length > 0}
              pendingText={timetableChanges.length ? `마지막 배포 이후 바뀐 노선: ${timetableChanges.join(", ")}` : "마지막 배포와 같습니다."}
              onPublished={load}
            />
            <PublishCard
              kind="static"
              canPublish={routes.length > 0}
              pendingText={staticTouched.length ? `마지막 배포 이후 수정된 노선: ${staticTouched.map((route) => route.route_key).join(", ")} (시간표 수정 포함)` : "마지막 배포 이후 수정된 노선이 없습니다."}
              onPublished={load}
            />
          </div>

          <section className="rounded-2xl border border-amber-200 bg-amber-50 p-4 text-sm text-amber-900">
            <p className="font-semibold">전환 기간: 구버전 앱용 깃허브 파일도 맞춰 주세요</p>
            <p className="mt-1">
              구버전 앱은 서버 버전만 보고 깃허브 페이지에서 파일을 받습니다. 배포한 뒤 아래 이력에서 시간표는 <code>bus_times.json</code>을 받아,
              노선도는 파일과 매니페스트를 받아 깃허브 저장소에 같은 이름으로 올려 주세요.
            </p>
          </section>

          <section className="overflow-hidden rounded-2xl border border-slate-200 bg-white shadow-sm">
            <h2 className="border-b border-slate-200 px-5 py-3 text-base font-semibold text-slate-900">배포 이력</h2>
            <div className="overflow-x-auto">
              <table className="min-w-full text-left text-sm">
                <thead className="bg-slate-50 text-slate-600">
                  <tr>
                    <th className="px-5 py-3">종류</th>
                    <th className="px-5 py-3">버전</th>
                    <th className="px-5 py-3">상태</th>
                    <th className="px-5 py-3">적용 시각</th>
                    <th className="px-5 py-3">배포 시각</th>
                    <th className="px-5 py-3">변경 내용</th>
                    <th className="px-5 py-3">깃허브용 파일</th>
                  </tr>
                </thead>
                <tbody>
                  {releases.map((release) => (
                    <tr key={release.id} className="border-t border-slate-200">
                      <td className="px-5 py-3">{kindLabels[release.kind]}</td>
                      <td className="px-5 py-3 font-mono">{release.version}</td>
                      <td className="px-5 py-3"><StatusBadge release={release} /></td>
                      <td className="px-5 py-3 text-slate-600">{release.effective_from ? formatDateTime(release.effective_from) : "즉시"}</td>
                      <td className="px-5 py-3 text-slate-600">{formatDateTime(release.published_at)}</td>
                      <td className="max-w-md px-5 py-3 text-slate-700">
                        {release.note ? <p className="font-semibold text-slate-900">{release.note}</p> : null}
                        {release.changes === null ? (
                          release.note ? null : (
                            <p className="text-slate-400">
                              {releases.some((other) => other.kind === release.kind && other.id < release.id) ? "기록 없음" : "최초 등록"}
                            </p>
                          )
                        ) : release.changes.length ? (
                          <ul className="space-y-0.5 text-xs text-slate-600">
                            {release.changes.map((line) => <li key={line}>{line}</li>)}
                          </ul>
                        ) : (
                          <p className="text-xs text-slate-400">노선별 변경 없음</p>
                        )}
                      </td>
                      <td className="px-5 py-3">
                        {release.kind === "timetable" ? (
                          <button type="button" onClick={() => void downloadTimetable(release)} className="rounded border border-slate-300 px-3 py-1">bus_times.json</button>
                        ) : (
                          <div className="flex gap-2">
                            {release.download_url ? (
                              <a href={release.download_url} download="bus_static_data.json" target="_blank" rel="noreferrer" className="rounded border border-slate-300 px-3 py-1">bus_static_data.json</a>
                            ) : null}
                            <button type="button" onClick={() => void copyManifest(release)} className="rounded border border-slate-300 px-3 py-1">매니페스트 복사</button>
                          </div>
                        )}
                      </td>
                    </tr>
                  ))}
                  {!releases.length ? <tr><td colSpan={7} className="px-5 py-6 text-slate-500">배포 이력이 없습니다.</td></tr> : null}
                </tbody>
              </table>
            </div>
          </section>
        </div>
      )}
    </AdminShell>
  );
}
