from fastapi import APIRouter, HTTPException, Depends, WebSocket, WebSocketDisconnect, Query
from sqlalchemy.orm import Session
import httpx
import os
import asyncio
import json
from typing import List, Dict, Set, Optional
from dotenv import load_dotenv
import logging
from utils.redis_client import get_cache, set_cache
from models.subway import SubwayArrivalResponse, SubwayArrivalInfo, StationScheduleResponse, TrainScheduleInfo
from models.subway_schedule import SubwaySchedule
from database import SessionLocal, get_db
import re
from datetime import datetime, timedelta

router = APIRouter(prefix="/subway", tags=["Subway"])

load_dotenv()
SEOUL_SUBWAY_KEY = os.getenv("SEOUL_SUBWAY_KEY")
BASE_URL = "http://swopenAPI.seoul.go.kr/api/subway"

# 캐시 만료 시간 (초)
SUBWAY_CACHE_TTL = 10  # 30초마다 업데이트

# 웹소켓 연결 관리
active_connections: Set[WebSocket] = set()
subway_clients_event = asyncio.Event()
http_client: Optional[httpx.AsyncClient] = None


def get_http_client() -> httpx.AsyncClient:
    global http_client
    if http_client is None or http_client.is_closed:
        http_client = httpx.AsyncClient(timeout=httpx.Timeout(10.0, connect=5.0))
    return http_client

def build_api_url(station_name: str, start_index: int = 0, end_index: int = 20) -> str:
    """
    서울 지하철 API URL을 생성합니다.
    요청하신 대로 타입은 'json'으로 고정되어 있습니다.
    """
    if not SEOUL_SUBWAY_KEY:
        raise ValueError("SEOUL_SUBWAY_KEY is not set in environment variables")
    
    # 클라이언트에 따라 역명에 대한 URL 인코딩이 필요할 수 있지만,
    # httpx가 일반적으로 이를 처리합니다. 서울 API는 경로에 직접 이름을 넣는 것을 기대합니다.
    return f"{BASE_URL}/{SEOUL_SUBWAY_KEY}/json/realtimeStationArrival/{start_index}/{end_index}/{station_name}"

async def fetch_station_data(station_name: str) -> Optional[List[dict]]:
    """
    서울 열린데이터 광장에서 특정 역의 실시간 도착 정보를 가져옵니다.
    """
    url = build_api_url(station_name)
    try:
        client = get_http_client()
        response = await client.get(url)
        response.raise_for_status()
        data = response.json()
        
        if "realtimeArrivalList" in data:
            return data["realtimeArrivalList"]
        else:
            # API가 오류를 반환하거나 데이터 구조가 없는 경우 처리
            code = data.get("code")
            if code == "INFO-200":
                # 데이터가 없는 경우 (정상 상황)
                logging.info(f"No realtime data for {station_name} (INFO-200)")
                return []
            
            logging.warning(f"No realtimeArrivalList found for {station_name}: {data}")
            return []
    except Exception as e:
        logging.error(f"Error fetching subway data for {station_name}: {e}")
        return None

async def broadcast_subway_data(websocket: WebSocket = None):
    """
    모든 연결된 클라이언트에게 현재 캐시된 데이터를 브로드캐스트합니다.
    websocket 인자가 주어지면 해당 클라이언트에게만 전송합니다.
    """
    targets = ["천안", "아산"]
    result = {}
    for station in targets:
        cached_data = get_cache(f"subway:{station}")
        if cached_data:
             safe_items = []
             for item in cached_data:
                 try:
                     safe_items.append(SubwayArrivalInfo(**item).dict())
                 except Exception as e:
                     logging.error(f"Failed to parse cached item for {station}: {e}")
             result[station] = safe_items
        else:
            result[station] = []
    
    message = json.dumps(result)

    if websocket:
        try:
            await websocket.send_text(message)
        except Exception as e:
            logging.error(f"WebSocket send error (single): {e}")
    else:
        if not active_connections:
            return

        for connection in list(active_connections):
            try:
                await connection.send_text(message)
            except Exception as e:
                logging.error(f"WebSocket broadcast error: {e}")
                active_connections.discard(connection)
        if not active_connections:
            subway_clients_event.clear()

