"""대시보드 v2의 시내버스 시간표·노선도 편집과 게시 API."""

from datetime import datetime, timezone
from typing import Any, Literal, NoReturn

from fastapi import APIRouter, Body, Depends, HTTPException, Query, Response, status
from fastapi.responses import JSONResponse, RedirectResponse
from sqlalchemy.orm import Session

from database import get_db
from models import CityBusRelease, CityBusRoute, User
from routers.admin_v2 import get_admin_api_user
from routers.bus import ROUTES as BIS_ROUTE_IDS
from schemas.admin_v2 import (
    AdminCityBusBisTimetableResponse,
    AdminCityBusPublishRequest,
    AdminCityBusReleaseResponse,
    AdminCityBusReorderRequest,
    AdminCityBusRouteCreateRequest,
    AdminCityBusRoutePayload,
    AdminCityBusRouteResponse,
    AdminCityBusStopsCompareResponse,
)
from services import city_bus_bis, city_bus_data
from services.city_bus_bis import CityBusBisError
from services.city_bus_data import (
    KIND_STATIC,
    KIND_TIMETABLE,
    CityBusDataError,
    CityBusNotFoundError,
    CityBusStorageError,
)


router = APIRouter(prefix="/api/admin-v2/city-bus", tags=["Admin V2 City Bus"])

ROUTE_NOT_FOUND_MESSAGE = "노선을 찾을 수 없습니다."
RELEASE_NOT_FOUND_MESSAGE = "게시본을 찾을 수 없습니다."
BIS_ROUTE_MISSING_MESSAGE = "BIS 노선 ID가 없는 노선입니다."
STOPS_ROUTE_MISSING_MESSAGE = "공공데이터 노선 ID가 없는 노선입니다."


def serialize_route(route: CityBusRoute) -> AdminCityBusRouteResponse:
    return AdminCityBusRouteResponse(
        route_key=route.route_key,
        sort_order=route.sort_order,
        origin=route.origin,
        terminus=route.terminus,
        times=list(route.times or []),
        geojson_feature_count=route.geojson_feature_count or 0,
        stop_count=route.stop_count or 0,
        updated_at=route.updated_at,
    )


def serialize_release(release: CityBusRelease, current_ids: set[int], now: datetime) -> AdminCityBusReleaseResponse:
    effective_from = city_bus_data._as_utc(release.effective_from)
    return AdminCityBusReleaseResponse(
        id=release.id,
        kind=release.kind,
        version=release.version,
        effective_from=effective_from,
        published_at=city_bus_data._as_utc(release.published_at),
        download_url=release.download_url,
        sha256=release.sha256,
        size_bytes=release.size_bytes,
        is_current=release.id in current_ids,
        is_scheduled=effective_from is not None and effective_from > now,
        note=release.note,
        changes=release.changes,
    )


def raise_city_bus_error(exc: Exception) -> NoReturn:
    if isinstance(exc, CityBusNotFoundError):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=ROUTE_NOT_FOUND_MESSAGE)
    if isinstance(exc, (CityBusStorageError, CityBusBisError)):
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=str(exc))
    raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc))


@router.get("/routes", response_model=list[AdminCityBusRouteResponse])
def get_city_bus_routes(
    current_admin: User = Depends(get_admin_api_user),
    db: Session = Depends(get_db),
):
    del current_admin
    return [serialize_route(route) for route in city_bus_data.list_routes(db)]


@router.post("/routes", response_model=AdminCityBusRouteResponse, status_code=status.HTTP_201_CREATED)
def create_city_bus_route(
    payload: AdminCityBusRouteCreateRequest,
    current_admin: User = Depends(get_admin_api_user),
    db: Session = Depends(get_db),
):
    try:
        route = city_bus_data.create_route(
            db,
            route_key=payload.route_key,
            origin=payload.origin,
            terminus=payload.terminus,
            times=payload.times,
            admin_id=current_admin.id,
        )
    except (CityBusDataError, CityBusNotFoundError) as exc:
        raise_city_bus_error(exc)
    return serialize_route(route)


