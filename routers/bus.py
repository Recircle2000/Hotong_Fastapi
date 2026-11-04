from fastapi import APIRouter, WebSocket, WebSocketDisconnect, HTTPException, Depends, Request, Response
from fastapi.responses import JSONResponse
import asyncio
from typing import List, Dict, Set, Optional, Tuple
from dataclasses import dataclass, field
import httpx
import os
import json
from dotenv import load_dotenv
import redis
from utils.redis_client import REDIS_ENABLED, set_cache, get_cache, delete_cache, delete_pattern
from utils.security import get_current_admin
from database import SessionLocal
from services.city_bus_data import (
    KIND_TIMETABLE,
    check_effective_timetable,
    get_effective_release,
    release_generation,
)
from datetime import datetime, timedelta, time, timezone
import logging
import time as time_module

router = APIRouter()

load_dotenv()
API_KEY = os.getenv("API_KEY")
CITY_CODE = "34040"
BASE_URL = "http://apis.data.go.kr/1613000/BusLcInfoInqireService/getRouteAcctoBusLcList"

# 버스 노선 ID
ROUTES = {
    # 순환5번
    "순환5_DOWN": "ASB288000141",  # 호서대학교 출발 (하행)
    "순환5_UP": "ASB288000286",  # 천안아산역 출발 (상행)

    # "900_UP":"ASB285000245", #900번 상행 개발용
    # "900_DOWN":"ASB285000244",#900번 하행

    # 810번
    "810_DOWN": "ASB288000276",  # 호서대학교 출발 (하행)
    "810_UP": "ASB288000091",  # 시외버스터미널 출발 (상행)

    # 820번
    "820_DOWN": "ASB288000277",  # 호서대학교 출발 (하행)
    "820_UP": "ASB288000092",  # 시외버스터미널 출발 (상행)

    # 821번
    "821_DOWN": "ASB288000333",  # 호서대학교 출발 (하행)
    "821_UP": "ASB288000332",  # 시외버스터미널 출발 (상행)

    # 822번
    "822_DOWN": "ASB288000362",  # 호서대학교 출발 (하행)
    "822_UP": "ASB288000361",  # 시외버스터미널 출발 (상행)

    # 1000번
    "1000_DOWN": "ASB288001028",  # 호서대학교 출발 (하행)
    "1000_UP": "ASB288001027",  # 탕정역 출발 (상행)

    # 1001번
    # "1001_UP": "ASB288000358",  # 포스코 아파트 출발 (상행)
    # 기타 노선은 주석 처리되어 있음

    # 24번
    "24_UP": "CAB285000025",  # 동우아파트 출발 (상행)
    "24_DOWN": "CAB285000024",  # 각원사 회차지 출발 (하행)

    # 81번
    "81_UP": "CAB285000294",  # 차암2통 출발 (상행)
    "81_DOWN": "CAB285000293",  # 각원사 회차지 출발 (하행)
}

CHEONAN_ROUTE_NAMES = {"24_UP", "24_DOWN", "81_UP", "81_DOWN"}
WS_ROUTE_GROUPS: Dict[str, Tuple[str, ...]] = {
    "all": tuple(ROUTES.keys()),
    "asan_down": tuple(
        route_name for route_name in ROUTES
        if route_name not in CHEONAN_ROUTE_NAMES and route_name.endswith("_DOWN")
    ),
    "asan_up": tuple(
        route_name for route_name in ROUTES
        if route_name not in CHEONAN_ROUTE_NAMES and route_name.endswith("_UP")
    ),
    "cheonan_down": tuple(
        route_name for route_name in ROUTES
        if route_name in CHEONAN_ROUTE_NAMES and route_name.endswith("_DOWN")
    ),
    "cheonan_up": tuple(
        route_name for route_name in ROUTES
        if route_name in CHEONAN_ROUTE_NAMES and route_name.endswith("_UP")
    ),
}

# 주요 노선 (항상 체크)
MAIN_ROUTES = ["순환5_DOWN", "순환5_UP", "24_UP", "24_DOWN", "81_UP", "81_DOWN", "1000_DOWN", "1000_UP"]

# 시간표 기반 체크 노선
SCHEDULED_ROUTES = ["810_DOWN", "810_UP", "820_DOWN", "820_UP", "821_DOWN", "821_UP", "822_DOWN", "822_UP"]

# 버스 데이터 캐시 TTL (초)
BUS_CACHE_TTL = 5

# 외부 API가 잠깐 비거나 실패해도 마지막으로 확인된 위치를 유지하는 시간 (초).
# 이 시간 동안 새 위치를 한 번도 못 받으면 운행 없음으로 본다.
# 보는 사람이 없을 때 주기(30초) 두 번 + 타임아웃 여유보다 길어야 평소에도 위치가 끊기지 않는다.
BUS_HOLD_SECONDS = 75
BUS_LAST_GOOD_PREFIX = "bus:last_good:"

