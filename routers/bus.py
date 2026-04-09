from fastapi import APIRouter, WebSocket, WebSocketDisconnect, HTTPException, Depends
import asyncio
from typing import List, Dict, Set, Optional, Tuple
from dataclasses import dataclass, field
import httpx
import os
import json
from dotenv import load_dotenv
import redis
from utils.redis_client import redis_client, set_cache, get_cache, delete_cache, delete_pattern
from utils.security import get_current_admin
from datetime import datetime, timedelta, time
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

# 주요 노선 운행 시간
MAIN_ROUTES_START_TIME = time(6, 5)  # 오전 6시 15분
MAIN_ROUTES_END_TIME = time(23, 50)  # 오후 10시 15분

# 웹소켓 연결 관리
active_connections: Set[WebSocket] = set()
filtered_connections: Dict[str, Set[WebSocket]] = {
    group_name: set() for group_name in WS_ROUTE_GROUPS if group_name != "all"
}
bus_clients_event = asyncio.Event()

# 시간표 데이터 저장
bus_timetable: Dict[str, dict] = {}
# 파싱된 시간표 캐시 (문자열 파싱 비용 절감)
parsed_bus_timetable: Dict[str, List[Tuple[int, int]]] = {}
# 시간표 파일의 마지막 수정 시간
last_timetable_update = 0
# 재사용 HTTP 클라이언트
bus_http_client: Optional[httpx.AsyncClient] = None
route_fetch_tasks: Dict[str, asyncio.Task] = {}

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
        cached_data = get_cache(route_name)
        if cached_data:
            filtered_data = []
            for bus in cached_data:
                filtered_bus = {k: v for k, v in bus.items() if k not in ["nodeid", "routetp"]}
                filtered_data.append(filtered_bus)
            result[route_name] = filtered_data

    return json.dumps(result)


def get_requested_route_names() -> Tuple[str, ...]:
    if active_connections:
        return WS_ROUTE_GROUPS["all"]

    requested_routes = set()
    for group_name, connections in filtered_connections.items():
        if connections:
            requested_routes.update(WS_ROUTE_GROUPS[group_name])

    return tuple(route_name for route_name in ROUTES if route_name in requested_routes)


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
        if log_context:
            log_context.skipped.add(route_name)
        return None

    if use_cache:
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


def load_bus_timetable():
    global last_timetable_update, bus_timetable, parsed_bus_timetable
    try:
        file_path = 'bus_times.json'
        current_mtime = os.path.getmtime(file_path)
        if current_mtime > last_timetable_update:
            with open(file_path, 'r', encoding='utf-8') as f:
                bus_timetable.clear()
                bus_timetable.update(json.load(f))
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
                last_timetable_update = current_mtime
                logging.debug(f"버스 시간표가 업데이트되었습니다: {datetime.fromtimestamp(current_mtime)}")
    except Exception as e:
        logging.error(f"시간표 로딩 오류: {e}")


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
        # 체크할 필요 없는 노선은 캐시에서 삭제하고 리턴
        delete_cache(route_name)
        # print(f"[{route_name}] 운행 중이 아니므로 캐시 삭제")
        return None

    if bus_http_client is None or bus_http_client.is_closed:
        bus_http_client = httpx.AsyncClient()

    try:
        api_url = build_api_url(route_id, route_name)
        logger.debug(f"[BUS_API][request] route={route_name} url={api_url}")
        response = await bus_http_client.get(api_url)
        response.raise_for_status()
        data = response.json()

        # 데이터가 없는 경우 처리
        if not data["response"]["body"]["items"]:
            delete_cache(route_name)
            if log_context:
                log_context.external_empty.add(route_name)
            return None

        items = data["response"]["body"]["items"]["item"]
        if isinstance(items, dict):
            items = [items]

        # Redis에 저장 (TTL BUS_CACHE_TTL 초)
        set_cache(route_name, items, BUS_CACHE_TTL)
        if log_context:
            log_context.external_success.add(route_name)
        # print(f"[{route_name}] 버스 위치 데이터 업데이트 ({len(items)}대)")
        return items
    except Exception as e:
        logger.error(f"[BUS_WS][api_error] route={route_name} error={e}")
        return None


async def update_bus_cache():
    load_bus_timetable()
    while True:
        # 접속자 생길 때까지 대기
        await bus_clients_event.wait()

        load_bus_timetable()
        requested_route_names = get_requested_route_names()

        if requested_route_names:
            await ensure_route_data(
                requested_route_names,
                log_context=BusSyncLogContext(group=get_active_ws_group_name()),
            )
        else:
            logging.debug("현재 요청된 노선이 없습니다")

        # 데이터가 있든 없든 브로드캐스트 (빈 상태 전송)
        await broadcast_bus_data()
        await broadcast_filtered_bus_data()

        # logging.debug(f"===== 버스 데이터 업데이트 완료: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')} =====\n")
        await asyncio.sleep(5)


async def broadcast_bus_data(websocket: WebSocket = None):
    result = {}
    available_routes = []

    for route_name in ROUTES.keys():
        cached_data = get_cache(route_name)
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
    bus_clients_event.set()
    logger.info(f"[BUS_WS][connect] group=all total_clients={get_total_active_connections()}")

    try:
        await ensure_route_data(
            WS_ROUTE_GROUPS["all"],
            log_context=BusSyncLogContext(group="all"),
        )

        # 데이터가 있든 없든 최초 1회는 상태를 알려줌 (빈 객체라도 전송)
        await broadcast_bus_data(websocket)

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
        if get_total_active_connections() == 0:
            bus_clients_event.clear()
            logger.info("[BUS_WS][idle] total_clients=0 background_paused=true")

async def handle_filtered_bus_websocket(websocket: WebSocket, group_name: str):
    route_names = WS_ROUTE_GROUPS[group_name]

    await websocket.accept()
    filtered_connections[group_name].add(websocket)
    bus_clients_event.set()
    logger.info(f"[BUS_WS][connect] group={group_name} total_clients={get_total_active_connections()}")

    try:
        await ensure_route_data(
            route_names,
            log_context=BusSyncLogContext(group=group_name),
        )
        await websocket.send_text(build_bus_message(route_names))

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
        if get_total_active_connections() == 0:
            bus_clients_event.clear()
            logger.info("[BUS_WS][idle] total_clients=0 background_paused=true")


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
    운행 중인 24번, 81번 버스 노선의 위치 정보를 조회합니다.
    캐시에 없으면 실시간으로 조회합니다.
    """
    target_routes = ["24_DOWN", "81_DOWN"]
    result = {}

    await ensure_route_data(tuple(target_routes))

    for route_name in target_routes:
        if route_name not in ROUTES:
            continue

        cached_data = get_cache(route_name)

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
    캐시에 없으면 실시간으로 조회합니다.
    """
    # 경로 이름 검증
    if route_name not in ROUTES:
        raise HTTPException(status_code=404, detail="Route not found")

    await ensure_route_data((route_name,))
    cached_data = get_cache(route_name)

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


@router.get("/bus-timetable/version")
def get_bus_timetable_version():
    """
    bus_times.json의 version 필드만 반환하는 엔드포인트
    """
    try:
        with open('bus_times.json', 'r', encoding='utf-8') as f:
            data = json.load(f)
            version = data.get('version')
            if version:
                return {"version": version}
            else:
                raise HTTPException(status_code=404, detail="Version field not found")
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail="bus_times.json not found")
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