async def update_subway_cache():
    """
    대상 역의 지하철 데이터 캐시를 업데이트하는 백그라운드 작업입니다.
    연결된 클라이언트가 없을 때는 업데이트를 일시 중지합니다.
    """
    target_stations = ["천안", "아산"]
    while True:
        # 접속자 생길 때까지 완전 대기
        await subway_clients_event.wait()

        try:
            # 접속자가 있는 동안 반복
            # [User Request]: 캐시된 기점 차량 정보 로드 (매 루프마다 갱신된 정보 확인)
            starting_trains = set(get_cache("subway:cheonan_starting_trains") or [])

            for station in target_stations:
                data = await fetch_station_data(station)
                if data is not None:
                    # 필요하다면 데이터를 파싱하고 단순화하거나, 그대로 저장하고 조회 시 파싱합니다.
                    # Pydantic 모델 구조에 맞춰 파싱된 데이터를 저장합니다.
                    parsed_data = []
                    for item in data:
                        # 종착역이 현재 역과 같으면 제외 (도착해서 운행 종료하는 열차)
                        # [User Request] 종착역이 서동탄이면 제외
                        if item.get("bstatnNm") == item.get("statnNm") or item.get("bstatnNm") == "서동탄":
                            continue

                        # 열차 번호 포맷팅 (예: "0694" -> "k694")
                        btrain_no = item.get("btrainNo", "")
                        if btrain_no:
                            btrain_no = f"k{btrain_no.lstrip('0')}"
                        
                        # 병점행 하행은 제외(서울 -> 병점이 잡히는 문제점 해결)
                        if item.get("updnLine") == "하행" and item.get("bstatnNm") == "병점":
                            continue

                        # 1) 천안 기점 차량이면 메시지 변경
                        if btrain_no in starting_trains:
                            item["arvlMsg2"] = "출발 대기"

                        # 2) 상행 신창 기점(현재 위치가 신창)인 경우 메시지 변경
                        elif item.get("updnLine") == "상행" and item.get("arvlMsg3") == "신창":
                            item["arvlMsg2"] = "기점(신창) 대기"

                        # 3) 위 케이스가 아니라면(=일반 열차) 도착 완료된 열차 제외
                        elif item.get("arvlMsg2") == f"{station} 도착":
                            continue
                        
                        info = SubwayArrivalInfo(
                            subwayId=item.get("subwayId", ""),
                            updnLine=item.get("updnLine", ""),
                            btrainNo=btrain_no,
                            bstatnNm=item.get("bstatnNm", ""),
                            statnNm=item.get("statnNm", ""),
                            arvlMsg2=item.get("arvlMsg2", ""),
                            arvlMsg3=item.get("arvlMsg3", ""),
                            barvlDt=item.get("barvlDt", "0"),
                            recptnDt=item.get("recptnDt", "")
                        )
                        parsed_data.append(info.dict())
                    
                    set_cache(f"subway:{station}", parsed_data, SUBWAY_CACHE_TTL)
                    logging.info(f"Updated cache for subway station: {station}")
                else:
                    logging.info(f"No data received for {station}")
            
            # 업데이트 후 브로드캐스트
            await broadcast_subway_data()

        except Exception as e:
            logging.error(f"Error in subway cache update loop: {e}")
        
        await asyncio.sleep(SUBWAY_CACHE_TTL)


def is_express_train(train_no: str) -> bool:
    """
    급행 여부 판별: 숫자가 3자리면 완행, 4자리면 급행
    """
    digits = re.sub(r'\D', '', train_no)
    return len(digits) == 4

