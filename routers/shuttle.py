from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy.orm import Session
from typing import List
from pydantic import BaseModel
from datetime import time, date
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates
from utils.security import get_current_admin
from holidayskr import is_holiday

from database import get_db
from models.shuttle import Schedule, ScheduleStop, ShuttleStation, ShuttleRoute
from models.schedule_types import ScheduleType, ScheduleException
from utils.redis_client import get_cache, set_cache, delete_pattern
from utils.serializer import serialize_models

router = APIRouter()
templates = Jinja2Templates(directory="templates")

# 캐시 get/set 공통화 헬퍼 함수
def get_or_set_cache(key: str, db_query_func, serializer):
    cached = get_cache(key)
    if cached:
        return cached
    data = db_query_func()
    if not data:
        raise HTTPException(status_code=404, detail="데이터 없음")
    serialized = serializer(data)
    set_cache(key, serialized)
    return serialized

# schedule_type 결정 유틸 함수
def resolve_schedule_type(db: Session, target_date: date) -> tuple[str, str]:
    date_str = target_date.strftime('%Y-%m-%d')
    weekday = target_date.weekday()  # 0=월요일, 6=일요일
    # 1. 기본 타입 결정
    if weekday == 5:
        base_schedule_type = "Saturday"
    elif weekday == 4:
        base_schedule_type = "Weekday_friday"
    elif weekday == 6:
        base_schedule_type = "Holiday"
    else:
        base_schedule_type = "Weekday"
    # 2. 공휴일 판단
    if is_holiday(date_str):
        base_schedule_type = "Holiday"
    # 3. 예외 일정 매칭
    schedule_exceptions = db.query(ScheduleException).filter(
        ScheduleException.start_date <= target_date,
        ScheduleException.end_date >= target_date,
        ScheduleException.is_activate == True
    ).all()
    applicable_exception = None
    if schedule_exceptions:
        for exception in schedule_exceptions:
            exception_type_active = db.query(ScheduleType).filter(
                ScheduleType.schedule_type == exception.schedule_type,
                ScheduleType.is_activate == True
            ).first()
            if exception_type_active:
                should_apply_exception = False
                if weekday == 5:
                    should_apply_exception = exception.include_saturday
                elif weekday == 4:
                    should_apply_exception = exception.include_weekday_friday
                elif weekday == 6:
                    should_apply_exception = exception.include_sunday
                elif base_schedule_type == "Holiday":
                    should_apply_exception = exception.include_holiday
                else:
                    should_apply_exception = exception.include_weekday
                if should_apply_exception:
                    applicable_exception = exception
                    break
    if applicable_exception:
        schedule_type = applicable_exception.schedule_type
    else:
        schedule_type = base_schedule_type
    # 4. 활성화 여부 확인 및 이름 반환
    schedule_type_info = db.query(ScheduleType).filter(
        ScheduleType.schedule_type == schedule_type
    ).first()
    if not schedule_type_info or not schedule_type_info.is_activate:
        raise HTTPException(
            status_code=404,
            detail=f"Schedule type '{schedule_type}' is not active for date {target_date}"
        )
    return schedule_type, schedule_type_info.schedule_type_name

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

class ScheduleTypeResponse(BaseModel):
    schedule_type: str
    schedule_type_name: str
    is_activate: bool

    class Config:
        from_attributes = True

class ScheduleTypeCreate(BaseModel):
    schedule_type: str
    schedule_type_name: str
    is_activate: bool = True

class ScheduleTypeUpdate(BaseModel):
    schedule_type_name: str | None = None
    is_activate: bool | None = None

class ScheduleExceptionResponse(BaseModel):
    id: int
    start_date: date
    end_date: date
    schedule_type: str
    reason: str | None
    schedule_type_name: str | None = None  # 클라이언트에서 표시하기 위해 추가
    is_activate: bool
    include_weekday: bool
    include_weekday_friday: bool
    include_saturday: bool
    include_sunday: bool
    include_holiday: bool

    class Config:
        from_attributes = True

class ScheduleExceptionCreate(BaseModel):
    start_date: date
    end_date: date
    schedule_type: str
    reason: str | None = None
    is_activate: bool = True
    include_weekday: bool = True
    include_weekday_friday: bool = True
    include_saturday: bool = False
    include_sunday: bool = False
    include_holiday: bool = False

