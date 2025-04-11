from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from typing import List
from pydantic import BaseModel
from datetime import time

from database import get_db
from models.shuttle import Schedule, ScheduleStop, ShuttleStation, ShuttleRoute

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
    schedules = db.query(Schedule).filter(
        Schedule.route_id == route_id,
        Schedule.schedule_type == schedule_type
    ).all()

    if not schedules:
        raise HTTPException(
            status_code=404,
            detail=f"No schedules found for route {route_id} on {schedule_type}"
        )

    return schedules

@router.get("/schedules/{schedule_id}/stops", response_model=List[ScheduleStopResponse])
def get_schedule_stops(
    schedule_id: int,
    db: Session = Depends(get_db)
):
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

    return stops

@router.get("/stations/{station_id}/schedules", response_model=List[StationScheduleResponse])
def get_station_schedules(
    station_id: int,
    db: Session = Depends(get_db)
):
    schedules = db.query(
        Schedule.route_id,
        ShuttleStation.name.label('station_name'),
        ScheduleStop.arrival_time,
        ScheduleStop.stop_order
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

    return schedules


@router.get("/stations", response_model=List[StationResponse])
def get_stations(
        station_id: int | None = None,
        db: Session = Depends(get_db)
):
    if station_id:
        station = db.query(ShuttleStation).filter(
            ShuttleStation.id == station_id
        ).first()

        if not station:
            raise HTTPException(
                status_code=404,
                detail=f"Station with id {station_id} not found"
            )

        return [station]

    return db.query(ShuttleStation).all()

@router.get("/routes", response_model=List[RouteResponse])
def get_routes(
    route_id: int | None = None,
    db: Session = Depends(get_db)
):
    if route_id:
        route = db.query(ShuttleRoute).filter(
            ShuttleRoute.id == route_id
        ).first()

        if not route:
            raise HTTPException(
                status_code=404,
                detail=f"Route with id {route_id} not found"
            )

        return [route]

    return db.query(ShuttleRoute).all()