async def fetch_train_schedule(line_name: str, station_name: str, direction: str, day_type: str):
    """
    API에서 기차 시간표를 가져옵니다.
    http://openapi.seoul.go.kr:8088/{KEY}/json/getTrainSch/1/500//N/{direction}/{day_type}/{line_name}//{station_name}
    """
    if not SEOUL_SUBWAY_KEY:
        logging.error("SEOUL_SUBWAY_KEY is missing")
        return []
        
    encoded_station = station_name
    # URL 구성 (슬래시 개수 엄수)
    now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    url = f"http://openapi.seoul.go.kr:8088/{SEOUL_SUBWAY_KEY}/json/getTrainSch/1/100//N/{direction}/{day_type}/{line_name}//{encoded_station}///////{now_str}"
    
    client = get_http_client()
    try:
        response = await client.get(url)
        data = response.json()
        return data
    except Exception as e:
        logging.error(f"Failed to fetch schedule for {station_name} {direction} {day_type}: {e}")
        return None

async def update_schedule_cache_daily():
    """
    24시간마다 역 별 기차 시간표를 캐싱합니다.
    천안, 아산 / 평일, 주말 / 상행, 하행
    """
    first_run = True
    
    while True:
        should_update = True
        
        # 첫 실행 시 DB에 데이터가 있는지 확인
        if first_run:
            db_check = SessionLocal()
            try:
                if db_check.query(SubwaySchedule).first():
                    logging.info("✅ 기존 지하철 시간표 데이터 존재. 시작 시 중복 업데이트 건너뜀.")
                    should_update = False
            except Exception as e:
                logging.error(f"Startup DB check failed: {e}")
            finally:
                db_check.close()
            first_run = False
            
        try:
            stations = []
            if should_update:
                logging.info("Starting daily subway schedule update...")
                
                stations = ["천안", "아산"]
            else:
                logging.info("Skipping initial daily subway schedule update because schedule data already exists.")
            directions = ["상행", "하행"]
            day_types = ["평일", "주말"]
            line_name = "1호선" # 천안/아산은 1호선
            
            new_schedules = []
            
            for station in stations:
                for direction in directions:
                    for day in day_types:
                        data = await fetch_train_schedule(line_name, station, direction, day)
                        
                        items = []
                        # 데이터 구조 파싱 (User provided structure vs Standard API fallback)
                        if data:
                            if "response" in data and "body" in data["response"]:
                                body = data["response"]["body"]
                                if "items" in body and "item" in body["items"]:
                                    items = body["items"]["item"]
                            elif "getTrainSch" in data and "row" in data["getTrainSch"]:
                                items = data["getTrainSch"]["row"]
                        
                        if items:
                            for item in items:
                                train_no = item.get("trainno") or item.get("trainNo")
                                if not train_no:
                                    continue
                                    
                                schedule = SubwaySchedule(
                                    train_no=train_no,
                                    up_down_type=item.get("upbdnbSe") or direction,
                                    day_type=item.get("wkndSe") or day,
                                    line_name=item.get("lineNm") or line_name,
                                    branch_name=item.get("brlnNm"),
                                    station_name=item.get("stnNm") or station,
                                    departure_station=item.get("dptreStnNm"),
                                    arrival_station=item.get("arvlStnNm"),
                                    departure_time=item.get("trainDptreTm"),
                                    arrival_time=item.get("trainArvlTm"),
                                    is_express=is_express_train(train_no)
                                )
                                new_schedules.append(schedule)
                        
                        # API 호출 간격 조절 (과부하 방지: 5초)
                        await asyncio.sleep(1)

            if new_schedules:
                db: Session = SessionLocal()
                try:
                    # 기존 데이터 삭제 (테이블 전체 삭제가 부담스러우면 조건부 삭제 고려 가능하나, 
                    # 24시간 주기 갱신이면 전체 갱신이 깔끔)
                    # "db초기화는 절대로 하면 안됨" -> 스키마 초기화 금지. 데이터 갱신은 OK.
                    db.query(SubwaySchedule).delete()
                    db.bulk_save_objects(new_schedules)
                    db.commit()
                    logging.info(f"Subway schedule updated. Total records: {len(new_schedules)}")

                    # [User Request]: 천안 출발/신창 기점 차량 Redis 캐싱
                    # arrival_time이 없고(None or ""), 상행, departure_station이 "천안"
                    # [User Request]: 현재 요일에 맞춰 평일/주말 필터링 추가
                    now = datetime.now()
                    current_day_type = "주말" if now.weekday() >= 5 else "평일"

                    target_trains = db.query(SubwaySchedule.train_no).filter(
                        SubwaySchedule.departure_station == "천안",
                        SubwaySchedule.up_down_type == "상행",
                        SubwaySchedule.day_type == current_day_type,
                        (SubwaySchedule.arrival_time == None) | (SubwaySchedule.arrival_time == "")
                    ).all()

                    cheonan_starting_ids = []
                    for (t_no,) in target_trains:
                        # 포맷팅: k + 숫자 (leading zero 제거)
                        clean_no = re.sub(r'[^0-9]', '', t_no).lstrip('0')
                        if clean_no:
                            cheonan_starting_ids.append(f"k{clean_no}")

                    set_cache("subway:cheonan_starting_trains", cheonan_starting_ids, 86400) # 24시간 유지
                    logging.info(f"Cached {len(cheonan_starting_ids)} Cheonan starting trains.")
                except Exception as db_e:
                    db.rollback()
                    logging.error(f"Database error during schedule update: {db_e}")
                finally:
                    db.close()
            elif should_update:
                logging.warning("No schedule data fetched.")

        except Exception as e:
            logging.error(f"Error in daily schedule update: {e}")
        
        # 다음 날 02:00까지 대기

        now = datetime.now()
        next_run = now.replace(hour=2, minute=0, second=0, microsecond=0)
        if now >= next_run:
            next_run += timedelta(days=1)
        
        sleep_seconds = (next_run - now).total_seconds()
        logging.info(f"Next schedule update at {next_run} (in {sleep_seconds} seconds)")
        await asyncio.sleep(sleep_seconds)

