from fastapi import APIRouter, HTTPException
import asyncio
import httpx
import os
import json
from dotenv import load_dotenv
import redis
from urllib.parse import unquote

router = APIRouter()

load_dotenv()
API_KEY = os.getenv("API_KEY")
CITY_CODE = "34040"
BASE_URL = "http://apis.data.go.kr/1613000/BusLcInfoInqireService/getRouteAcctoBusLcList"

ROUTES = {
    # 순환5번
    #"순환5_DOWN": "ASB288000141",  # 호서대학교 출발 (하행)
    #"순환5_UP": "ASB288000286",    # 천안아산역 출발 (상행)

    "900_UP":"ASB285000244", #900번 상행
    "900_DOWN":"ASB285000245",#900번 하행

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

# Redis 클라이언트 생성 (decode_responses=True로 문자열 반환)
redis_client = redis.Redis(host="localhost", port=6379, db=0, decode_responses=True)

def build_api_url(route_id):
    return f"{BASE_URL}?serviceKey={API_KEY}&cityCode={CITY_CODE}&routeId={route_id}&_type=json"

async def fetch_bus_data(route_name, route_id):
    async with httpx.AsyncClient() as client:
        try:
            response = await client.get(build_api_url(route_id))
            response.raise_for_status()
            data = response.json()
            print(f"Fetched data for {route_name}: {data}")

            # 'items'가 비어 있으면 캐시 삭제 후 종료
            if not data["response"]["body"]["items"]:
                print(f"No bus data available for {route_name}")
                redis_client.delete(route_name)
                return

            # 정상적인 데이터가 있으면 'item' 필드를 가져옴
            items = data["response"]["body"]["items"]["item"]

            # 응답이 단일 객체라면 리스트로 변환
            if isinstance(items, dict):
                items = [items]

            # Redis에 JSON 문자열로 저장, TTL은 10초 (필요에 따라 조정)
            redis_client.setex(route_name, 10, json.dumps(items))
        except Exception as e:
            print(f"Error fetching bus data for {route_name}: {e}")

async def update_bus_data_periodically():
    while True:
        tasks = []
        for route_name, route_id in ROUTES.items():
            tasks.append(fetch_bus_data(route_name, route_id))
        await asyncio.gather(*tasks)
        await asyncio.sleep(10)  # 10초마다 업데이트

@router.on_event("startup")
async def startup_event():
    asyncio.create_task(update_bus_data_periodically())

@router.get("/buses")
async def get_all_buses():
    result = {}
    for route_name in ROUTES.keys():
        cached_data = redis_client.get(route_name)
        if cached_data:
            result[route_name] = json.loads(cached_data)
        else:
            result[route_name] = None
    return {"buses": result}


@router.get("/buses/{route_name}")
async def get_bus_by_route(route_name: str):
    # No need to decode the route name here as FastAPI handles URL decoding automatically
    if route_name not in ROUTES:
        raise HTTPException(status_code=404, detail="Route not found")

    cached_data = redis_client.get(route_name)
    if not cached_data:
        raise HTTPException(status_code=404, detail="No bus data found for this route")
    return {route_name: json.loads(cached_data)}