# 백그라운드 갱신 주기 (초). 보는 사람(웹소켓 연결, 최근 /buses 요청)이 있으면 짧게 돈다.
BUS_IDLE_INTERVAL = 30
BUS_ACTIVE_INTERVAL = 5
# 마지막 /buses 요청 뒤 이 시간 동안은 보는 사람이 있다고 본다 (초).
BUS_HTTP_DEMAND_SECONDS = 30
# 시간표는 게시·예약 적용 때만 바뀌므로 평소에는 DB를 읽지 않는다.
# 서버 밖(가져오기 도구, 직접 SQL)에서 바꾼 경우에 대비해 이 간격으로만 버전을 확인한다 (초).
BUS_TIMETABLE_RECHECK_SECONDS = 3600
# DB를 못 읽었을 때 다시 시도하는 간격 (초)
BUS_TIMETABLE_RETRY_SECONDS = 60

# 외부 API는 매분 초반에 2~5초씩 늦어질 때가 있어 기본값(5초)보다 넉넉히 기다린다.
BUS_API_TIMEOUT = httpx.Timeout(8.0, connect=3.0)

# 주요 노선 운행 시간
MAIN_ROUTES_START_TIME = time(6, 5)  # 오전 6시 15분
MAIN_ROUTES_END_TIME = time(23, 50)  # 오후 10시 15분

# 웹소켓 연결 관리
active_connections: Set[WebSocket] = set()
filtered_connections: Dict[str, Set[WebSocket]] = {
    group_name: set() for group_name in WS_ROUTE_GROUPS if group_name != "all"
}
# 쉬는 중인 백그라운드 루프를 바로 한 바퀴 돌리고 싶을 때 세운다.
bus_loop_wake = asyncio.Event()
# 루프가 지금 기다리는 주기. 이미 짧은 주기로 돌고 있으면 깨우지 않는다.
bus_loop_interval: float = BUS_IDLE_INTERVAL
# 마지막 /buses 요청 시각 (monotonic)
last_http_demand_at: Optional[float] = None
# 노선별로 외부 API 조회를 마지막으로 끝낸 시각 (monotonic). 성공·빈 응답·오류 모두 포함.
route_checked_at: Dict[str, float] = {}

# 시간표 데이터 저장
bus_timetable: Dict[str, dict] = {}
# 파싱된 시간표 캐시 (문자열 파싱 비용 절감)
parsed_bus_timetable: Dict[str, List[Tuple[int, int]]] = {}
# 마지막으로 읽어 들인 시간표 버전 (바뀌었을 때만 다시 파싱)
loaded_timetable_version: Optional[str] = None
# 시간표를 다시 확인할 시점: 다음 정기 확인 (monotonic), 마지막으로 반영한 게시 횟수, 다음 예약 적용 시각 (UTC)
timetable_next_check_at: Optional[float] = None
timetable_seen_generation: Optional[int] = None
timetable_next_effective_at: Optional[datetime] = None
# 대시보드 게시본이 아직 없을 때 쓰는 예전 시간표 파일
TIMETABLE_FILE_PATH = 'bus_times.json'
# 재사용 HTTP 클라이언트
bus_http_client: Optional[httpx.AsyncClient] = None
route_fetch_tasks: Dict[str, asyncio.Task] = {}
latest_bus_data: Dict[str, List[dict]] = {}
# Redis를 쓰지 않을 때의 마지막 확인 위치: 노선 -> (받은 시각, 버스 목록)
last_good_bus_data: Dict[str, Tuple[float, List[dict]]] = {}


def remember_last_good_bus_data(route_name: str, items: List[dict]) -> None:
    if REDIS_ENABLED:
        set_cache(BUS_LAST_GOOD_PREFIX + route_name, items, BUS_HOLD_SECONDS)
    else:
        last_good_bus_data[route_name] = (time_module.monotonic(), items)


def forget_last_good_bus_data(route_name: str) -> None:
    if REDIS_ENABLED:
        delete_cache(BUS_LAST_GOOD_PREFIX + route_name)
    else:
        last_good_bus_data.pop(route_name, None)


def get_last_good_bus_data(route_name: str) -> Optional[List[dict]]:
    if REDIS_ENABLED:
        return get_cache(BUS_LAST_GOOD_PREFIX + route_name)
    held = last_good_bus_data.get(route_name)
    if held is None:
        return None
    received_at, items = held
    if time_module.monotonic() - received_at > BUS_HOLD_SECONDS:
        last_good_bus_data.pop(route_name, None)
        return None
    return items


