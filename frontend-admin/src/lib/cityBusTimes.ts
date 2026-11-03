import type { CityBusRoute, CityBusTimetableFile } from "./cityBusTypes";

const TIME_IN_TEXT = /(\d{1,2}):(\d{2})/g;

/** 붙여넣은 글에서 시각만 뽑아 HH:MM으로 맞춘다. 엑셀·PDF·줄바꿈·쉼표 구분 모두 받는다. */
export function extractTimes(text: string): string[] {
  return Array.from(text.matchAll(TIME_IN_TEXT), (match) => `${match[1].padStart(2, "0")}:${match[2]}`);
}

export type TimesCheck = {
  times: string[];
  invalid: string[];
  duplicates: string[];
};

export function checkTimes(text: string): TimesCheck {
  const raw = extractTimes(text);
  const invalid = raw.filter((value) => {
    const [hour, minute] = value.split(":").map(Number);
    return hour > 23 || minute > 59;
  });
  const duplicates = Array.from(new Set(raw.filter((value, index) => raw.indexOf(value) !== index)));
  const times = Array.from(new Set(raw.filter((value) => !invalid.includes(value)))).sort();
  return { times, invalid, duplicates };
}

export type TimesDiff = {
  /** incoming에만 있는 시각 */
  added: string[];
  /** current에만 있는 시각 */
  removed: string[];
};

export function diffTimes(current: string[], incoming: string[]): TimesDiff {
  return {
    added: incoming.filter((time) => !current.includes(time)),
    removed: current.filter((time) => !incoming.includes(time)),
  };
}

export type RouteDiff = {
  added: string[];
  removed: string[];
  infoChanged: boolean;
  /** 게시본에 없던 노선 */
  isNew: boolean;
};

export function diffRoute(route: CityBusRoute, published: CityBusTimetableFile | null): RouteDiff {
  const entry = published?.[route.route_key];
  const hasTimetable = Boolean(route.origin || route.terminus || route.times.length);
  if (!entry || typeof entry === "string") {
    return { added: route.times, removed: [], infoChanged: false, isNew: hasTimetable };
  }
  return {
    ...diffTimes(entry.시간표, route.times),
    infoChanged: entry.출발지 !== route.origin || entry.종점 !== route.terminus,
    isNew: false,
  };
}

export function hasRouteChanges(diff: RouteDiff) {
  return diff.isNew || diff.infoChanged || diff.added.length > 0 || diff.removed.length > 0;
}

/** 게시본에는 있는데 초안에서 지운 노선 */
export function removedRouteKeys(routes: CityBusRoute[], published: CityBusTimetableFile | null) {
  if (!published) return [];
  const keys = new Set(routes.filter((route) => route.origin || route.terminus || route.times.length).map((route) => route.route_key));
  return Object.keys(published).filter((key) => key !== "version" && !keys.has(key));
}

export function formatDateTime(value: string | null) {
  return value ? new Date(value).toLocaleString("ko-KR") : "-";
}
