from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy.orm import Session
from typing import List
from pydantic import BaseModel
from datetime import time
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates

from database import get_db
from models.shuttle import Schedule, ScheduleStop, ShuttleStation, ShuttleRoute
from utils.redis_client import get_cache, set_cache, delete_pattern
from utils.serializer import serialize_models

router = APIRouter()
templates = Jinja2Templates(directory="templates")

class ScheduleStopResponse(BaseModel):
    station_id: int
    arrival_time: time
    stop_order: int
    station_name: str

    class Config:
        from_attributes = True

class StationScheduleResponse(BaseModel):
    schedule_id: int
    route_id: int
    station_name: str
    arrival_time: time
    stop_order: int
    schedule_type: str

    class Config:
        from_attributes = True

class StationResponse(BaseModel):
    id: int
    name: str
    latitude: float
    longitude: float
    description: str | None
    image_url: str | None

    class Config:
        from_attributes = True

class RouteResponse(BaseModel):
    id: int
    route_name: str
    direction: str

    class Config:
        from_attributes = True

# 새로운 스키마 추가
class ScheduleStopCreate(BaseModel):
    station_id: int
    arrival_time: time
    stop_order: int

class ScheduleCreate(BaseModel):
    route_id: int
    schedule_type: str
    start_time: time
    end_time: time
    stops: List[ScheduleStopCreate]

class ScheduleUpdate(BaseModel):
    route_id: int | None = None
    schedule_type: str | None = None
    start_time: time | None = None
    end_time: time | None = None
    stops: List[ScheduleStopCreate] | None = None

@router.get("/schedules")
def get_schedules(
    route_id: int,
    schedule_type: str,
    db: Session = Depends(get_db)
):
    # 캐시 키 생성
    cache_key = f"shuttle:schedules:{route_id}:{schedule_type}"
    
    # 캐시 확인
    cached_data = get_cache(cache_key)
    if cached_data:
        return cached_data
    
    # 캐시가 없는 경우 DB에서 조회
    schedules = db.query(Schedule).filter(
        Schedule.route_id == route_id,
        Schedule.schedule_type == schedule_type
    ).all()

    if not schedules:
        raise HTTPException(
            status_code=404,
            detail=f"No schedules found for route {route_id} on {schedule_type}"
        )
    
    # 결과를 직렬화하고 캐시에 저장
    serialized_schedules = serialize_models(schedules)
    set_cache(cache_key, serialized_schedules)
    
    return serialized_schedules

@router.get("/schedules/{schedule_id}/stops", response_model=List[ScheduleStopResponse])
def get_schedule_stops(
    schedule_id: int,
    db: Session = Depends(get_db)
):
    # 캐시 키 생성
    cache_key = f"shuttle:schedule_stops:{schedule_id}"
    
    # 캐시 확인
    cached_data = get_cache(cache_key)
    if cached_data:
        return cached_data
    
    # 캐시가 없는 경우 DB에서 조회
    stops = db.query(
        ShuttleStation.id.label('station_id'),
        ScheduleStop.arrival_time,
        ScheduleStop.stop_order,
        ShuttleStation.name.label('station_name')
    ).join(
        ShuttleStation,
        ScheduleStop.station_id == ShuttleStation.id
    ).filter(
        ScheduleStop.schedule_id == schedule_id
    ).order_by(
        ScheduleStop.stop_order
    ).all()

    if not stops:
        raise HTTPException(
            status_code=404,
            detail=f"No stops found for schedule {schedule_id}"
        )
    
    # SQLAlchemy Result 객체를 사전 리스트로 변환
    result = [
        {
            "station_id": stop.station_id,
            "arrival_time": stop.arrival_time.isoformat() if hasattr(stop.arrival_time, 'isoformat') else stop.arrival_time,
            "stop_order": stop.stop_order,
            "station_name": stop.station_name
        } for stop in stops
    ]
    
    # 결과를 캐시에 저장
    set_cache(cache_key, result)
    
    return result

