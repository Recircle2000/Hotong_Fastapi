import { apiRequest } from "./api";
import type {
  CityBusBisTimetable,
  CityBusRelease,
  CityBusReleaseKind,
  CityBusRoute,
  CityBusRoutePayload,
  CityBusStopsCompare,
  CityBusTimetableFile,
} from "./cityBusTypes";

const BASE = "/city-bus";

export function getCityBusRoutes() {
  return apiRequest<CityBusRoute[]>(`${BASE}/routes`);
}

export function createCityBusRoute(payload: CityBusRoutePayload & { route_key: string }) {
  return apiRequest<CityBusRoute>(`${BASE}/routes`, { method: "POST", body: payload });
}

export function updateCityBusRoute(routeKey: string, payload: CityBusRoutePayload) {
  return apiRequest<CityBusRoute>(`${BASE}/routes/${encodeURIComponent(routeKey)}`, {
    method: "PUT",
    body: payload,
  });
}

export function deleteCityBusRoute(routeKey: string) {
  return apiRequest<void>(`${BASE}/routes/${encodeURIComponent(routeKey)}`, { method: "DELETE" });
}

export function reorderCityBusRoutes(routeKeys: string[]) {
  return apiRequest<CityBusRoute[]>(`${BASE}/routes/order`, {
    method: "PUT",
    body: { route_keys: routeKeys },
  });
}

/** 그 노선 하나의 BIS 평일 시간표를 받아온다. 비교만 하고 저장하지 않는다. */
export function getCityBusBisTimetable(routeKey: string) {
  return apiRequest<CityBusBisTimetable>(`${BASE}/routes/${encodeURIComponent(routeKey)}/bis-timetable`);
}

/** 그 노선 하나의 공공데이터 경유정류소 목록을 받아 저장된 정류장과 비교한다. 저장하지 않는다. */
export function compareCityBusStops(routeKey: string) {
  return apiRequest<CityBusStopsCompare>(`${BASE}/routes/${encodeURIComponent(routeKey)}/stops-compare`);
}

export function uploadCityBusRouteFile(routeKey: string, part: "geojson" | "stops", data: unknown) {
  return apiRequest<CityBusRoute>(`${BASE}/routes/${encodeURIComponent(routeKey)}/${part}`, {
    method: "PUT",
    body: data as object,
  });
}

export function getCityBusReleases(kind?: CityBusReleaseKind) {
  return apiRequest<CityBusRelease[]>(`${BASE}/releases${kind ? `?kind=${kind}` : ""}`);
}

export function publishCityBusRelease(kind: CityBusReleaseKind, effectiveFrom: string | null, note: string | null) {
  return apiRequest<CityBusRelease>(`${BASE}/releases/${kind}`, {
    method: "POST",
    body: { effective_from: effectiveFrom, note },
  });
}

export function getCityBusTimetableFile(releaseId: number) {
  return apiRequest<CityBusTimetableFile>(`${BASE}/releases/${releaseId}/file`);
}

/** 지금 앱에 내려가는 시간표 게시본. 없으면 null. */
export async function getCurrentCityBusTimetable() {
  const releases = await getCityBusReleases("timetable");
  const current = releases.find((release) => release.is_current);
  return current ? getCityBusTimetableFile(current.id) : null;
}