# Global task references to prevent duplicate execution
subway_cache_task: Optional[asyncio.Task] = None
schedule_cache_task: Optional[asyncio.Task] = None

@router.on_event("startup")
async def startup_event():
    global subway_cache_task, schedule_cache_task, http_client
    if http_client is None or http_client.is_closed:
        http_client = get_http_client()
    
    # 백그라운드 작업 시작 (중복 실행 방지)
    if subway_cache_task is None or subway_cache_task.done():
        subway_cache_task = asyncio.create_task(update_subway_cache())
        
    if schedule_cache_task is None or schedule_cache_task.done():
        schedule_cache_task = asyncio.create_task(update_schedule_cache_daily())


@router.on_event("shutdown")
async def shutdown_event():
    global http_client
    if http_client is not None and not http_client.is_closed:
        await http_client.aclose()
        http_client = None

@router.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    await websocket.accept()
    active_connections.add(websocket)
    subway_clients_event.set()
    logging.info(f"Subway Client connected. Total: {len(active_connections)}")
    
    try:
        # 최초 연결 시 즉시 데이터 전송
        try:
            await broadcast_subway_data(websocket)
        except Exception as e:
            logging.error(f"Initial broadcast failed, but keeping connection alive: {e}")
        
        while True:
            # 클라이언트 유지 및 메시지 처리 (필요 시)
            data = await websocket.receive_text()
            if data == "ping":
                await websocket.send_text("pong")
                
    except WebSocketDisconnect as e:
        logging.info(f"Subway Client disconnected: code={e.code}, reason={e.reason}")
    except Exception as e:
        logging.error(f"WebSocket error: {e}")
    finally:
        active_connections.discard(websocket)
        if not active_connections:
            subway_clients_event.clear()
        logging.info(f"Subway Client removed. Total: {len(active_connections)}")