@router.put("/routes/order", response_model=list[AdminCityBusRouteResponse])
def reorder_city_bus_routes(
    payload: AdminCityBusReorderRequest,
    current_admin: User = Depends(get_admin_api_user),
    db: Session = Depends(get_db),
):
    del current_admin
    try:
        routes = city_bus_data.reorder_routes(db, payload.route_keys)
    except CityBusDataError as exc:
        raise_city_bus_error(exc)
    return [serialize_route(route) for route in routes]


@router.put("/routes/{route_key}", response_model=AdminCityBusRouteResponse)
def update_city_bus_route(
    route_key: str,
    payload: AdminCityBusRoutePayload,
    current_admin: User = Depends(get_admin_api_user),
    db: Session = Depends(get_db),
):
    try:
        route = city_bus_data.update_route(
            db,
            route_key,
            origin=payload.origin,
            terminus=payload.terminus,
            times=payload.times,
            admin_id=current_admin.id,
        )
    except (CityBusDataError, CityBusNotFoundError) as exc:
        raise_city_bus_error(exc)
    return serialize_route(route)


@router.delete("/routes/{route_key}", status_code=status.HTTP_204_NO_CONTENT)
def delete_city_bus_route(
    route_key: str,
    current_admin: User = Depends(get_admin_api_user),
    db: Session = Depends(get_db),
):
    del current_admin
    try:
        city_bus_data.delete_route(db, route_key)
    except CityBusNotFoundError as exc:
        raise_city_bus_error(exc)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.get("/routes/{route_key}/bis-timetable", response_model=AdminCityBusBisTimetableResponse)
def get_city_bus_bis_timetable(
    route_key: str,
    current_admin: User = Depends(get_admin_api_user),
    db: Session = Depends(get_db),
):
    """BIS 홈페이지의 평일 시간표. 대시보드에서 노선 하나씩 비교할 때만 부른다."""
    del current_admin
    try:
        route = city_bus_data.get_route(db, route_key)
    except CityBusNotFoundError as exc:
        raise_city_bus_error(exc)
    source = city_bus_bis.resolve_bis_source(route.route_key, BIS_ROUTE_IDS)
    if source is None:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=BIS_ROUTE_MISSING_MESSAGE)
    try:
        timetable = city_bus_bis.fetch_bis_timetable(source)
    except CityBusBisError as exc:
        raise_city_bus_error(exc)
    return AdminCityBusBisTimetableResponse(
        source=timetable.source,
        source_url=timetable.source_url,
        times=timetable.times,
        fetched_at=datetime.now(timezone.utc),
    )


@router.get("/routes/{route_key}/stops-compare", response_model=AdminCityBusStopsCompareResponse)
def compare_city_bus_route_stops(
    route_key: str,
    current_admin: User = Depends(get_admin_api_user),
    db: Session = Depends(get_db),
):
    """공공데이터 경유정류소 목록과 저장된 정류장 JSON 비교. 교체는 PUT /routes/{key}/stops로 한다."""
    del current_admin
    try:
        route = city_bus_data.get_route(db, route_key)
    except CityBusNotFoundError as exc:
        raise_city_bus_error(exc)
    # 이 노선 하나의 정류장 원문만 읽는다.
    current = route.stops_json
    resolved = city_bus_bis.resolve_stops_route_id(current, route.route_key, BIS_ROUTE_IDS)
    if resolved is None:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=STOPS_ROUTE_MISSING_MESSAGE)
    route_id, city_code = resolved
    try:
        fetched = city_bus_bis.fetch_route_stops(route_id, city_code)
    except CityBusBisError as exc:
        raise_city_bus_error(exc)
    diff = city_bus_bis.diff_stops(current, fetched)
    return AdminCityBusStopsCompareResponse(
        route_id=route_id,
        city_code=city_code,
        fetched_at=datetime.now(timezone.utc),
        current_count=diff.current_count,
        fetched_count=diff.fetched_count,
        added=diff.added,
        removed=diff.removed,
        renamed=diff.renamed,
        moved=diff.moved,
        reordered=diff.reordered,
        fetched=fetched,
    )


