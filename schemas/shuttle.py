from datetime import date, time
from typing import List

from pydantic import BaseModel


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
    schedule_type_name: str | None = None
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

    class Config:
        from_attributes = True


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


class ScheduleTypeByDateResponse(BaseModel):
    schedule_type_name: str


class ScheduleResponse(BaseModel):
    id: int
    route_id: int
    schedule_type: str
    start_time: time
    end_time: time

    class Config:
        from_attributes = True
