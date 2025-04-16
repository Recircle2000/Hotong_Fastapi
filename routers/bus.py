from fastapi import APIRouter, WebSocket, WebSocketDisconnect, HTTPException
import asyncio
import httpx
import os
import json
from dotenv import load_dotenv
import redis
from utils.redis_client import redis_client, set_cache, get_cache, delete_cache, delete_pattern

router = APIRouter()

load_dotenv()
API_KEY = os.getenv("API_KEY")
CITY_CODE = "34040"
BASE_URL = "http://apis.data.go.kr/1613000/BusLcInfoInqireService/getRouteAcctoBusLcList"

# 버스 노선 ID
ROUTES = {
    # 순환5번
    #"순환5_DOWN": "ASB288000141",  # 호서대학교 출발 (하행)
    #"순환5_UP": "ASB288000286",    # 천안아산역 출발 (상행)

    "900_UP":"ASB285000245", #900번 상행 개발용
    "900_DOWN":"ASB285000244",#900번 하행

    # 810번
   # "810_DOWN": "ASB288000276",  # 호서대학교 출발 (하행)
   # "810_UP": "ASB288000091",  # 시외버스터미널 출발 (상행)

    # 820번
    #"820_DOWN": "ASB288000277",  # 호서대학교 출발 (하행)
    #"820_UP": "ASB288000092",  # 시외버스터미널 출발 (상행)

    # 821번
    #"821_DOWN": "ASB288000333",  # 호서대학교 출발 (하행)
    #"821_UP": "ASB288000332",  # 시외버스터미널 출발 (상행)

    # 1000번
    #"1000_DOWN": "ASB288000352",  # 호서대학교 출발 (하행)
   # "1000_UP": "ASB288000353",  # 탕정역 출발 (상행)

    # 1001번
    #"1001_UP": "ASB288000358",  # 포스코 아파트 출발 (상행)
    # 기타 노선은 주석 처리되어 있음
}

# 버스 데이터 캐시 TTL (초)
BUS_CACHE_TTL = 60

# 웹소켓 연결 관리
active_connections = []


def build_api_url(route_id):
    return f"{BASE_URL}?serviceKey={API_KEY}&cityCode={CITY_CODE}&routeId={route_id}&_type=json"


async def fetch_bus_data(route_name, route_id):
    async with httpx.AsyncClient() as client:
        try:
            response = await client.get(build_api_url(route_id))
            response.raise_for_status()
            data = response.json()

            # 데이터가 없는 경우 처리
            if not data["response"]["body"]["items"]:
                print(f"No bus data available for {route_name}")
                delete_cache(route_name)
                return

            items = data["response"]["body"]["items"]["item"]
            if isinstance(items, dict):
                items = [items]

            # Redis에 저장 (TTL BUS_CACHE_TTL 초)
            set_cache(route_name, items, BUS_CACHE_TTL)
        except Exception as e:
            print(f"Error fetching bus data for {route_name}: {e}")


async def update_bus_data_periodically():
    while True:
        print("버스 데이터 업데이트 시작")
        tasks = [fetch_bus_data(route_name, route_id) for route_name, route_id in ROUTES.items()]
        await asyncio.gather(*tasks)
        # 갱신된 데이터를 웹소켓 클라이언트들에게 브로드캐스트
        await broadcast_bus_data()

        await asyncio.sleep(60)# 10초 주기


async def broadcast_bus_data(websocket: WebSocket = None):
    result = {}
    for route_name in ROUTES.keys():
        cached_data = get_cache(route_name)
        if cached_data:
            result[route_name] = cached_data

    message = json.dumps(result)
    if websocket:
        try:
            await websocket.send_text(message)
        except Exception as e:
            print(f"❌ WebSocket 전송 오류: {e}")
    else:
        for connection in active_connections:
            try:
                await connection.send_text(message)
            except Exception as e:
                print(f"❌ WebSocket 전송 오류: {e}")


# 웹소켓 연결 관리
async def connect_client(websocket: WebSocket):
    await websocket.accept()
    active_connections.append(websocket)
    print(f"✅ 클라이언트 접속: {len(active_connections)}명")
    await broadcast_bus_data(websocket)  # Send data to the newly connected client



async def disconnect_client(websocket: WebSocket):
    active_connections.remove(websocket)
    print(f"❌ 클라이언트 접속 종료: {len(active_connections)}명")


#WebSocket 엔드포인트
@router.websocket("/ws/bus")
async def websocket_endpoint(websocket: WebSocket):
    await connect_client(websocket)
    try:
        while True:
            await websocket.receive_text()  # 클라이언트에서 데이터를 받을 수 있음 (ping 등)
    except WebSocketDisconnect:
        await disconnect_client(websocket)
    except Exception as e:
        print(f"WebSocket 연결 오류: {e}")
        await disconnect_client(websocket)


# HTTP API 엔드포인트 (레거시)
@router.get("/buses")
async def get_all_buses():
    result = {}
    for route_name in ROUTES.keys():
        cached_data = get_cache(route_name)
        if cached_data:
            result[route_name] = cached_data
        else:
            result[route_name] = None
    return {"buses": result}


@router.get("/buses/{route_name}")
async def get_bus_by_route(route_name: str):
    # 경로 이름 검증
    if route_name not in ROUTES:
        raise HTTPException(status_code=404, detail="Route not found")

    cached_data = get_cache(route_name)
    if not cached_data:
        raise HTTPException(status_code=404, detail="No bus data found for this route")
    return {route_name: cached_data}

@router.post("/cache/invalidate")
async def invalidate_bus_cache(route_name: str = None):
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