def get_latest_bus_data(route_name: str) -> Optional[List[dict]]:
    """화면에 내보낼 버스 위치. 방금 받은 값이 없으면 유지 중인 마지막 위치를 쓴다.

    웹소켓과 /buses 계열 엔드포인트가 모두 이 함수로 읽는다.
    """
    fresh = get_cache(route_name) if REDIS_ENABLED else latest_bus_data.get(route_name)
    return fresh if fresh else get_last_good_bus_data(route_name)

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)
logging.getLogger("httpx").setLevel(logging.WARNING)
logging.getLogger("httpcore").setLevel(logging.WARNING)
LOG_ROUTE_LIST_LIMIT = 6


@dataclass
class BusSyncLogContext:
    group: str
    started_at: float = field(default_factory=time_module.perf_counter)
    requested: Set[str] = field(default_factory=set)
    cache_hit: Set[str] = field(default_factory=set)
    dedup_reuse: Set[str] = field(default_factory=set)
    external_request: Set[str] = field(default_factory=set)
    external_success: Set[str] = field(default_factory=set)
    external_empty: Set[str] = field(default_factory=set)
    skipped: Set[str] = field(default_factory=set)
    failed: Set[str] = field(default_factory=set)


def get_ordered_route_names(route_names: Set[str]) -> List[str]:
    return [route_name for route_name in ROUTES if route_name in route_names]


def format_route_summary(route_names: Set[str]) -> str:
    ordered_routes = get_ordered_route_names(route_names)
    displayed_routes = ordered_routes[:LOG_ROUTE_LIST_LIMIT]
    remaining_count = len(ordered_routes) - len(displayed_routes)
    route_text = ",".join(displayed_routes)

    if remaining_count > 0:
        route_text = f"{route_text},+{remaining_count}" if route_text else f"+{remaining_count}"

    return f"{len(ordered_routes)}[{route_text}]"


def format_failure_summary(route_names: Set[str]) -> str:
    if not route_names:
        return "0"
    return format_route_summary(route_names)


def log_bus_sync_summary(log_context: BusSyncLogContext):
    log_context.failed.update(
        log_context.external_request - log_context.external_success - log_context.external_empty
    )

    duration_ms = int((time_module.perf_counter() - log_context.started_at) * 1000)
    message = (
        f"[BUS_WS][sync] group={log_context.group} "
        f"requested={format_route_summary(log_context.requested)} "
        f"cache_hit={format_route_summary(log_context.cache_hit)} "
        f"dedup_reuse={format_route_summary(log_context.dedup_reuse)} "
        f"external_request={format_route_summary(log_context.external_request)} "
        f"external_success={format_route_summary(log_context.external_success)} "
        f"failed={format_failure_summary(log_context.failed)} "
        f"duration={duration_ms}ms"
    )

    if log_context.external_empty:
        message += f" external_empty={format_route_summary(log_context.external_empty)}"
    if log_context.skipped:
        message += f" skipped={format_route_summary(log_context.skipped)}"

    logger.info(message)


def get_active_ws_group_name() -> str:
    if active_connections:
        return "all"

    active_groups = [
        group_name
        for group_name, connections in filtered_connections.items()
        if connections
    ]

    if len(active_groups) == 1:
        return active_groups[0]
    if len(active_groups) > 1:
        return "mixed"
    return "none"


def get_total_active_connections() -> int:
    return len(active_connections) + sum(len(connections) for connections in filtered_connections.values())


def build_bus_message(route_names: Optional[Tuple[str, ...]] = None) -> str:
    result = {}
    target_routes = route_names or WS_ROUTE_GROUPS["all"]

    for route_name in target_routes:
        cached_data = get_latest_bus_data(route_name)
        if cached_data:
            filtered_data = []
            for bus in cached_data:
                filtered_bus = {k: v for k, v in bus.items() if k not in ["nodeid", "routetp"]}
                filtered_data.append(filtered_bus)
            result[route_name] = filtered_data

    return json.dumps(result)


def select_loop_interval(ws_connections: int, last_demand_at: Optional[float], now: float) -> int:
    """보는 사람이 있으면 짧은 주기, 없으면 긴 주기."""
    if ws_connections > 0:
        return BUS_ACTIVE_INTERVAL
    if last_demand_at is not None and now - last_demand_at <= BUS_HTTP_DEMAND_SECONDS:
        return BUS_ACTIVE_INTERVAL
    return BUS_IDLE_INTERVAL


def current_loop_interval() -> int:
    return select_loop_interval(get_total_active_connections(), last_http_demand_at, time_module.monotonic())


def wake_bus_loop() -> None:
    """긴 주기로 쉬고 있는 루프를 바로 돌린다. 이미 짧은 주기면 다음 바퀴를 기다린다."""
    if bus_loop_interval > BUS_ACTIVE_INTERVAL:
        bus_loop_wake.set()


def record_http_demand() -> None:
    global last_http_demand_at
    last_http_demand_at = time_module.monotonic()
    wake_bus_loop()


