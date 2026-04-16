from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from fastapi.security import OAuth2PasswordBearer
from sqlalchemy.orm import Session

from database import get_db
from models import User
from schemas.admin_v2 import (
    AdminEmergencyNoticePayload,
    AdminEmergencyNoticeResponse,
    AdminLoginRequest,
    AdminLogoutResponse,
    AdminNoticePayload,
    AdminNoticeResponse,
    AdminSessionResponse,
    AdminSessionUser,
    AdminShuttleStationPayload,
    AdminShuttleStationResponse,
)
from services.admin_auth import (
    AUTH_REQUIRED_MESSAGE,
    AdminAuthError,
    authenticate_admin_credentials,
    clear_admin_session,
    login_admin_session,
    resolve_admin_user,
)
from services.admin_emergency_notice import (
    create_admin_emergency_notice,
    delete_admin_emergency_notice,
    list_admin_emergency_notices,
    serialize_emergency_notice,
    update_admin_emergency_notice,
)
from services.admin_notice import (
    create_admin_notice,
    delete_admin_notice,
    list_admin_notices,
    serialize_notice,
    update_admin_notice,
)
from services.admin_shuttle_station import (
    SHUTTLE_STATION_NOT_FOUND_MESSAGE,
    create_admin_shuttle_station,
    delete_admin_shuttle_station,
    list_admin_shuttle_stations,
    serialize_shuttle_station,
    update_admin_shuttle_station,
)
from utils.redis_client import delete_pattern


router = APIRouter(prefix="/api/admin-v2", tags=["Admin V2"])
oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/api/admin-v2/auth/login", auto_error=False)


def serialize_session_user(user: User) -> AdminSessionUser:
    return AdminSessionUser(id=user.id, email=user.email, is_admin=bool(user.is_admin))


def invalidate_shuttle_station_cache() -> None:
    delete_pattern("stations:*")
    delete_pattern("station_schedules:*")
    delete_pattern("schedule_stops:*")
    delete_pattern("station_route_memberships:*")


async def get_admin_api_user(
    request: Request,
    db: Session = Depends(get_db),
    token: str | None = Depends(oauth2_scheme),
) -> User:
    user = resolve_admin_user(request, db, token)
    if user:
        return user
    raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail=AUTH_REQUIRED_MESSAGE)


@router.post("/auth/login", response_model=AdminSessionResponse)
async def login_admin_v2(
    payload: AdminLoginRequest,
    request: Request,
    db: Session = Depends(get_db),
):
    try:
        user = authenticate_admin_credentials(db, payload.email, payload.password)
    except AdminAuthError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.message) from exc

    login_admin_session(request, user)
    return AdminSessionResponse(authenticated=True, user=serialize_session_user(user))


@router.post("/auth/logout", response_model=AdminLogoutResponse)
async def logout_admin_v2(request: Request):
    clear_admin_session(request)
    return AdminLogoutResponse(success=True)


@router.get("/auth/session", response_model=AdminSessionResponse)
async def get_admin_v2_session(current_admin: User = Depends(get_admin_api_user)):
    return AdminSessionResponse(authenticated=True, user=serialize_session_user(current_admin))


@router.get("/notices", response_model=list[AdminNoticeResponse])
async def get_admin_v2_notices(
    current_admin: User = Depends(get_admin_api_user),
    db: Session = Depends(get_db),
):
    del current_admin
    return [serialize_notice(notice) for notice in list_admin_notices(db)]


@router.post("/notices", response_model=AdminNoticeResponse, status_code=status.HTTP_201_CREATED)
async def create_admin_v2_notice(
    payload: AdminNoticePayload,
    current_admin: User = Depends(get_admin_api_user),
    db: Session = Depends(get_db),
):
    del current_admin
    notice = create_admin_notice(
        db,
        title=payload.title,
        content=payload.content,
        notice_type=payload.notice_type,
        is_pinned=payload.is_pinned,
    )
    return serialize_notice(notice)


@router.put("/notices/{notice_id}", response_model=AdminNoticeResponse)
async def update_admin_v2_notice(
    notice_id: int,
    payload: AdminNoticePayload,
    current_admin: User = Depends(get_admin_api_user),
    db: Session = Depends(get_db),
):
    del current_admin
    notice = update_admin_notice(
        db,
        notice_id=notice_id,
        title=payload.title,
        content=payload.content,
        notice_type=payload.notice_type,
        is_pinned=payload.is_pinned,
    )
    if not notice:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="공지사항을 찾을 수 없습니다.")
    return serialize_notice(notice)