@router.get("/schedule", response_model=StationScheduleResponse)
def get_subway_schedule(
    station_name: str = Query(..., description="역 이름 (예: 천안, 아산)"),
    day_type: str = Query(..., description="요일 구분 (예: 평일, 주말)"),
    db: Session = Depends(get_db)
):
    """
    지하철 시간표를 조회합니다.
    """
    schedules = db.query(SubwaySchedule).filter(
        SubwaySchedule.station_name == station_name,
        SubwaySchedule.day_type == day_type,
        SubwaySchedule.departure_time != None,
        SubwaySchedule.departure_time != ""
    ).all()
    
    if not schedules:
        # 데이터가 없으면 빈 리스트 반환
        return StationScheduleResponse(
            day_type=day_type,
            station_name=station_name,
            timetable={}
        )

    timetable = {}
    
    # 데이터 그룹화
    for item in schedules:
        direction = item.up_down_type
        if direction not in timetable:
            timetable[direction] = []
            
        timetable[direction].append(TrainScheduleInfo(
            trainno=item.train_no,
            arrival_station=item.arrival_station or "",
            departure_time=item.departure_time or "",
            is_express=item.is_express
        ))
    
    # 시간순 정렬
    for direction in timetable:
        timetable[direction].sort(key=lambda x: x.departure_time)
        
    return StationScheduleResponse(
        day_type=day_type,
        station_name=station_name,
        timetable=timetable
    )

@router.get("/{station_name}", response_model=SubwayArrivalResponse)
async def get_subway_arrival(station_name: str):
    """
    특정 역의 실시간 도착 정보를 조회합니다 (천안, 아산은 자동 캐시됨).
    다른 역의 경우 실시간으로 가져오거나, 대상 역만 지원한다고 가정할 수도 있습니다.
    현재는 캐싱 대상 역에 최적화되어 있습니다.
    """
    # [Safety] 잘못된 경로 매칭 방지
    if station_name in ["ws", "favicon.ico"]:
        raise HTTPException(status_code=404, detail=f"Invalid station name: {station_name}")

    # 캐시 먼저 확인
    cached_data = get_cache(f"subway:{station_name}")
    
    if cached_data:
        items = [SubwayArrivalInfo(**item) for item in cached_data]
        return SubwayArrivalResponse(station=station_name, arrivals=items)
    
    # 캐시에 없는 경우 (다른 역을 온디맨드로 지원하거나, 
    # 대상 역의 캐시가 비어있는 경우), 직접 조회할 수 있습니다.
    # 현재는 캐시에 없으면 직접 조회하도록 처리합니다 (폴백).
    data = await fetch_station_data(station_name)
    if data is None:
        data = []
        
    items = []
    for item in data:
        # 종착역이 현재 역과 같으면 제외 (도착해서 운행 종료하는 열차)
        if item.get("bstatnNm") == item.get("statnNm"):
            continue
            
        # 열차 번호 포맷팅 (예: "0694" -> "k694")
        btrain_no = item.get("btrainNo", "")
        if btrain_no:
            btrain_no = f"k{btrain_no.lstrip('0')}"

        info = SubwayArrivalInfo(
            subwayId=item.get("subwayId", ""),
            updnLine=item.get("updnLine", ""),
            btrainNo=btrain_no,
            bstatnNm=item.get("bstatnNm", ""),
            statnNm=item.get("statnNm", ""),
            arvlMsg2=item.get("arvlMsg2", ""),
            arvlMsg3=item.get("arvlMsg3", ""),
            barvlDt=item.get("barvlDt", "0"),
            recptnDt=item.get("recptnDt", "")
        )
        items.append(info)
    
    return SubwayArrivalResponse(station=station_name, arrivals=items)

@router.get("/", response_model=Dict[str, List[SubwayArrivalInfo]])
async def get_all_target_stations():
    """
    기본 대상 역인 천안, 아산 두 곳의 도착 정보를 조회합니다.
    """
    targets = ["천안", "아산"]
    result = {}
    for station in targets:
        cached_data = get_cache(f"subway:{station}")
        if cached_data:
             result[station] = [SubwayArrivalInfo(**item) for item in cached_data]
        else:
            result[station] = []
    return result