class ScheduleExceptionUpdate(BaseModel):
    start_date: date | None = None
    end_date: date | None = None
    schedule_type: str | None = None
    reason: str | None = None
    is_activate: bool | None = None
    include_weekday: bool | None = None
    include_weekday_friday: bool | None = None
    include_saturday: bool | None = None
    include_sunday: bool | None = None
    include_holiday: bool | None = None

class RouteResponse(BaseModel):
    id: int
    route_name: str
    direction: str
    description: str | None

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

class StationSchedulesByDateResponse(BaseModel):
    schedule_type: str
    schedule_type_name: str
    date: date
    station_id: int
    station_name: str
    schedules: List[StationScheduleResponse]

    class Config:
        from_attributes = True

class ScheduleResponse(BaseModel):
    id: int
    route_id: int
    schedule_type: str
    start_time: time
    end_time: time
    class Config:
        from_attributes = True

@router.get("/schedules", response_model=List[ScheduleResponse])
def get_schedules(
    route_id: int,
    schedule_type: str,
    db: Session = Depends(get_db)
):
    """
    특정 노선 ID와 일정 유형에 따른 셔틀 일정을 조회합니다.
    """
    cache_key = f"schedules:{route_id}:{schedule_type}"
    return get_or_set_cache(
        cache_key,
        lambda: db.query(Schedule).filter(
            Schedule.route_id == route_id,
            Schedule.schedule_type == schedule_type
        ).all(),
        serialize_models
    )

@router.get("/schedules-by-date")
def get_schedules_by_date(
    route_id: int,
    date: date,
    db: Session = Depends(get_db)
):
    """
    특정 노선 ID와 날짜에 따른 셔틀 일정을 조회합니다.
    요일, 공휴일, 예외 일정을 모두 고려하여 해당 날짜에 적용되는 일정을 반환합니다.
    """
    cache_key = f"schedules-by-date:{route_id}:{date}"
    cached_data = get_cache(cache_key)
    if cached_data:
        return cached_data
    # schedule_type 결정 (유틸 함수 사용)
    schedule_type, schedule_type_name = resolve_schedule_type(db, date)
    schedules = db.query(Schedule).filter(
        Schedule.route_id == route_id,
        Schedule.schedule_type == schedule_type
    ).all()
    if not schedules:
        raise HTTPException(
            status_code=404,
            detail=f"No schedules found for route {route_id} on {date} (type: {schedule_type})"
        )
    result = {
        "schedule_type": schedule_type,
        "schedule_type_name": schedule_type_name,
        "date": date.isoformat(),
        "schedules": serialize_models(schedules)
    }
    set_cache(cache_key, result)
    return result

@router.get("/schedules/{schedule_id}/stops", response_model=List[ScheduleStopResponse])
def get_schedule_stops(
    schedule_id: int,
    db: Session = Depends(get_db)
):
    """
    특정 일정 ID에 대한 모든 정류장 정보를 조회합니다.
    """
    # Redis 캐시 키 생성
    cache_key = f"schedule_stops:{schedule_id}"
    
    # Redis 캐시 확인
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
    
    # Redis에 응답 데이터 캐싱
    set_cache(cache_key, result)
    
    return result

