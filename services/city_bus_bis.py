"""대시보드에서 노선 하나씩 비교할 때 부르는 외부 출처(BIS·공공데이터) 조회.

시간표: 공공데이터포털에는 출발시각 목록을 주는 API가 없어서(TAGO는 첫차·막차·배차간격뿐)
각 시 BIS 홈페이지가 쓰는 엔드포인트를 그대로 부른다. 공식 API가 아니라 사이트가
바뀌면 깨질 수 있다.
- 아산: POST /mobile/traffic/searchBusTimeList → JSON busTimeList[]
- 천안: GET /bis/showBusTimeTable.do → HTML의 "평일 출발시간" 목록
앱 시간표는 노선마다 목록이 하나라서 평일 시간표만 읽는다.

정류장: TAGO 노선별 경유정류소 목록 API 응답 원문이 노선도의 정류장 JSON이다.
"""

from __future__ import annotations

import math
import os
import re
from dataclasses import dataclass, field
from typing import Any, Mapping
from urllib.parse import urlencode

import httpx

from services.city_bus_data import CityBusDataError, normalize_times, stop_items, validate_stops_json


ASAN_TIME_LIST_URL = "https://bus.asan.go.kr/mobile/traffic/searchBusTimeList"
ASAN_PAGE_URL = "https://bus.asan.go.kr/web/bus_timetable_pop"
CHEONAN_TIMETABLE_URL = "https://its.cheonan.go.kr/bis/showBusTimeTable.do"
CHEONAN_AREA_CODE = "285"

SOURCE_ASAN = "asan"
SOURCE_CHEONAN = "cheonan"

REQUEST_TIMEOUT_SECONDS = 10.0
ASAN_WEEKDAY = "1"
# 천안은 상행(_UP)이 2, 하행(_DOWN)이 1이다.
CHEONAN_DIRECTIONS = {"UP": "2", "DOWN": "1"}

_CHEONAN_WEEKDAY_BLOCK = re.compile(r"<dt>\s*평일 출발시간\s*</dt>(.*?)</dl>", re.S)
_CHEONAN_TIME = re.compile(r"<dd>\s*(\d{1,2}:\d{2})\s*</dd>")


class CityBusBisError(RuntimeError):
    """BIS 응답을 받지 못했거나 읽지 못했을 때. 라우터에서 502로 바꾼다."""


@dataclass(frozen=True)
class BisSource:
    source: str
    # 아산은 BIS 노선 ID(숫자), 천안은 노선 번호
    route_id: str
    direction: str | None = None

    @property
    def page_url(self) -> str:
        """사람이 열어 볼 BIS 시간표 페이지."""
        if self.source == SOURCE_ASAN:
            return f"{ASAN_PAGE_URL}?{urlencode({'auto_route_id': self.route_id})}"
        return f"{CHEONAN_TIMETABLE_URL}?{urlencode(cheonan_params(self.route_id, self.direction or ''))}"


@dataclass(frozen=True)
class BisTimetable:
    source: str
    source_url: str
    times: list[str]


def resolve_bis_source(route_key: str, routes: Mapping[str, str]) -> BisSource | None:
    """노선 키를 BIS 조회 정보로 바꾼다. routes는 routers/bus.py의 ROUTES(실시간 위치용 노선 ID)."""
    route_id = routes.get(route_key)
    if not route_id:
        return None
    if route_id.startswith("CAB"):
        name, _, direction = route_key.rpartition("_")
        if not name or direction not in CHEONAN_DIRECTIONS:
            return None
        return BisSource(SOURCE_CHEONAN, name, CHEONAN_DIRECTIONS[direction])
    if route_id.startswith("ASB"):
        return BisSource(SOURCE_ASAN, route_id[len("ASB"):])
    return None


def cheonan_params(route_name: str, direction: str) -> dict[str, str]:
    # 나머지 파라미터는 빈 값이라도 모두 보내야 한다. 빠지면 404 페이지가 온다.
    return {
        "routeName": route_name,
        "routeDirection": direction,
        "relayAreacode": CHEONAN_AREA_CODE,
        "routeExplain": "",
        "stName": "",
        "edName": "",
        "fstTime": "",
        "lstTime": "",
        "routeDLength": "",
        "avgTime": "",
    }


