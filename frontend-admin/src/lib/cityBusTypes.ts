export type CityBusReleaseKind = "timetable" | "static";

export type CityBusRoute = {
  route_key: string;
  sort_order: number;
  origin: string;
  terminus: string;
  times: string[];
  geojson_feature_count: number;
  stop_count: number;
  updated_at: string | null;
};

export type CityBusRoutePayload = {
  origin: string;
  terminus: string;
  times: string[];
};

export type CityBusRelease = {
  id: number;
  kind: CityBusReleaseKind;
  version: string;
  effective_from: string | null;
  published_at: string;
  download_url: string | null;
  sha256: string | null;
  size_bytes: number | null;
  /** 지금 앱에 내려가는 게시본 */
  is_current: boolean;
  /** 적용 시각이 아직 오지 않은 예약 게시본 */
  is_scheduled: boolean;
  /** 앱 변경이력에 나가는 관리자 메모 */
  note: string | null;
  /** 이전 게시본과 비교한 자동 요약. 비교할 게시본이 없었으면 null */
  changes: string[] | null;
};

/** 게시된 bus_times.json. version 외의 키는 노선 키다. */
export type CityBusTimetableFile = {
  version: string;
  [routeKey: string]: string | { 출발지: string; 종점: string; 시간표: string[] };
};

export type CityBusStopRef = { nodeid: string; nodeord: number | null; nodenm: string };

/** 공공데이터 경유정류소 목록과 저장된 정류장 JSON의 차이. 비교만 하고 저장되지 않는다. */
export type CityBusStopsCompare = {
  route_id: string;
  city_code: string;
  fetched_at: string;
  current_count: number;
  fetched_count: number;
  added: CityBusStopRef[];
  removed: CityBusStopRef[];
  renamed: (CityBusStopRef & { before: string })[];
  moved: (CityBusStopRef & { meters: number })[];
  reordered: boolean;
  /** 교체할 때 그대로 올리는 공공데이터 응답 원문 */
  fetched: object;
};

/** 아산·천안 BIS 홈페이지에서 받아온 평일 시간표. 비교용이라 저장되지 않는다. */
export type CityBusBisTimetable = {
  source: "asan" | "cheonan";
  source_url: string;
  times: string[];
  fetched_at: string;
};
