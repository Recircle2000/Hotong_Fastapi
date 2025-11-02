from fastapi import APIRouter, WebSocket, WebSocketDisconnect, HTTPException, Depends
import asyncio
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
    "순환5_UP": "ASB288000286",    # 천안아산역 출발 (상행)

    #"900_UP":"ASB285000245", #900번 상행 개발용
    #"900_DOWN":"ASB285000244",#900번 하행

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
    #"1001_UP": "ASB288000358",  # 포스코 아파트 출발 (상행)
    # 기타 노선은 주석 처리되어 있음

    # 24번
    "24_UP": "CAB285000025",  # 동우아파트 출발 (상행)
    "24_DOWN": "CAB285000024",  # 각원사 회차지 출발 (하행)

    # 81번
    "81_UP": "CAB285000294",  # 차암2통 출발 (상행)
    "81_DOWN": "CAB285000293",  # 각원사 회차지 출발 (하행)
}

# 주요 노선 (항상 체크)
MAIN_ROUTES = ["순환5_DOWN", "순환5_UP", "24_UP", "24_DOWN", "81_UP", "81_DOWN","1000_DOWN", "1000_UP"]

# 시간표 기반 체크 노선
SCHEDULED_ROUTES = ["810_DOWN", "810_UP", "820_DOWN", "820_UP", "821_DOWN", "821_UP","822_DOWN", "822_UP" ]

# 버스 데이터 캐시 TTL (초)
BUS_CACHE_TTL = 5

# 주요 노선 운행 시간
MAIN_ROUTES_START_TIME = time(6, 5)  # 오전 6시 15분
MAIN_ROUTES_END_TIME = time(23, 50)   # 오후 10시 15분

# 웹소켓 연결 관리
active_connections = []

# 시간표 데이터 저장
bus_timetable = {}
# 시간표 파일의 마지막 수정 시간
last_timetable_update = 0

logging.basicConfig(level=logging.DEBUG)

def load_bus_timetable():
    global last_timetable_update, bus_timetable
    try:
        file_path = 'bus_times.json'
        current_mtime = os.path.getmtime(file_path)
        if current_mtime > last_timetable_update:
            with open(file_path, 'r', encoding='utf-8') as f:
                bus_timetable.clear()
                bus_timetable.update(json.load(f))
                last_timetable_update = current_mtime
                logging.info(f"버스 시간표가 업데이트되었습니다: {datetime.fromtimestamp(current_mtime)}")
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
            logging.info(f"[{route_name}] 주요 노선 운행 시간 외: {now} (운행시간: {MAIN_ROUTES_START_TIME}-{MAIN_ROUTES_END_TIME})")
        return is_check
    
    # 시간표 기반 노선들
    if route_name in SCHEDULED_ROUTES and route_name in bus_timetable:
        # 시간표 확인
        timetable = bus_timetable[route_name]["시간표"]
        
        # 현재 시간
        current_datetime = datetime.now()
        current_time_str = current_datetime.strftime("%H:%M")
        
        # 노선의 운행 여부 확인
        for departure_time in timetable:
            # 출발 시간을 datetime 객체로 변환
            try:
                departure_parts = departure_time.split(":")
                departure_hour = int(departure_parts[0])
                departure_minute = int(departure_parts[1])
                departure_datetime = current_datetime.replace(hour=departure_hour, minute=departure_minute, second=0, microsecond=0)
                
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
                if (-60 <= time_diff_minutes and time_diff_minutes < 0) or (0 <= time_diff_minutes and time_diff_minutes <= 1):
                    # 시간 표시 메시지 작성
                    if time_diff_minutes >= 0:
                        status_msg = f"출발까지 {int(time_diff_minutes)}분 남음"
                    else:
                        status_msg = f"출발 후 {int(abs(time_diff_minutes))}분 경과"
                    
                    #print(f"[{route_name}] 🚍 운행 중: 출발 시간 {departure_time} ({status_msg})")
                    return True
            except Exception as e:
                #print(f"[{route_name}] ⚠️ 시간 계산 오류: {e} (출발시간: {departure_time})")
                continue
        return False
    
    # 기본적으로 체크하지 않음
    if route_name in SCHEDULED_ROUTES and route_name not in bus_timetable:
        logging.warning(f"[{route_name}] ⚠️ 시간표 정보 없음")
    return False

async def fetch_bus_data(route_name, route_id):
    # 해당 노선을 체크해야 하는지 확인
    if not should_check_route(route_name):
        # 체크할 필요 없는 노선은 캐시에서 삭제하고 리턴
        if get_cache(route_name):
            delete_cache(route_name)
           # print(f"[{route_name}] 운행 중이 아니므로 캐시 삭제")
        return
        
    async with httpx.AsyncClient() as client:
        try:
            
            response = await client.get(build_api_url(route_id, route_name))
            response.raise_for_status()
            data = response.json()

            # 데이터가 없는 경우 처리
            if not data["response"]["body"]["items"]:
                delete_cache(route_name)
                return

            items = data["response"]["body"]["items"]["item"]
            if isinstance(items, dict):
                items = [items]

            # Redis에 저장 (TTL BUS_CACHE_TTL 초)
            set_cache(route_name, items, BUS_CACHE_TTL)
            #print(f"[{route_name}] 버스 위치 데이터 업데이트 ({len(items)}대)")
        except Exception as e:
            logging.error(f"[{route_name}] API 호출 오류: {e}")
        