@router.delete("/notices/{notice_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_admin_v2_notice(
    notice_id: int,
    current_admin: User = Depends(get_admin_api_user),
    db: Session = Depends(get_db),
):
    del current_admin
    if not delete_admin_notice(db, notice_id=notice_id):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="공지사항을 찾을 수 없습니다.")
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.get("/emergency-notices", response_model=list[AdminEmergencyNoticeResponse])
async def get_admin_v2_emergency_notices(
    current_admin: User = Depends(get_admin_api_user),
    db: Session = Depends(get_db),
):
    del current_admin
    return [
        serialize_emergency_notice(notice)
        for notice in list_admin_emergency_notices(db)
    ]


@router.post(
    "/emergency-notices",
    response_model=AdminEmergencyNoticeResponse,
    status_code=status.HTTP_201_CREATED,
)
async def create_admin_v2_emergency_notice(
    payload: AdminEmergencyNoticePayload,
    current_admin: User = Depends(get_admin_api_user),
    db: Session = Depends(get_db),
):
    del current_admin
    notice = create_admin_emergency_notice(
        db,
        category=payload.category,
        title=payload.title,
        content=payload.content,
        created_at=payload.created_at,
        end_at=payload.end_at,
    )
    return serialize_emergency_notice(notice)


@router.put("/emergency-notices/{notice_id}", response_model=AdminEmergencyNoticeResponse)
async def update_admin_v2_emergency_notice(
    notice_id: int,
    payload: AdminEmergencyNoticePayload,
    current_admin: User = Depends(get_admin_api_user),
    db: Session = Depends(get_db),
):
    del current_admin
    notice = update_admin_emergency_notice(
        db,
        notice_id=notice_id,
        category=payload.category,
        title=payload.title,
        content=payload.content,
        created_at=payload.created_at,
        end_at=payload.end_at,
    )
    return serialize_emergency_notice(notice)


@router.delete("/emergency-notices/{notice_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_admin_v2_emergency_notice(
    notice_id: int,
    current_admin: User = Depends(get_admin_api_user),
    db: Session = Depends(get_db),
):
    del current_admin
    if not delete_admin_emergency_notice(db, notice_id=notice_id):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="긴급공지 정보를 찾을 수 없습니다.",
        )
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.get("/shuttle-stations", response_model=list[AdminShuttleStationResponse])
async def get_admin_v2_shuttle_stations(
    current_admin: User = Depends(get_admin_api_user),
    db: Session = Depends(get_db),
):
    del current_admin
    return [
        serialize_shuttle_station(station)
        for station in list_admin_shuttle_stations(db)
    ]


@router.post(
    "/shuttle-stations",
    response_model=AdminShuttleStationResponse,
    status_code=status.HTTP_201_CREATED,
)
async def create_admin_v2_shuttle_station(
    payload: AdminShuttleStationPayload,
    current_admin: User = Depends(get_admin_api_user),
    db: Session = Depends(get_db),
):
    del current_admin
    station = create_admin_shuttle_station(
        db,
        name=payload.name,
        latitude=payload.latitude,
        longitude=payload.longitude,
        description=payload.description,
        image_url=payload.image_url,
        is_active=payload.is_active,
    )
    invalidate_shuttle_station_cache()
    return serialize_shuttle_station(station)


@router.put("/shuttle-stations/{station_id}", response_model=AdminShuttleStationResponse)
async def update_admin_v2_shuttle_station(
    station_id: int,
    payload: AdminShuttleStationPayload,
    current_admin: User = Depends(get_admin_api_user),
    db: Session = Depends(get_db),
):
    del current_admin
    station = update_admin_shuttle_station(
        db,
        station_id=station_id,
        name=payload.name,
        latitude=payload.latitude,
        longitude=payload.longitude,
        description=payload.description,
        image_url=payload.image_url,
        is_active=payload.is_active,
    )
    if station is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=SHUTTLE_STATION_NOT_FOUND_MESSAGE,
        )
    invalidate_shuttle_station_cache()
    return serialize_shuttle_station(station)


@router.delete("/shuttle-stations/{station_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_admin_v2_shuttle_station(
    station_id: int,
    current_admin: User = Depends(get_admin_api_user),
    db: Session = Depends(get_db),
):
    del current_admin
    if not delete_admin_shuttle_station(db, station_id=station_id):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=SHUTTLE_STATION_NOT_FOUND_MESSAGE,
        )
    invalidate_shuttle_station_cache()
    return Response(status_code=status.HTTP_204_NO_CONTENT)