def route_recently_checked(route_name: str) -> bool:
    checked_at = route_checked_at.get(route_name)
    return checked_at is not None and time_module.monotonic() - checked_at <= BUS_HOLD_SECONDS


async def ensure_unchecked_route_data(route_names: Tuple[str, ...]) -> None:
    """캐시에 값이 없고 최근에 조회한 적도 없는 운행 노선만 바로 받아 온다.

    서버가 막 시작해 루프가 아직 한 바퀴도 못 돈 경우처럼 드문 상황에만 외부 API를 기다린다.
    """
    missing = tuple(
        route_name for route_name in route_names
        if get_latest_bus_data(route_name) is None
        and not route_recently_checked(route_name)
        and should_check_route(route_name)
    )
    if missing:
        await ensure_route_data(missing)


async def fetch_bus_data_deduplicated(
        route_name: str,
        route_id: str,
        route_should_check: Optional[bool] = None,
        use_cache: bool = True,
        log_context: Optional[BusSyncLogContext] = None,
) -> Optional[List[dict]]:
    if route_should_check is None:
        route_should_check = should_check_route(route_name)

    if not route_should_check:
        delete_cache(route_name)
        forget_last_good_bus_data(route_name)
        if not REDIS_ENABLED:
            latest_bus_data.pop(route_name, None)
        if log_context:
            log_context.skipped.add(route_name)
        return None

    if use_cache and REDIS_ENABLED:
        cached_data = get_cache(route_name)
        if cached_data is not None:
            if log_context:
                log_context.cache_hit.add(route_name)
            return cached_data

    existing_task = route_fetch_tasks.get(route_name)
    if existing_task and not existing_task.done():
        if log_context:
            log_context.dedup_reuse.add(route_name)
        return await existing_task

    if log_context:
        log_context.external_request.add(route_name)

    task = asyncio.create_task(
        fetch_bus_data(
            route_name,
            route_id,
            route_should_check=route_should_check,
            log_context=log_context,
        )
    )
    route_fetch_tasks[route_name] = task

    try:
        return await task
    finally:
        if route_fetch_tasks.get(route_name) is task:
            route_fetch_tasks.pop(route_name, None)


async def ensure_route_data(
        route_names: Tuple[str, ...],
        use_cache: bool = True,
        log_context: Optional[BusSyncLogContext] = None,
):
    tasks = []

    if log_context:
        log_context.requested.update(route_names)

    for route_name in route_names:
        route_should_check = should_check_route(route_name)
        if log_context and not route_should_check:
            log_context.skipped.add(route_name)
        tasks.append(
            fetch_bus_data_deduplicated(
                route_name,
                ROUTES[route_name],
                route_should_check=route_should_check,
                use_cache=use_cache,
                log_context=log_context,
            )
        )

    if tasks:
        await asyncio.gather(*tasks)

    if log_context:
        log_bus_sync_summary(log_context)


def read_current_timetable() -> Optional[dict]:
    """대시보드에서 게시한 시간표를 우선 쓰고, 아직 없으면 예전 bus_times.json을 쓴다."""
    with SessionLocal() as db:
        release = get_effective_release(db, KIND_TIMETABLE)
    if release is not None and release.payload:
        return release.payload
    try:
        with open(TIMETABLE_FILE_PATH, 'r', encoding='utf-8') as f:
            return json.load(f)
    except FileNotFoundError:
        return None


def apply_bus_timetable(data: dict, version: str) -> None:
    global loaded_timetable_version
    bus_timetable.clear()
    bus_timetable.update(data)
    parsed_bus_timetable.clear()
    for route_name in SCHEDULED_ROUTES:
        if route_name not in bus_timetable:
            continue
        timetable = bus_timetable[route_name].get("시간표", [])
        parsed_times: List[Tuple[int, int]] = []
        for departure_time in timetable:
            try:
                departure_hour, departure_minute = map(int, departure_time.split(":"))
                parsed_times.append((departure_hour, departure_minute))
            except Exception:
                continue
        parsed_bus_timetable[route_name] = parsed_times
    loaded_timetable_version = version
    logging.info(f"버스 시간표를 불러왔습니다: {version}")


def load_timetable_file() -> None:
    try:
        with open(TIMETABLE_FILE_PATH, 'r', encoding='utf-8') as f:
            data = json.load(f)
    except FileNotFoundError:
        logging.warning("시간표 데이터가 없습니다")
        return
    version = str(data.get("version"))
    if version != loaded_timetable_version or not bus_timetable:
        apply_bus_timetable(data, version)