async def update_bus_data_periodically():
    load_bus_timetable()
    while True:
        if len(active_connections) == 0:
            # 연결이 없어도 24_DOWN, 81_DOWN은 항상 업데이트
            for forced_route in ["24_DOWN", "81_DOWN"]:
                if forced_route in ROUTES:
                    await fetch_bus_data(forced_route, ROUTES[forced_route])
            await asyncio.sleep(5)  # 연결 없으면 대기만
            logging.debug("연결 없음. 버스 데이터 업데이트x (필수노선만 업데이트)")
            continue
        load_bus_timetable()
        tasks = []
        checking_routes = []
        skipping_routes = []
        for route_name, route_id in ROUTES.items():
            if should_check_route(route_name):
                tasks.append(fetch_bus_data(route_name, route_id))
                checking_routes.append(route_name)
            else:
                skipping_routes.append(route_name)
        if tasks:
            await asyncio.gather(*tasks)
            await broadcast_bus_data()
        else:
            logging.debug("현재 체크할 노선이 없습니다")
        logging.debug(f"===== 버스 데이터 업데이트 완료: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')} =====\n")
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
                filtered_bus = {k: v for k, v in bus.items() if k not in ["nodeid", "nodeord", "routetp"]}
                filtered_data.append(filtered_bus)
            result[route_name] = filtered_data
            available_routes.append(route_name)

    if available_routes:
        logging.info(f"브로드캐스트: {len(available_routes)}개 노선 데이터 전송 ({', '.join(available_routes)})")
    else:
        logging.info("브로드캐스트: 전송할 데이터 없음")
        
    message = json.dumps(result)
    if websocket:
        try:
            await websocket.send_text(message)

        except Exception as e:
            logging.error(f"❌ WebSocket 전송 오류 (단일 클라이언트): {e}")
    else:
        if not active_connections:
            logging.warning("❌ 연결된 클라이언트 없음")
            return
            
        for connection in active_connections:
            try:
                await connection.send_text(message)
            except Exception as e:
                logging.error(f"❌ WebSocket 전송 오류: {e}")
                
                # 끊어진 연결은 제거
                try:
                    active_connections.remove(connection)
                    logging.warning(f"❌ 끊어진 연결 제거 (남은 클라이언트: {len(active_connections)}명)")
                except:
                    pass


# 웹소켓 연결 관리
async def connect_client(websocket: WebSocket):
    await websocket.accept()
    active_connections.append(websocket)
    logging.info(f"✅ 클라이언트 접속: {len(active_connections)}명")
    # 최초 연결 시 버스 데이터 즉시 업데이트 후 전송
    tasks = [fetch_bus_data(route_name, route_id) for route_name, route_id in ROUTES.items()]
    await asyncio.gather(*tasks)
    await broadcast_bus_data(websocket)



async def disconnect_client(websocket: WebSocket):
    active_connections.remove(websocket)
    logging.info(f"❌ 클라이언트 접속 종료: {len(active_connections)}명")


#WebSocket 엔드포인트
@router.websocket("/ws/bus")
async def websocket_endpoint(websocket: WebSocket):
    """
    버스 위치 정보를 실시간으로 제공하는 WebSocket 엔드포인트입니다.
    클라이언트가 연결하면 주기적으로 최신 버스 위치 데이터를 전송합니다.
    """
    await connect_client(websocket)
    try:
        while True:
            # 클라이언트로부터 메시지 대기
            data = await websocket.receive_text()
            
            # "ping" 메시지에 대한 응답 처리
            if data == "ping":
                await websocket.send_text("pong")
            
    except WebSocketDisconnect:
        await disconnect_client(websocket)
    except Exception as e:
        logging.error(f"WebSocket 연결 오류: {e}")
        await disconnect_client(websocket)


# HTTP API 엔드포인트 (레거시)
@router.get("/buses")
async def get_all_buses():
    """
    운행 중인 모든 버스 노선의 버스 위치 정보를 조회합니다.
    """
    result = {}
    for route_name in ROUTES.keys():
        cached_data = get_cache(route_name)
        if cached_data:
            # 각 버스 데이터에서 불필요한 필드 제거
            filtered_data = []
            for bus in cached_data:
                filtered_bus = {k: v for k, v in bus.items() if k not in ["nodeid", "nodeord", "routetp"]}
                filtered_data.append(filtered_bus)
            result[route_name] = filtered_data
        else:
            result[route_name] = None
    return {"buses": result}


@router.get("/buses/{route_name}")
async def get_bus_by_route(route_name: str):
    """
    특정 노선의 운행 중인 버스 위치 정보를 조회합니다.
    """
    # 경로 이름 검증
    if route_name not in ROUTES:
        raise HTTPException(status_code=404, detail="Route not found")

    cached_data = get_cache(route_name)
    if not cached_data:
        raise HTTPException(status_code=404, detail="No bus data found for this route")
    return {route_name: cached_data}

@router.post("/cache/invalidate")
async def invalidate_bus_cache(route_name: str = None, current_admin = Depends(get_current_admin)):
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
def clear_shuttle_cache(current_admin = Depends(get_current_admin)):
    """
    모든 셔틀 캐시를 무효화합니다.
    """
    deleted_count = delete_pattern("*")
    return {"message": f"{deleted_count}개의 캐시가 무효화되었습니다.", "success": True}

@router.post("/cache/invalidate")
def invalidate_cache(pattern: str = "*", current_admin = Depends(get_current_admin)):
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