@router.get("/stations/{station_id}/schedules", response_model=List[StationScheduleResponse])
def get_station_schedules(
    station_id: int,
    db: Session = Depends(get_db)
):
    # 캐시 키 생성
    cache_key = f"shuttle:station_schedules:{station_id}"
    
    # 캐시 확인
    cached_data = get_cache(cache_key)
    if cached_data:
        return cached_data
    
    # 캐시가 없는 경우 DB에서 조회
    schedules = db.query(
        Schedule.id.label('schedule_id'),
        Schedule.route_id,
        ShuttleStation.name.label('station_name'),
        ScheduleStop.arrival_time,
        ScheduleStop.stop_order,
        Schedule.schedule_type
    ).join(
        ScheduleStop, Schedule.id == ScheduleStop.schedule_id
    ).join(
        ShuttleStation, ScheduleStop.station_id == ShuttleStation.id
    ).filter(
        ScheduleStop.station_id == station_id
    ).order_by(
        Schedule.route_id,
        Schedule.start_time,
        ScheduleStop.stop_order
    ).all()

    if not schedules:
        raise HTTPException(
            status_code=404,
            detail=f"No schedules found for station {station_id}"
        )
    
    # SQLAlchemy Result 객체를 사전 리스트로 변환
    result = [
        {
            "schedule_id": schedule.schedule_id,
            "route_id": schedule.route_id,
            "station_name": schedule.station_name,
            "arrival_time": schedule.arrival_time.isoformat() if hasattr(schedule.arrival_time, 'isoformat') else schedule.arrival_time,
            "stop_order": schedule.stop_order,
            "schedule_type": schedule.schedule_type
        } for schedule in schedules
    ]
    
    # 결과를 캐시에 저장
    set_cache(cache_key, result)
    
    return result

@router.get("/stations", response_model=List[StationResponse])
def get_stations(
        station_id: int | None = None,
        db: Session = Depends(get_db)
):
    # 캐시 키 생성
    cache_key = f"shuttle:stations:{station_id if station_id else 'all'}"
    
    # 캐시 확인
    cached_data = get_cache(cache_key)
    if cached_data:
        return cached_data
    
    # 캐시가 없는 경우 DB에서 조회
    if station_id:
        station = db.query(ShuttleStation).filter(
            ShuttleStation.id == station_id
        ).first()

        if not station:
            raise HTTPException(
                status_code=404,
                detail=f"Station with id {station_id} not found"
            )
        
        stations = [station]
    else:
        stations = db.query(ShuttleStation).all()
    
    # 결과를 직렬화하고 캐시에 저장
    serialized_stations = serialize_models(stations)
    set_cache(cache_key, serialized_stations)
    
    return serialized_stations

@router.get("/routes", response_model=List[RouteResponse])
def get_routes(
    route_id: int | None = None,
    db: Session = Depends(get_db)
):
    # 캐시 키 생성
    cache_key = f"shuttle:routes:{route_id if route_id else 'all'}"
    
    # 캐시 확인
    cached_data = get_cache(cache_key)
    if cached_data:
        return cached_data
    
    # 캐시가 없는 경우 DB에서 조회
    if route_id:
        route = db.query(ShuttleRoute).filter(
            ShuttleRoute.id == route_id
        ).first()

        if not route:
            raise HTTPException(
                status_code=404,
                detail=f"Route with id {route_id} not found"
            )
        
        routes = [route]
    else:
        routes = db.query(ShuttleRoute).all()
    
    # 결과를 직렬화하고 캐시에 저장
    serialized_routes = serialize_models(routes)
    set_cache(cache_key, serialized_routes)
    
    return serialized_routes

# 캐시 무효화를 위한 함수 (관리자 API로 추가할 수 있음)
@router.post("/cache/invalidate")
def invalidate_cache(pattern: str = "shuttle:*"):
    """
    특정 패턴의 셔틀 캐시를 무효화합니다.
    예: 
    - 모든 셔틀 캐시: shuttle:*
    - 스케줄 캐시: shuttle:schedules:*
    - 역 캐시: shuttle:stations:*
    """
    deleted_count = delete_pattern(pattern)
    return {"message": f"{deleted_count}개의 캐시가 무효화되었습니다."}

# 관리자 API 엔드포인트 추가
@router.post("/admin/schedules", status_code=201)
def create_schedule(
    schedule_data: ScheduleCreate,
    db: Session = Depends(get_db)
):
    # 1. 해당 route가 존재하는지 확인
    route = db.query(ShuttleRoute).filter(ShuttleRoute.id == schedule_data.route_id).first()
    if not route:
        raise HTTPException(status_code=404, detail=f"Route with id {schedule_data.route_id} not found")
    
    # 2. 스케줄 객체 생성
    new_schedule = Schedule(
        route_id=schedule_data.route_id,
        schedule_type=schedule_data.schedule_type,
        start_time=schedule_data.start_time,
        end_time=schedule_data.end_time
    )
    db.add(new_schedule)
    db.flush()  # ID 할당을 위해 flush
    
    # 3. 스케줄 정류장 객체 생성
    for stop_data in schedule_data.stops:
        # 정류장이 존재하는지 확인
        station = db.query(ShuttleStation).filter(ShuttleStation.id == stop_data.station_id).first()
        if not station:
            db.rollback()
            raise HTTPException(status_code=404, detail=f"Station with id {stop_data.station_id} not found")
        
        new_stop = ScheduleStop(
            schedule_id=new_schedule.id,
            station_id=stop_data.station_id,
            arrival_time=stop_data.arrival_time,
            stop_order=stop_data.stop_order
        )
        db.add(new_stop)
    
    # 4. 커밋
    try:
        db.commit()
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=500, detail=f"Failed to create schedule: {str(e)}")
    
    # 5. 캐시 무효화
    delete_pattern(f"shuttle:schedules:{schedule_data.route_id}:*")
    delete_pattern("shuttle:station_schedules:*")
    
    return {"id": new_schedule.id, "message": "Schedule created successfully"}