def load_bus_timetable() -> bool:
    """적용 중인 시간표 버전을 확인하고, 바뀌었을 때만 내용을 받아 반영한다. DB를 읽었으면 True."""
    global timetable_next_effective_at
    try:
        with SessionLocal() as db:
            check = check_effective_timetable(db, loaded_timetable_version if bus_timetable else None)
    except Exception as e:
        logging.error(f"시간표 확인 오류: {e}")
        timetable_next_effective_at = None
        if not bus_timetable:
            # 배포 순서가 어긋나 테이블이 아직 없는 경우 등. 예전 파일이라도 쓴다.
            load_timetable_file()
        return False

    timetable_next_effective_at = check.next_effective_at
    try:
        if check.version is None:
            load_timetable_file()
        elif check.payload is not None:
            apply_bus_timetable(check.payload, check.version)
    except Exception as e:
        logging.error(f"시간표 로딩 오류: {e}")
    return True


def timetable_reload_due(now_monotonic: float, now_utc: datetime, generation: int) -> bool:
    """처음, 대시보드에서 게시했을 때, 예약 게시가 적용될 때, 정기 확인 때만 DB를 읽는다."""
    if timetable_next_check_at is None or now_monotonic >= timetable_next_check_at:
        return True
    if generation != timetable_seen_generation:
        return True
    return timetable_next_effective_at is not None and now_utc >= timetable_next_effective_at


async def refresh_timetable_if_due() -> None:
    global timetable_next_check_at, timetable_seen_generation
    now = time_module.monotonic()
    # 읽는 도중 게시가 일어나도 놓치지 않도록 읽기 전에 게시 횟수를 잡아 둔다.
    generation = release_generation()
    if not timetable_reload_due(now, datetime.now(timezone.utc), generation):
        return
    ok = await asyncio.to_thread(load_bus_timetable)
    timetable_seen_generation = generation
    timetable_next_check_at = now + (BUS_TIMETABLE_RECHECK_SECONDS if ok else BUS_TIMETABLE_RETRY_SECONDS)


def build_api_url(route_id, route_name=None):
    # 24번, 81번 노선은 CITY_CODE를 34010으로 사용
    if route_name in ["24_UP", "24_DOWN", "81_UP", "81_DOWN"]:
        city_code = "34010"
    else:
        city_code = CITY_CODE
    return f"{BASE_URL}?serviceKey={API_KEY}&cityCode={city_code}&routeId={route_id}&_type=json"


def should_check_route(route_name):
    now = datetime.now().time()
    # 주요 노선(순환5번, 1000번)은 운행 시간 내에만 체크
    if route_name in MAIN_ROUTES:
        is_check = MAIN_ROUTES_START_TIME <= now <= MAIN_ROUTES_END_TIME
        if not is_check:
            logging.debug(f"[{route_name}] 주요 노선 운행 시간 외: {now} (운행시간: {MAIN_ROUTES_START_TIME}-{MAIN_ROUTES_END_TIME})")
        return is_check

    # 시간표 기반 노선들
    if route_name in SCHEDULED_ROUTES and route_name in parsed_bus_timetable:
        # 시간표 확인
        timetable = parsed_bus_timetable[route_name]

        # 현재 시간
        current_datetime = datetime.now()

        # 노선의 운행 여부 확인
        for departure_hour, departure_minute in timetable:
            # 파싱 캐시된 출발 시간을 datetime 객체로 변환
            try:
                departure_datetime = current_datetime.replace(hour=departure_hour, minute=departure_minute, second=0,
                                                              microsecond=0)

                # 날짜가 바뀐 경우 처리 (현재 새벽, 출발 시간은 저녁인 경우 전날로 설정)
                if current_datetime.hour < 4 and departure_hour > 20:
                    departure_datetime = departure_datetime - timedelta(days=1)
                # 날짜가 바뀐 경우 처리 (현재 저녁, 출발 시간은 새벽인 경우 다음날로 설정)
                elif current_datetime.hour > 20 and departure_hour < 4:
                    departure_datetime = departure_datetime + timedelta(days=1)

                # 현재 시간과 출발 시간의 차이 (분)
                # 여기서 양수는 "출발까지 남은 시간", 음수는 "출발 후 경과 시간"
                time_diff_minutes = (departure_datetime - current_datetime).total_seconds() / 60

                # 출발 1분 전부터 출발 후 60분(1시간)까지만 체크
                # 출발 1분 전 조건: 0 <= time_diff_minutes <= 1 (양수)
                # 출발 후 60분 이내 조건: -60 <= time_diff_minutes < 0 (음수)
                if (-60 <= time_diff_minutes and time_diff_minutes < 0) or (
                        0 <= time_diff_minutes and time_diff_minutes <= 1):
                    # 시간 표시 메시지 작성
                    if time_diff_minutes >= 0:
                        status_msg = f"출발까지 {int(time_diff_minutes)}분 남음"
                    else:
                        status_msg = f"출발 후 {int(abs(time_diff_minutes))}분 경과"

                    # print(f"[{route_name}] 🚍 운행 중: 출발 시간 {departure_time} ({status_msg})")
                    return True
            except Exception as e:
                # print(f"[{route_name}] ⚠️ 시간 계산 오류: {e} (출발시간: {departure_time})")
                continue
        return False

    # 기본적으로 체크하지 않음
    if route_name in SCHEDULED_ROUTES and route_name not in bus_timetable:
        logging.warning(f"[{route_name}] ⚠️ 시간표 정보 없음")
    return False