def _format_hhmm(value: str) -> str:
    # 아산은 "0840", "715"처럼 콜론 없이 준다.
    digits = re.sub(r"\D", "", value)
    if len(digits) not in (3, 4):
        raise CityBusBisError(f"BIS 응답의 시각을 읽지 못했습니다: {value!r}")
    return f"{digits[:-2].zfill(2)}:{digits[-2:]}"


def parse_asan_times(data: Any) -> list[str]:
    items = data.get("busTimeList") if isinstance(data, dict) else None
    if not isinstance(items, list):
        raise CityBusBisError("BIS 응답을 읽지 못했습니다: busTimeList가 없습니다.")
    times = []
    for item in items:
        if not isinstance(item, dict) or item.get("week_operation_flag") != "1":
            continue
        # 한 노선 ID에 양방향이 같이 있는 노선은 상행만 쓴다.
        if item.get("turn_useflag") == "1" and item.get("updn_line") != "1":
            continue
        times.append(_format_hhmm(str(item.get("departure_time", ""))))
    return times


def parse_cheonan_times(html: str) -> list[str]:
    block = _CHEONAN_WEEKDAY_BLOCK.search(html)
    if block is None:
        raise CityBusBisError("BIS 응답을 읽지 못했습니다: 평일 출발시간 목록이 없습니다.")
    return _CHEONAN_TIME.findall(block.group(1))


def _finish(times: list[str]) -> list[str]:
    if not times:
        raise CityBusBisError("BIS에 평일 시간표가 없습니다.")
    try:
        # BIS가 같은 시각을 두 번 주는 경우가 있어 중복은 합친다.
        return normalize_times(list(dict.fromkeys(times)))
    except CityBusDataError as exc:
        raise CityBusBisError(f"BIS 응답을 읽지 못했습니다: {exc}") from exc


def fetch_bis_timetable(source: BisSource) -> BisTimetable:
    try:
        if source.source == SOURCE_ASAN:
            response = httpx.post(
                ASAN_TIME_LIST_URL,
                data={"busRouteId": source.route_id, "weekcd": ASAN_WEEKDAY},
                timeout=REQUEST_TIMEOUT_SECONDS,
            )
            response.raise_for_status()
            times = parse_asan_times(response.json())
        else:
            response = httpx.get(
                CHEONAN_TIMETABLE_URL,
                params=cheonan_params(source.route_id, source.direction or ""),
                timeout=REQUEST_TIMEOUT_SECONDS,
            )
            response.raise_for_status()
            times = parse_cheonan_times(response.text)
    except httpx.HTTPError as exc:
        raise CityBusBisError(f"BIS에 연결하지 못했습니다: {exc}") from exc
    except ValueError as exc:
        raise CityBusBisError(f"BIS 응답을 읽지 못했습니다: {exc}") from exc
    return BisTimetable(source=source.source, source_url=source.page_url, times=_finish(times))


# ---------------------------------------------------------------------------
# 정류장 (TAGO 노선별 경유정류소 목록)
# ---------------------------------------------------------------------------

TAGO_ROUTE_STOPS_URL = "http://apis.data.go.kr/1613000/BusRouteInfoInqireService/getRouteAcctoThrghSttnList"
ASAN_CITY_CODE = "34040"
CHEONAN_CITY_CODE = "34010"
TAGO_NUM_OF_ROWS = 200
# 좌표가 이보다 많이 바뀌면 위치 이동으로 본다. 그 아래는 측위 오차 수준이다.
STOP_MOVE_THRESHOLD_METERS = 30.0


@dataclass(frozen=True)
class StopsDiff:
    current_count: int
    fetched_count: int
    added: list[dict[str, Any]] = field(default_factory=list)
    removed: list[dict[str, Any]] = field(default_factory=list)
    renamed: list[dict[str, Any]] = field(default_factory=list)
    moved: list[dict[str, Any]] = field(default_factory=list)
    reordered: bool = False


def resolve_stops_route_id(stops_json: dict[str, Any] | None, route_key: str, routes: Mapping[str, str]) -> tuple[str, str] | None:
    """(TAGO 노선 ID, 도시코드). 저장된 정류장 JSON의 routeid를 먼저 쓰고, 없으면 ROUTES를 쓴다."""
    route_id = next((str(item["routeid"]) for item in stop_items(stops_json) if item.get("routeid")), None)
    route_id = route_id or routes.get(route_key)
    if not route_id:
        return None
    # routers/bus.py build_api_url과 같은 규칙: 천안 노선만 34010
    return route_id, CHEONAN_CITY_CODE if route_id.startswith("CAB") else ASAN_CITY_CODE


