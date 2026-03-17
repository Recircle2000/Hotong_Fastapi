from sqlalchemy.orm import Session

from models import ShuttleStation
from schemas.admin_v2 import AdminShuttleStationResponse


SHUTTLE_STATION_NOT_FOUND_MESSAGE = "셔틀 정류장을 찾을 수 없습니다."


def normalize_optional_text(value: str | None) -> str | None:
    if value is None:
        return None
    normalized = value.strip()
    return normalized or None


def list_admin_shuttle_stations(db: Session) -> list[ShuttleStation]:
    return (
        db.query(ShuttleStation)
        .order_by(ShuttleStation.is_active.desc(), ShuttleStation.id.asc())
        .all()
    )


def create_admin_shuttle_station(
    db: Session,
    *,
    name: str,
    latitude: float,
    longitude: float,
    description: str | None,
    image_url: str | None,
    is_active: bool,
) -> ShuttleStation:
    station = ShuttleStation(
        name=name.strip(),
        latitude=latitude,
        longitude=longitude,
        description=normalize_optional_text(description),
        image_url=normalize_optional_text(image_url),
        is_active=bool(is_active),
    )
    db.add(station)
    db.commit()
    db.refresh(station)
    return station


def update_admin_shuttle_station(
    db: Session,
    *,
    station_id: int,
    name: str,
    latitude: float,
    longitude: float,
    description: str | None,
    image_url: str | None,
    is_active: bool,
) -> ShuttleStation | None:
    station = db.query(ShuttleStation).filter(ShuttleStation.id == station_id).first()
    if station is None:
        return None

    station.name = name.strip()
    station.latitude = latitude
    station.longitude = longitude
    station.description = normalize_optional_text(description)
    station.image_url = normalize_optional_text(image_url)
    station.is_active = bool(is_active)
    db.commit()
    db.refresh(station)
    return station


def delete_admin_shuttle_station(db: Session, *, station_id: int) -> bool:
    station = db.query(ShuttleStation).filter(ShuttleStation.id == station_id).first()
    if station is None:
        return False

    db.delete(station)
    db.commit()
    return True


def serialize_shuttle_station(station: ShuttleStation) -> AdminShuttleStationResponse:
    return AdminShuttleStationResponse(
        id=station.id,
        name=station.name,
        latitude=station.latitude,
        longitude=station.longitude,
        description=station.description,
        image_url=station.image_url,
        is_active=bool(station.is_active),
    )