async def fetch_bus_data(
        route_name,
        route_id,
        route_should_check: Optional[bool] = None,
        log_context: Optional[BusSyncLogContext] = None,
) -> Optional[List[dict]]:
    global bus_http_client
    # 해당 노선을 체크해야 하는지 확인
    if route_should_check is None:
        route_should_check = should_check_route(route_name)

    if not route_should_check:
        # 체크할 필요 없는 노선은 캐시에서 삭제하고 리턴 (유지 중인 위치도 함께 지운다)
        delete_cache(route_name)
        forget_last_good_bus_data(route_name)
        if not REDIS_ENABLED:
            latest_bus_data.pop(route_name, None)
        # print(f"[{route_name}] 운행 중이 아니므로 캐시 삭제")
        return None

    if bus_http_client is None or bus_http_client.is_closed:
        bus_http_client = httpx.AsyncClient(timeout=BUS_API_TIMEOUT)

    try:
        return await _request_bus_data(route_name, route_id, log_context)
    finally:
        route_checked_at[route_name] = time_module.monotonic()


async def _request_bus_data(
        route_name: str,
        route_id: str,
        log_context: Optional[BusSyncLogContext],
) -> Optional[List[dict]]:
    try:
        api_url = build_api_url(route_id, route_name)
        logger.debug(f"[BUS_API][request] route={route_name} url={api_url}")
        response = await bus_http_client.get(api_url)
        response.raise_for_status()
        data = response.json()

        # 데이터가 없는 경우 처리. 마지막 확인 위치는 BUS_HOLD_SECONDS 동안 남겨 둔다.
        if not data["response"]["body"]["items"]:
            delete_cache(route_name)
            if not REDIS_ENABLED:
                latest_bus_data.pop(route_name, None)
            if log_context:
                log_context.external_empty.add(route_name)
            return None

        items = data["response"]["body"]["items"]["item"]
        if isinstance(items, dict):
            items = [items]

        # Redis에 저장 (TTL BUS_CACHE_TTL 초)
        set_cache(route_name, items, BUS_CACHE_TTL)
        remember_last_good_bus_data(route_name, items)
        if not REDIS_ENABLED:
            latest_bus_data[route_name] = items
        if log_context:
            log_context.external_success.add(route_name)
        # print(f"[{route_name}] 버스 위치 데이터 업데이트 ({len(items)}대)")
        return items
    except Exception as e:
        logger.error(f"[BUS_WS][api_error] route={route_name} error={e}")
        if not REDIS_ENABLED:
            latest_bus_data.pop(route_name, None)
        return None


async def update_bus_cache():
    """전체 노선 위치를 항상 데워 둔다.

    보는 사람이 없으면 BUS_IDLE_INTERVAL, 있으면 BUS_ACTIVE_INTERVAL마다 돈다.
    웹소켓 첫 메시지와 /buses는 이 캐시를 바로 내보내므로 외부 API 지연을 기다리지 않는다.
    """
    global bus_loop_interval
    while True:
        try:
            await refresh_timetable_if_due()

            await ensure_route_data(
                WS_ROUTE_GROUPS["all"],
                log_context=BusSyncLogContext(group=f"{get_active_ws_group_name()}/{current_loop_interval()}s"),
            )

            # 접속자가 있을 때만 실제로 보낸다 (데이터가 없어도 빈 상태를 보냄)
            await broadcast_bus_data()
            await broadcast_filtered_bus_data()
        except asyncio.CancelledError:
            raise
        except Exception as e:
            logger.error(f"[BUS_WS][loop_error] error={e}")

        bus_loop_interval = current_loop_interval()
        bus_loop_wake.clear()
        try:
            await asyncio.wait_for(bus_loop_wake.wait(), bus_loop_interval)
        except asyncio.TimeoutError:
            pass


async def broadcast_bus_data(websocket: WebSocket = None):
    result = {}
    available_routes = []

    for route_name in ROUTES.keys():
        cached_data = get_latest_bus_data(route_name)
        if cached_data:
            # 각 버스 데이터에서 불필요한 필드 제거
            filtered_data = []
            for bus in cached_data:
                filtered_bus = {k: v for k, v in bus.items() if k not in ["nodeid", "routetp"]}
                filtered_data.append(filtered_bus)
            result[route_name] = filtered_data
            available_routes.append(route_name)

    message = json.dumps(result)
    
    if websocket:
        try:
            await websocket.send_text(message)
        except Exception as e:
            logging.error(f"❌ WebSocket 전송 오류 (단일 클라이언트): {e}")
    else:
        if not active_connections:
            return

        for connection in list(active_connections):
            try:
                await connection.send_text(message)
            except Exception as e:
                logging.error(f"❌ WebSocket 전송 오류: {e}")
                # 끊어진 연결은 제거하지 않음 (WebSocketDisconnect에서 처리)


