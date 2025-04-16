from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from typing import List
from pydantic import BaseModel
from datetime import time

from database import get_db
from models.shuttle import Schedule, ScheduleStop, ShuttleStation, ShuttleRoute
from utils.redis_client import get_cache, set_cache, delete_pattern
from utils.serializer import serialize_models

router = APIRouter()

class ScheduleStopResponse(BaseModel):
    arrival_time: time
    stop_order: int
    station_name: str

    class Config:
        from_attributes = True

class StationScheduleResponse(BaseModel):
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