@router.put("/admin/schedules/{schedule_id}")
def update_schedule(
    schedule_id: int,
    schedule_data: ScheduleUpdate,
    db: Session = Depends(get_db)
):
    # 1. 스케줄 존재 확인
    schedule = db.query(Schedule).filter(Schedule.id == schedule_id).first()
    if not schedule:
        raise HTTPException(status_code=404, detail=f"Schedule with id {schedule_id} not found")
    
    # 2. route_id가 변경되었고 해당 route가 존재하는지 확인
    if schedule_data.route_id is not None:
        route = db.query(ShuttleRoute).filter(ShuttleRoute.id == schedule_data.route_id).first()
        if not route:
            raise HTTPException(status_code=404, detail=f"Route with id {schedule_data.route_id} not found")
        schedule.route_id = schedule_data.route_id
    
    # 3. 다른 필드 업데이트
    if schedule_data.schedule_type is not None:
        schedule.schedule_type = schedule_data.schedule_type
    if schedule_data.start_time is not None:
        schedule.start_time = schedule_data.start_time
    if schedule_data.end_time is not None:
        schedule.end_time = schedule_data.end_time
    
    # 4. stops 업데이트 (있을 경우)
    if schedule_data.stops is not None:
        # 기존 정류장 정보 삭제
        db.query(ScheduleStop).filter(ScheduleStop.schedule_id == schedule_id).delete()
        
        # 새 정류장 정보 추가
        for stop_data in schedule_data.stops:
            # 정류장이 존재하는지 확인
            station = db.query(ShuttleStation).filter(ShuttleStation.id == stop_data.station_id).first()
            if not station:
                db.rollback()
                raise HTTPException(status_code=404, detail=f"Station with id {stop_data.station_id} not found")
            
            new_stop = ScheduleStop(
                schedule_id=schedule_id,
                station_id=stop_data.station_id,
                arrival_time=stop_data.arrival_time,
                stop_order=stop_data.stop_order
            )
            db.add(new_stop)
    
    # 5. 커밋
    try:
        db.commit()
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=500, detail=f"Failed to update schedule: {str(e)}")
    
    # 6. 캐시 무효화
    delete_pattern(f"shuttle:schedules:{schedule.route_id}:*")
    delete_pattern("shuttle:station_schedules:*")
    delete_pattern(f"shuttle:schedule_stops:{schedule_id}")
    
    return {"message": "Schedule updated successfully"}

@router.delete("/admin/schedules/{schedule_id}")
def delete_schedule(
    schedule_id: int,
    db: Session = Depends(get_db)
):
    # 1. 스케줄 존재 확인
    schedule = db.query(Schedule).filter(Schedule.id == schedule_id).first()
    if not schedule:
        raise HTTPException(status_code=404, detail=f"Schedule with id {schedule_id} not found")
    
    route_id = schedule.route_id  # 캐시 무효화를 위해 저장
    
    # 2. 스케줄 삭제
    try:
        db.delete(schedule)  # 관계에 cascade 설정되어 있어 stops도 자동 삭제됨
        db.commit()
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=500, detail=f"Failed to delete schedule: {str(e)}")
    
    # 3. 캐시 무효화
    delete_pattern(f"shuttle:schedules:{route_id}:*")
    delete_pattern("shuttle:station_schedules:*")
    delete_pattern(f"shuttle:schedule_stops:{schedule_id}")
    
    return {"message": "Schedule deleted successfully"}

# 셔틀 시간표 관리 페이지 (이전 경로 - 이제 dashboard에서 처리)
# @router.get("/admin/schedules", response_class=HTMLResponse)
# async def get_shuttle_admin_schedules(request: Request):
#     return templates.TemplateResponse("shuttle_admin.html", {"request": request})

# 관리자 페이지 (메인) - /shuttle/admin 경로 (URL: /admin/shuttle로 연결됨)
# @router.get("/admin", response_class=HTMLResponse)
# async def get_shuttle_admin_main(request: Request):
#     return templates.TemplateResponse("shuttle_admin.html", {"request": request})