@router.get("/stations/{station_id}/schedules", response_model=List[StationScheduleResponse])
def get_station_schedules(
    station_id: int,
    db: Session = Depends(get_db)
):
    """
    특정 정류장 ID에 대한 모든 셔틀 일정을 조회합니다.
    """
    cache_key = f"station_schedules:{station_id}"
    def db_query():
        return db.query(
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
    def serializer(schedules):
        if not schedules:
            return []
        return [
            {
                "schedule_id": schedule.schedule_id,
                "route_id": schedule.route_id,
                "station_name": schedule.station_name,
                "arrival_time": schedule.arrival_time.isoformat() if hasattr(schedule.arrival_time, 'isoformat') else schedule.arrival_time,
                "stop_order": schedule.stop_order,
                "schedule_type": schedule.schedule_type
            } for schedule in schedules
        ]
    return get_or_set_cache(cache_key, db_query, serializer)

@router.get("/stations", response_model=List[StationResponse])
def get_stations(
        station_id: int | None = None,
        db: Session = Depends(get_db)
):
    """
    모든 셔틀 정류장 목록을 조회합니다.
    station_id가 제공되면 해당 정류장만 조회합니다.
    """
    cache_key = f"stations:{station_id if station_id else 'all'}"
    def db_query():
        if station_id:
            station = db.query(ShuttleStation).filter(
                ShuttleStation.id == station_id
            ).first()
            if not station:
                return []
            return [station]
        else:
            return db.query(ShuttleStation).all()
    return get_or_set_cache(cache_key, db_query, serialize_models)

@router.get("/routes", response_model=List[RouteResponse])
def get_routes(
    route_id: int | None = None,
    db: Session = Depends(get_db)
):
    """
    모든 셔틀 노선 목록을 조회합니다.
    route_id가 제공되면 해당 노선만 조회합니다.
    """
    cache_key = f"routes:{route_id if route_id else 'all'}"
    def db_query():
        if route_id:
            route = db.query(ShuttleRoute).filter(
                ShuttleRoute.id == route_id
            ).first()
            if not route:
                return []
            return [route]
        else:
            return db.query(ShuttleRoute).all()
    return get_or_set_cache(cache_key, db_query, serialize_models)

@router.get("/schedule-types", response_model=List[ScheduleTypeResponse])
def get_schedule_types(db: Session = Depends(get_db)):
    """
    모든 일정 유형(평일, 주말, 공휴일 등) 목록을 조회합니다.
    """
    cache_key = "schedule_types"
    return get_or_set_cache(cache_key, lambda: db.query(ScheduleType).all(), serialize_models)

@router.post("/admin/schedule-types", response_model=ScheduleTypeResponse)
def create_schedule_type(
    schedule_type_data: ScheduleTypeCreate,
    db: Session = Depends(get_db),
    current_admin = Depends(get_current_admin)
):
    """
    새로운 일정 유형을 생성합니다. (관리자 권한 필요)
    """
    # 이미 존재하는지 확인
    existing = db.query(ScheduleType).filter(
        ScheduleType.schedule_type == schedule_type_data.schedule_type
    ).first()
    
    if existing:
        raise HTTPException(
            status_code=400,
            detail=f"일정 유형 코드 '{schedule_type_data.schedule_type}'가 이미 존재합니다."
        )
    
    # 이름도 중복 확인
    existing_name = db.query(ScheduleType).filter(
        ScheduleType.schedule_type_name == schedule_type_data.schedule_type_name
    ).first()
    
    if existing_name:
        raise HTTPException(
            status_code=400,
            detail=f"일정 유형 이름 '{schedule_type_data.schedule_type_name}'이 이미 존재합니다."
        )
    
    # 새 일정 유형 생성
    new_schedule_type = ScheduleType(**schedule_type_data.dict())
    db.add(new_schedule_type)
    
    try:
        db.commit()
        db.refresh(new_schedule_type)
    except Exception as e:
        db.rollback()
        raise HTTPException(
            status_code=500, 
            detail=f"일정 유형 생성 중 오류가 발생했습니다: {str(e)}"
        )
    
    # 캐시 무효화
    delete_pattern("schedule_types")
    
    return new_schedule_type

@router.put("/admin/schedule-types/{schedule_type}", response_model=ScheduleTypeResponse)
def update_schedule_type(
    schedule_type: str,
    schedule_type_data: ScheduleTypeUpdate,
    db: Session = Depends(get_db),
    current_admin = Depends(get_current_admin)
):
    """
    기존 일정 유형을 수정합니다. (관리자 권한 필요)
    """
    # 일정 유형 존재 확인
    db_schedule_type = db.query(ScheduleType).filter(
        ScheduleType.schedule_type == schedule_type
    ).first()
    
    if not db_schedule_type:
        raise HTTPException(
            status_code=404,
            detail=f"일정 유형 '{schedule_type}'을 찾을 수 없습니다."
        )
    
    # 이름 중복 확인 (이름이 변경된 경우)
    if schedule_type_data.schedule_type_name and schedule_type_data.schedule_type_name != db_schedule_type.schedule_type_name:
        existing_name = db.query(ScheduleType).filter(
            ScheduleType.schedule_type_name == schedule_type_data.schedule_type_name
        ).first()
        
        if existing_name:
            raise HTTPException(
                status_code=400,
                detail=f"일정 유형 이름 '{schedule_type_data.schedule_type_name}'이 이미 존재합니다."
            )
    
    # 업데이트할 데이터 설정
    if schedule_type_data.schedule_type_name:
        db_schedule_type.schedule_type_name = schedule_type_data.schedule_type_name
    if schedule_type_data.is_activate is not None:
        db_schedule_type.is_activate = schedule_type_data.is_activate
    
    try:
        db.commit()
        db.refresh(db_schedule_type)
    except Exception as e:
        db.rollback()
        raise HTTPException(
            status_code=500, 
            detail=f"일정 유형 업데이트 중 오류가 발생했습니다: {str(e)}"
        )
    
    # 캐시 무효화
    delete_pattern("schedule_types")
    delete_pattern("schedules-by-date:*")
    delete_pattern("schedule_exceptions")
    
    return db_schedule_type

@router.delete("/admin/schedule-types/{schedule_type}")
def delete_schedule_type(
    schedule_type: str,
    db: Session = Depends(get_db),
    current_admin = Depends(get_current_admin)
):
    """
    일정 유형을 삭제합니다. (관리자 권한 필요)
    해당 유형을 사용하는 일정이나 예외가 있으면 삭제할 수 없습니다.
    """
    # 일정 유형 존재 확인
    db_schedule_type = db.query(ScheduleType).filter(
        ScheduleType.schedule_type == schedule_type
    ).first()
    
    if not db_schedule_type:
        raise HTTPException(
            status_code=404,
            detail=f"일정 유형 '{schedule_type}'을 찾을 수 없습니다."
        )
    
    # 관련 일정 있는지 확인
    schedules = db.query(Schedule).filter(
        Schedule.schedule_type == schedule_type
    ).count()
    
    if schedules > 0:
        raise HTTPException(
            status_code=400,
            detail=f"이 일정 유형을 사용하는 {schedules}개의 일정이 있어 삭제할 수 없습니다. 대신 비활성화하세요."
        )
    
    # 예외 일정 있는지 확인
    exceptions = db.query(ScheduleException).filter(
        ScheduleException.schedule_type == schedule_type
    ).count()
    
    if exceptions > 0:
        raise HTTPException(
            status_code=400,
            detail=f"이 일정 유형을 사용하는 {exceptions}개의 예외 일정이 있어 삭제할 수 없습니다. 먼저 예외 일정을 삭제하세요."
        )
    
    # 삭제 진행
    try:
        db.delete(db_schedule_type)
        db.commit()
    except Exception as e:
        db.rollback()
        raise HTTPException(
            status_code=500, 
            detail=f"일정 유형 삭제 중 오류가 발생했습니다: {str(e)}"
        )
    
    # 캐시 무효화
    delete_pattern("schedule_types")
    
    return {"message": f"일정 유형 '{schedule_type}'이 삭제되었습니다."}

# 관리자 API 엔드포인트 추가
@router.post("/admin/schedules", status_code=201)
def create_schedule(
    schedule_data: ScheduleCreate,
    db: Session = Depends(get_db),
    current_admin = Depends(get_current_admin)
):
    """
    새로운 셔틀 일정을 생성합니다. (관리자 권한 필요)
    """
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
    delete_pattern(f"schedules:*")
    delete_pattern(f"schedules-by-date:*")
    delete_pattern("station_schedules:*")
    delete_pattern("schedule_stops:*")
    
    return {"id": new_schedule.id, "message": "Schedule created successfully"}

@router.put("/admin/schedules/{schedule_id}")
def update_schedule(
    schedule_id: int,
    schedule_data: ScheduleUpdate,
    db: Session = Depends(get_db),
    current_admin = Depends(get_current_admin)
):
    """
    기존 셔틀 일정을 수정합니다. (관리자 권한 필요)
    """
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
    delete_pattern(f"schedules:*")
    delete_pattern(f"schedules-by-date:*")
    delete_pattern("station_schedules:*")
    delete_pattern("schedule_stops:*")
    
    return {"message": "Schedule updated successfully"}

@router.delete("/admin/schedules/{schedule_id}")
def delete_schedule(
    schedule_id: int,
    db: Session = Depends(get_db),
    current_admin = Depends(get_current_admin)
):
    """
    셔틀 일정을 삭제합니다. (관리자 권한 필요)
    """
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
    delete_pattern(f"schedules:*")
    delete_pattern(f"schedules-by-date:*")
    delete_pattern("station_schedules:*")
    delete_pattern("schedule_stops:*")
    
    return {"message": "Schedule deleted successfully"}

# 캐시 무효화를 위한 함수 (관리자 API로 추가할 수 있음)
@router.post("/admin/clear-cache")
def clear_shuttle_cache(current_admin = Depends(get_current_admin)):
    """
    모든 셔틀 캐시를 무효화합니다. (관리자 권한 필요)
    """
    deleted_count = delete_pattern("*")
    return {"message": f"{deleted_count}개의 캐시가 무효화되었습니다.", "success": True}

@router.post("/cache/invalidate")
def invalidate_cache(pattern: str = "*", current_admin = Depends(get_current_admin)):
    """
    특정 패턴의 셔틀 캐시를 무효화합니다. (관리자 권한 필요)
    예: 
    - 모든 셔틀 캐시: *
    - 스케줄 캐시: schedules:*
    - 역 캐시: stations:*
    """
    deleted_count = delete_pattern(pattern)
    return {"message": f"{deleted_count}개의 캐시가 무효화되었습니다."}

# 셔틀 시간표 관리 페이지 (이전 경로 - 이제 dashboard에서 처리)
# @router.get("/admin/schedules", response_class=HTMLResponse)
# async def get_shuttle_admin_schedules(request: Request):
#     return templates.TemplateResponse("shuttle_admin.html", {"request": request})

# 관리자 페이지 (메인) - /shuttle/admin 경로 (URL: /admin/shuttle로 연결됨)
# @router.get("/admin", response_class=HTMLResponse)
# async def get_shuttle_admin_main(request: Request):
#     return templates.TemplateResponse("shuttle_admin.html", {"request": request})

@router.get("/schedule-exceptions", response_model=List[ScheduleExceptionResponse])
def get_schedule_exceptions(db: Session = Depends(get_db)):
    """
    모든 일정 예외(특별 운행일) 목록을 조회합니다.
    """
    # Redis 캐시 키 생성
    cache_key = "schedule_exceptions"
    
    # Redis 캐시 확인
    cached_data = get_cache(cache_key)
    if cached_data:
        return cached_data
    
    # 캐시가 없는 경우 DB에서 조회
    exceptions = db.query(
        ScheduleException.id,
        ScheduleException.start_date,
        ScheduleException.end_date,
        ScheduleException.schedule_type,
        ScheduleException.reason,
        ScheduleType.schedule_type_name,
        ScheduleException.is_activate,
        ScheduleException.include_weekday,
        ScheduleException.include_weekday_friday,
        ScheduleException.include_saturday,
        ScheduleException.include_sunday,
        ScheduleException.include_holiday
    ).join(
        ScheduleType, 
        ScheduleException.schedule_type == ScheduleType.schedule_type
    ).order_by(
        ScheduleException.start_date.desc()
    ).all()
    
    # 결과를 직렬화
    result = []
    for exc in exceptions:
        result.append({
            "id": exc.id,
            "start_date": exc.start_date,
            "end_date": exc.end_date,
            "schedule_type": exc.schedule_type,
            "reason": exc.reason,
            "schedule_type_name": exc.schedule_type_name,
            "is_activate": exc.is_activate,
            "include_weekday": exc.include_weekday,
            "include_weekday_friday": exc.include_weekday_friday,
            "include_saturday": exc.include_saturday,
            "include_sunday": exc.include_sunday,
            "include_holiday": exc.include_holiday
        })
    
    # Redis에 응답 데이터 캐싱
    set_cache(cache_key, result)
    
    return result

@router.post("/admin/schedule-exceptions", response_model=ScheduleExceptionResponse)
def create_schedule_exception(
    exception_data: ScheduleExceptionCreate,
    db: Session = Depends(get_db),
    current_admin = Depends(get_current_admin)
):
    """
    새로운 일정 예외(특별 운행일)를 생성합니다. (관리자 권한 필요)
    """
    # 일정 유형이 존재하는지 확인
    schedule_type = db.query(ScheduleType).filter(
        ScheduleType.schedule_type == exception_data.schedule_type
    ).first()
    
    if not schedule_type:
        raise HTTPException(
            status_code=404,
            detail=f"일정 유형 '{exception_data.schedule_type}'을 찾을 수 없습니다."
        )
    
    # 날짜 유효성 검사
    if exception_data.start_date > exception_data.end_date:
        raise HTTPException(
            status_code=400,
            detail="시작 날짜는 종료 날짜보다 이전이어야 합니다."
        )
    

    
    # 새 예외 일정 생성
    new_exception = ScheduleException(**exception_data.dict())
    db.add(new_exception)
    
    try:
        db.commit()
        db.refresh(new_exception)
    except Exception as e:
        db.rollback()
        raise HTTPException(
            status_code=500, 
            detail=f"예외 일정 생성 중 오류가 발생했습니다: {str(e)}"
        )
    
    # 캐시 무효화
    delete_pattern("schedule_exceptions")
    delete_pattern("schedules-by-date:*")
    
    # 예외 일정과 일정 유형 이름 함께 반환
    response = {
        "id": new_exception.id,
        "start_date": new_exception.start_date,
        "end_date": new_exception.end_date,
        "schedule_type": new_exception.schedule_type,
        "reason": new_exception.reason,
        "schedule_type_name": schedule_type.schedule_type_name,
        "is_activate": new_exception.is_activate,
        "include_weekday": new_exception.include_weekday,
        "include_weekday_friday": new_exception.include_weekday_friday,
        "include_saturday": new_exception.include_saturday,
        "include_sunday": new_exception.include_sunday,
        "include_holiday": new_exception.include_holiday
    }
    
    return response

@router.put("/admin/schedule-exceptions/{exception_id}", response_model=ScheduleExceptionResponse)
def update_schedule_exception(
    exception_id: int,
    exception_data: ScheduleExceptionUpdate,
    db: Session = Depends(get_db),
    current_admin = Depends(get_current_admin)
):
    """
    기존 일정 예외(특별 운행일)를 수정합니다. (관리자 권한 필요)
    """
    # 예외 일정이 존재하는지 확인
    exception = db.query(ScheduleException).filter(
        ScheduleException.id == exception_id
    ).first()
    
    if not exception:
        raise HTTPException(
            status_code=404,
            detail=f"예외 일정 ID {exception_id}를 찾을 수 없습니다."
        )
    
    # 수정할 데이터 준비
    update_data = {}
    
    # 날짜 업데이트 (둘 다 제공된 경우에만 검증)
    start_date = exception_data.start_date or exception.start_date
    end_date = exception_data.end_date or exception.end_date
    
    if start_date > end_date:
        raise HTTPException(
            status_code=400,
            detail="시작 날짜는 종료 날짜보다 이전이어야 합니다."
        )
    

    
    # 시작 날짜 업데이트
    if exception_data.start_date:
        exception.start_date = exception_data.start_date
    
    # 종료 날짜 업데이트
    if exception_data.end_date:
        exception.end_date = exception_data.end_date
    
    # 일정 유형 변경 시 존재하는지 확인
    schedule_type_name = None
    if exception_data.schedule_type:
        schedule_type = db.query(ScheduleType).filter(
            ScheduleType.schedule_type == exception_data.schedule_type
        ).first()
        
        if not schedule_type:
            raise HTTPException(
                status_code=404,
                detail=f"일정 유형 '{exception_data.schedule_type}'을 찾을 수 없습니다."
            )
        
        exception.schedule_type = exception_data.schedule_type
        schedule_type_name = schedule_type.schedule_type_name
    
    # 이유 업데이트
    if exception_data.reason is not None:
        exception.reason = exception_data.reason
    
    # 상태 업데이트
    if exception_data.is_activate is not None:
        exception.is_activate = exception_data.is_activate
    
    # 요일별 포함 여부 업데이트
    if exception_data.include_weekday is not None:
        exception.include_weekday = exception_data.include_weekday
    
    if exception_data.include_weekday_friday is not None:
        exception.include_weekday_friday = exception_data.include_weekday_friday
    
    if exception_data.include_saturday is not None:
        exception.include_saturday = exception_data.include_saturday
    
    if exception_data.include_sunday is not None:
        exception.include_sunday = exception_data.include_sunday
    
    if exception_data.include_holiday is not None:
        exception.include_holiday = exception_data.include_holiday
    
    try:
        db.commit()
        db.refresh(exception)
    except Exception as e:
        db.rollback()
        raise HTTPException(
            status_code=500, 
            detail=f"예외 일정 업데이트 중 오류가 발생했습니다: {str(e)}"
        )
    
    # 캐시 무효화
    delete_pattern("schedule_exceptions")
    delete_pattern("schedules-by-date:*")
    
    # 현재 일정 유형 이름 가져오기
    if not schedule_type_name:
        schedule_type = db.query(ScheduleType).filter(
            ScheduleType.schedule_type == exception.schedule_type
        ).first()
        schedule_type_name = schedule_type.schedule_type_name if schedule_type else None
    
    # 응답 준비
    response = {
        "id": exception.id,
        "start_date": exception.start_date,
        "end_date": exception.end_date,
        "schedule_type": exception.schedule_type,
        "reason": exception.reason,
        "schedule_type_name": schedule_type_name,
        "is_activate": exception.is_activate,
        "include_weekday": exception.include_weekday,
        "include_weekday_friday": exception.include_weekday_friday,
        "include_saturday": exception.include_saturday,
        "include_sunday": exception.include_sunday,
        "include_holiday": exception.include_holiday
    }
    
    return response

@router.delete("/admin/schedule-exceptions/{exception_id}")
def delete_schedule_exception(
    exception_id: int,
    db: Session = Depends(get_db),
    current_admin = Depends(get_current_admin)
):
    """
    일정 예외(특별 운행일)를 삭제합니다. (관리자 권한 필요)
    """
    # 예외 일정이 존재하는지 확인
    exception = db.query(ScheduleException).filter(
        ScheduleException.id == exception_id
    ).first()
    
    if not exception:
        raise HTTPException(
            status_code=404,
            detail=f"예외 일정 ID {exception_id}를 찾을 수 없습니다."
        )
    
    # 삭제 진행
    try:
        db.delete(exception)
        db.commit()
    except Exception as e:
        db.rollback()
        raise HTTPException(
            status_code=500, 
            detail=f"예외 일정 삭제 중 오류가 발생했습니다: {str(e)}"
        )
    
    # 캐시 무효화
    delete_pattern("schedule_exceptions")
    delete_pattern("schedules-by-date:*")
    
    return {"message": f"예외 일정 ID {exception_id}가 삭제되었습니다."}

@router.get("/stations/{station_id}/schedules-by-date", response_model=StationSchedulesByDateResponse)
def get_station_schedules_by_date(
    station_id: int,
    date: date,
    db: Session = Depends(get_db)
):
    """
    특정 정류장 ID와 날짜에 따른 셔틀 일정을 조회합니다.
    요일, 공휴일, 예외 일정을 모두 고려하여 해당 날짜에 적용되는 일정을 반환합니다.
    """
    cache_key = f"station_schedules:{station_id}:{date}"
    cached_data = get_cache(cache_key)
    if cached_data:
        return cached_data
    station = db.query(ShuttleStation).filter(
        ShuttleStation.id == station_id
    ).first()
    if not station:
        raise HTTPException(
            status_code=404,
            detail=f"Station with id {station_id} not found"
        )
    # schedule_type 결정 (유틸 함수 사용)
    schedule_type, schedule_type_name = resolve_schedule_type(db, date)
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
        ScheduleStop.station_id == station_id,
        Schedule.schedule_type == schedule_type
    ).order_by(
        Schedule.route_id,
        Schedule.start_time,
        ScheduleStop.stop_order
    ).all()
    schedules_list = []
    if schedules:
        schedules_list = [
            {
                "schedule_id": schedule.schedule_id,
                "route_id": schedule.route_id,
                "station_name": schedule.station_name,
                "arrival_time": schedule.arrival_time.isoformat() if hasattr(schedule.arrival_time, 'isoformat') else schedule.arrival_time,
                "stop_order": schedule.stop_order,
                "schedule_type": schedule.schedule_type
            } for schedule in schedules
        ]
    response = {
        "schedule_type": schedule_type,
        "schedule_type_name": schedule_type_name,
        "date": date.isoformat(),
        "station_id": station_id,
        "station_name": station.name,
        "schedules": schedules_list
    }
    set_cache(cache_key, response)
    return response