@router.put("/routes/{route_key}/geojson", response_model=AdminCityBusRouteResponse)
def upload_city_bus_route_geojson(
    route_key: str,
    payload: Any = Body(...),
    current_admin: User = Depends(get_admin_api_user),
    db: Session = Depends(get_db),
):
    try:
        route = city_bus_data.set_route_geojson(db, route_key, payload, admin_id=current_admin.id)
    except (CityBusDataError, CityBusNotFoundError) as exc:
        raise_city_bus_error(exc)
    return serialize_route(route)


@router.put("/routes/{route_key}/stops", response_model=AdminCityBusRouteResponse)
def upload_city_bus_route_stops(
    route_key: str,
    payload: Any = Body(...),
    current_admin: User = Depends(get_admin_api_user),
    db: Session = Depends(get_db),
):
    try:
        route = city_bus_data.set_route_stops(db, route_key, payload, admin_id=current_admin.id)
    except (CityBusDataError, CityBusNotFoundError) as exc:
        raise_city_bus_error(exc)
    return serialize_route(route)


@router.get("/releases", response_model=list[AdminCityBusReleaseResponse])
def get_city_bus_releases(
    kind: Literal["timetable", "static"] | None = Query(default=None),
    current_admin: User = Depends(get_admin_api_user),
    db: Session = Depends(get_db),
):
    del current_admin
    now = datetime.now(timezone.utc)
    current_ids = {
        snapshot.id
        for release_kind in (KIND_TIMETABLE, KIND_STATIC)
        if (snapshot := city_bus_data.get_effective_release(db, release_kind, now=now)) is not None
    }
    return [
        serialize_release(release, current_ids, now)
        for release in city_bus_data.list_releases(db, kind)
    ]


def _publish(kind: str, payload: AdminCityBusPublishRequest, admin: User, db: Session) -> AdminCityBusReleaseResponse:
    publish = city_bus_data.publish_timetable if kind == KIND_TIMETABLE else city_bus_data.publish_static
    try:
        release = publish(db, admin_id=admin.id, effective_from=payload.effective_from, note=payload.note)
    except (CityBusDataError, CityBusStorageError) as exc:
        raise_city_bus_error(exc)
    now = datetime.now(timezone.utc)
    current = city_bus_data.get_effective_release(db, kind, now=now)
    return serialize_release(release, {current.id} if current else set(), now)


@router.post(
    "/releases/timetable",
    response_model=AdminCityBusReleaseResponse,
    status_code=status.HTTP_201_CREATED,
)
def publish_city_bus_timetable(
    payload: AdminCityBusPublishRequest,
    current_admin: User = Depends(get_admin_api_user),
    db: Session = Depends(get_db),
):
    return _publish(KIND_TIMETABLE, payload, current_admin, db)


@router.post(
    "/releases/static",
    response_model=AdminCityBusReleaseResponse,
    status_code=status.HTTP_201_CREATED,
)
def publish_city_bus_static(
    payload: AdminCityBusPublishRequest,
    current_admin: User = Depends(get_admin_api_user),
    db: Session = Depends(get_db),
):
    return _publish(KIND_STATIC, payload, current_admin, db)


@router.get("/releases/{release_id}/file")
def download_city_bus_release_file(
    release_id: int,
    current_admin: User = Depends(get_admin_api_user),
    db: Session = Depends(get_db),
):
    """게시본 파일. 전환 기간에 깃허브 페이지에 같은 파일을 올릴 때 쓴다."""
    del current_admin
    try:
        release = city_bus_data.get_release(db, release_id)
    except CityBusNotFoundError:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=RELEASE_NOT_FOUND_MESSAGE)

    if release.kind == KIND_STATIC:
        if not release.download_url:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=RELEASE_NOT_FOUND_MESSAGE)
        return RedirectResponse(release.download_url)

    return JSONResponse(
        content=release.payload,
        headers={"Content-Disposition": 'attachment; filename="bus_times.json"'},
    )