# WebSocket 엔드포인트
async def broadcast_filtered_bus_data():
    if not any(filtered_connections.values()):
        return

    group_messages = {
        group_name: build_bus_message(WS_ROUTE_GROUPS[group_name])
        for group_name, connections in filtered_connections.items()
        if connections
    }

    for group_name, connections in filtered_connections.items():
        if not connections:
            continue

        message = group_messages[group_name]
        for connection in list(connections):
            try:
                await connection.send_text(message)
            except Exception as e:
                logging.error(f"❌WebSocket 전송 오류: ({group_name}): {e}")


@router.websocket("/ws/bus")
async def websocket_endpoint(websocket: WebSocket):
    """
    버스 위치 정보를 실시간으로 제공하는 WebSocket 엔드포인트입니다.
    클라이언트가 연결하면 주기적으로 최신 버스 위치 데이터를 전송합니다.
    """
    await websocket.accept()
    active_connections.add(websocket)
    logger.info(f"[BUS_WS][connect] group=all total_clients={get_total_active_connections()}")

    try:
        # 외부 API를 기다리지 않고 데워 둔 캐시를 바로 보낸다 (빈 객체라도 전송)
        await broadcast_bus_data(websocket)
        wake_bus_loop()

        while True:
            # 클라이언트로부터 메시지 대기
            data = await websocket.receive_text()

            # "ping" 메시지에 대한 응답 처리
            if data == "ping":
                await websocket.send_text("pong")

    except WebSocketDisconnect:
        logger.info(f"[BUS_WS][disconnect] group=all total_clients={max(get_total_active_connections() - 1, 0)}")
    except Exception as e:
        logger.error(f"[BUS_WS][socket_error] group=all error={e}")
    finally:
        active_connections.discard(websocket)
        logger.info(f"[BUS_WS][removed] group=all total_clients={get_total_active_connections()}")

async def handle_filtered_bus_websocket(websocket: WebSocket, group_name: str):
    route_names = WS_ROUTE_GROUPS[group_name]

    await websocket.accept()
    filtered_connections[group_name].add(websocket)
    logger.info(f"[BUS_WS][connect] group={group_name} total_clients={get_total_active_connections()}")

    try:
        # 외부 API를 기다리지 않고 데워 둔 캐시를 바로 보낸다
        await websocket.send_text(build_bus_message(route_names))
        wake_bus_loop()

        while True:
            data = await websocket.receive_text()
            if data == "ping":
                await websocket.send_text("pong")

    except WebSocketDisconnect:
        logger.info(
            f"[BUS_WS][disconnect] group={group_name} total_clients={max(get_total_active_connections() - 1, 0)}"
        )
    except Exception as e:
        logger.error(f"[BUS_WS][socket_error] group={group_name} error={e}")
    finally:
        filtered_connections[group_name].discard(websocket)
        logger.info(f"[BUS_WS][removed] group={group_name} total_clients={get_total_active_connections()}")


@router.websocket("/ws/bus/asan/down")
async def websocket_asan_down(websocket: WebSocket):
    await handle_filtered_bus_websocket(websocket, "asan_down")


@router.websocket("/ws/bus/asan/up")
async def websocket_asan_up(websocket: WebSocket):
    await handle_filtered_bus_websocket(websocket, "asan_up")


@router.websocket("/ws/bus/cheonan/down")
async def websocket_cheonan_down(websocket: WebSocket):
    await handle_filtered_bus_websocket(websocket, "cheonan_down")


@router.websocket("/ws/bus/cheonan/up")
async def websocket_cheonan_up(websocket: WebSocket):
    await handle_filtered_bus_websocket(websocket, "cheonan_up")


# Global task reference to prevent duplicate execution
bus_cache_task: Optional[asyncio.Task] = None

@router.on_event("startup")
async def startup_event():
    global bus_cache_task
    
    # 백그라운드 작업 시작 (중복 실행 방지)
    if bus_cache_task is None or bus_cache_task.done():
        bus_cache_task = asyncio.create_task(update_bus_cache())


