from fastapi import APIRouter, HTTPException, Depends
import asyncio
import httpx
import os
from dotenv import load_dotenv
from sqlalchemy.orm import Session
from database import SessionLocal
from models import BusLocation  # DB 모델
from database import get_db

router = APIRouter()

load_dotenv()
API_KEY = os.getenv("API_KEY")
CITY_CODE = "34040"
BASE_URL = "http://apis.data.go.kr/1613000/BusLcInfoInqireService/getRouteAcctoBusLcList"

ROUTES = {
    # 순환5번
    "순환5_DOWN": "ASB288000141",  # 호서대학교 출발 (하행)
    "순환5_UP": "ASB288000286",  # 천안아산역 출발 (상행)

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
}

bus_data = {}

def build_api_url(route_id):
    return f"{BASE_URL}?serviceKey={API_KEY}&cityCode={CITY_CODE}&routeId={route_id}&_type=json"


async def fetch_bus_data(route_name, route_id, db: Session):
    async with httpx.AsyncClient() as client:
        try:
            response = await client.get(build_api_url(route_id))
            response.raise_for_status()
            data = response.json()

            if data["response"]["header"]["resultCode"] == "00":
                items = data["response"]["body"]["items"]["item"]

                # DB에 저장
                for item in items:
                    bus_location = BusLocation(
                        route_name=route_name,
                        latitude=item["latitude"],
                        longitude=item["longitude"],
                        bus_number=item["busNumber"]
                    )
                    db.add(bus_location)
                db.commit()
        except Exception as e:
            print(f"Error fetching bus data for {route_name}: {e}")



async def update_bus_data_periodically():
    db = SessionLocal()  # DB 세션 생성
    while True:
        tasks = [fetch_bus_data(route_name, route_id, db) for route_name, route_id in ROUTES.items()]
        await asyncio.gather(*tasks)
        await asyncio.sleep(5)


@router.on_event("startup")
async def startup_event():
    asyncio.create_task(update_bus_data_periodically())

@router.get("/buses")
async def get_all_buses(db: Session = Depends(get_db)):
    bus_locations = db.query(BusLocation).all()
    return {"buses": bus_locations}

@router.get("/buses/{route_name}")
async def get_bus_by_route(route_name: str, db: Session = Depends(get_db)):
    bus_locations = db.query(BusLocation).filter(BusLocation.route_name == route_name).all()
    if not bus_locations:
        raise HTTPException(status_code=404, detail="Route not found")
    return {route_name: bus_locations}