def fetch_route_stops(route_id: str, city_code: str) -> dict[str, Any]:
    api_key = os.getenv("API_KEY")
    if not api_key:
        raise CityBusBisError("API_KEY가 설정되지 않았습니다.")
    # .env의 키는 URL 인코딩된 값이라 params로 넘기면 다시 인코딩돼 403이 난다. routers/bus.py와 같이 URL에 그대로 넣는다.
    query = urlencode({"cityCode": city_code, "routeId": route_id, "numOfRows": TAGO_NUM_OF_ROWS, "pageNo": 1, "_type": "json"})
    try:
        response = httpx.get(f"{TAGO_ROUTE_STOPS_URL}?serviceKey={api_key}&{query}", timeout=REQUEST_TIMEOUT_SECONDS)
        response.raise_for_status()
        data = response.json()
    except httpx.HTTPError as exc:
        raise CityBusBisError(f"공공데이터 API에 연결하지 못했습니다: {exc}") from exc
    except ValueError as exc:
        raise CityBusBisError(f"공공데이터 응답을 읽지 못했습니다: {exc}") from exc

    try:
        header = data["response"]["header"]
        body = data["response"]["body"]
    except (KeyError, TypeError):
        raise CityBusBisError("공공데이터 응답을 읽지 못했습니다: response가 없습니다.") from None
    if str(header.get("resultCode")) != "00":
        raise CityBusBisError(f"공공데이터 API 오류: {header.get('resultMsg') or header.get('resultCode')}")
    try:
        validate_stops_json(data)
    except CityBusDataError as exc:
        raise CityBusBisError(f"공공데이터 응답을 읽지 못했습니다: {exc}") from exc
    total = int(body.get("totalCount") or 0)
    if total > len(stop_items(data)):
        raise CityBusBisError(f"정류장이 {total}개라 한 번에 다 받지 못했습니다.")
    return data


def _stop_ref(item: dict[str, Any]) -> dict[str, Any]:
    return {"nodeid": str(item.get("nodeid", "")), "nodeord": item.get("nodeord"), "nodenm": str(item.get("nodenm", ""))}


def _distance_meters(a: dict[str, Any], b: dict[str, Any]) -> float | None:
    try:
        lat1, lng1 = math.radians(float(a["gpslati"])), math.radians(float(a["gpslong"]))
        lat2, lng2 = math.radians(float(b["gpslati"])), math.radians(float(b["gpslong"]))
    except (KeyError, TypeError, ValueError):
        return None
    h = math.sin((lat2 - lat1) / 2) ** 2 + math.cos(lat1) * math.cos(lat2) * math.sin((lng2 - lng1) / 2) ** 2
    return 2 * 6_371_000 * math.asin(math.sqrt(h))


def diff_stops(current: dict[str, Any] | None, fetched: dict[str, Any]) -> StopsDiff:
    """정류장 ID(nodeid) 기준 비교. 이름·좌표가 바뀐 같은 정류장은 추가·삭제가 아니라 변경으로 본다."""
    old_items = stop_items(current)
    new_items = stop_items(fetched)
    old_by_id = {str(item.get("nodeid")): item for item in old_items}
    new_by_id = {str(item.get("nodeid")): item for item in new_items}

    renamed, moved = [], []
    for node_id, new in new_by_id.items():
        old = old_by_id.get(node_id)
        if old is None:
            continue
        if old.get("nodenm") != new.get("nodenm"):
            renamed.append({**_stop_ref(new), "before": str(old.get("nodenm", ""))})
        distance = _distance_meters(old, new)
        if distance is not None and distance > STOP_MOVE_THRESHOLD_METERS:
            moved.append({**_stop_ref(new), "meters": round(distance)})

    common_old = [node_id for node_id in old_by_id if node_id in new_by_id]
    common_new = [node_id for node_id in new_by_id if node_id in old_by_id]
    return StopsDiff(
        current_count=len(old_items),
        fetched_count=len(new_items),
        added=[_stop_ref(item) for node_id, item in new_by_id.items() if node_id not in old_by_id],
        removed=[_stop_ref(item) for node_id, item in old_by_id.items() if node_id not in new_by_id],
        renamed=renamed,
        moved=moved,
        reordered=common_old != common_new,
    )