# HTTP API 엔드포인트 (레거시)
@router.get("/buses")
async def get_all_buses():
    """
    운행 중인 24번, 81번 버스 노선의 위치 정보를 조회합니다. (구버전 앱 홈 천캠용)
    데워 둔 캐시를 바로 돌려주고, 요청이 이어지는 동안 백그라운드 갱신을 짧은 주기로 돌립니다.
    """
    target_routes = ["24_DOWN", "81_DOWN"]
    result = {}

    record_http_demand()
    await ensure_unchecked_route_data(tuple(target_routes))

    for route_name in target_routes:
        if route_name not in ROUTES:
            continue

        cached_data = get_latest_bus_data(route_name)

        if cached_data:
            # 각 버스 데이터에서 불필요한 필드 제거
            filtered_data = []
            for bus in cached_data:
                filtered_bus = {k: v for k, v in bus.items() if k not in ["nodeid", "routetp"]}
                filtered_data.append(filtered_bus)
            result[route_name] = filtered_data
        else:
            result[route_name] = None
    return {"buses": result}


@router.get("/buses/{route_name}")
async def get_bus_by_route(route_name: str):
    """
    특정 노선의 운행 중인 버스 위치 정보를 조회합니다.
    데워 둔 캐시를 바로 돌려줍니다.
    """
    # 경로 이름 검증
    if route_name not in ROUTES:
        raise HTTPException(status_code=404, detail="Route not found")

    record_http_demand()
    await ensure_unchecked_route_data((route_name,))
    cached_data = get_latest_bus_data(route_name)

    if not cached_data:
        # 그래도 없으면 데이터 없음 처리
        raise HTTPException(status_code=404, detail="No bus data found for this route")
        
    return {route_name: cached_data}


@router.on_event("shutdown")
async def shutdown_event():
    global bus_http_client
    if bus_http_client and not bus_http_client.is_closed:
        await bus_http_client.aclose()
        bus_http_client = None


@router.post("/cache/invalidate")
async def invalidate_bus_cache(route_name: str = None, current_admin=Depends(get_current_admin)):
    """
    버스 데이터 캐시를 무효화합니다.

    - route_name이 지정되면 해당 노선의 캐시만 삭제합니다.
    - route_name이 None이면 모든 버스 노선의 캐시를 삭제합니다.
    """
    if route_name:
        if route_name not in ROUTES:
            raise HTTPException(status_code=404, detail="Route not found")

        success = delete_cache(route_name)
        forget_last_good_bus_data(route_name)
        if success:
            # 캐시 삭제 후 데이터 다시 가져오기
            await fetch_bus_data(route_name, ROUTES[route_name])
            return {"message": f"{route_name} 노선의 캐시가 무효화되었습니다."}
        else:
            return {"message": f"{route_name} 노선의 캐시가 존재하지 않습니다."}
    else:
        # 모든 버스 데이터 캐시 삭제
        route_names = list(ROUTES.keys())
        deleted_count = 0

        for name in route_names:
            forget_last_good_bus_data(name)
            if delete_cache(name):
                deleted_count += 1

        # 캐시 삭제 후 모든 데이터 다시 가져오기
        tasks = [fetch_bus_data(route_name, route_id) for route_name, route_id in ROUTES.items()]
        await asyncio.gather(*tasks)

        return {"message": f"{deleted_count}개 노선의 캐시가 무효화되었습니다."}


# 캐시 무효화를 위한 함수 (관리자 API로 추가할 수 있음)
@router.post("/admin/clear-cache")
def clear_shuttle_cache(current_admin=Depends(get_current_admin)):
    """
    모든 셔틀 캐시를 무효화합니다.
    """
    deleted_count = delete_pattern("*")
    return {"message": f"{deleted_count}개의 캐시가 무효화되었습니다.", "success": True}


@router.post("/cache/invalidate")
def invalidate_cache(pattern: str = "*", current_admin=Depends(get_current_admin)):
    """
    특정 패턴의 셔틀 캐시를 무효화합니다.
    예: 
    - 모든 셔틀 캐시: *
    - 스케줄 캐시: schedules:*
    - 역 캐시: stations:*
    """
    deleted_count = delete_pattern(pattern)
    return {"message": f"{deleted_count}개의 캐시가 무효화되었습니다."}


@router.get("/bus-timetable")
def get_bus_timetable(request: Request):
    """
    앱이 내려받는 시내버스 시간표. 대시보드 게시본(없으면 bus_times.json)을 그대로 준다.
    """
    data = read_current_timetable()
    if not data or not data.get("version"):
        raise HTTPException(status_code=404, detail="Bus timetable not found")
    etag = f'"{data["version"]}"'
    headers = {"ETag": etag, "Cache-Control": "no-cache"}
    if request.headers.get("if-none-match") == etag:
        return Response(status_code=304, headers=headers)
    return JSONResponse(content=data, headers=headers)


@router.get("/bus-timetable/version")
def get_bus_timetable_version():
    """
    지금 적용 중인 시간표 버전만 반환하는 엔드포인트 (구버전 앱이 사용)
    """
    data = read_current_timetable()
    if not data:
        raise HTTPException(status_code=404, detail="Bus timetable not found")
    version = data.get("version")
    if not version:
        raise HTTPException(status_code=404, detail="Version field not found")
    return {"version": version}
