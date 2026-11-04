"""시내버스 시간표·노선도 초안 편집과 게시.

대시보드는 city_bus_routes(초안)를 고치고, 게시하면 city_bus_releases에 버전이 하나 쌓인다.
앱은 /api/app-config로 지금 적용 중인 버전을 확인하고, 바뀌었을 때만 내려받는다.
- 시간표: 게시본 JSON을 DB에 담아 /bus-timetable이 그대로 내려준다.
- 노선도: 1.6MB 정도라 Supabase Storage 공개 버킷에 버전별 파일로 올린다.
"""

from __future__ import annotations

import hashlib
import json
import logging
import re
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any
from zoneinfo import ZoneInfo

import httpx
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session, defer

from auth_config import get_supabase_auth_config
from models import CityBusRelease, CityBusRoute


logger = logging.getLogger(__name__)

KIND_TIMETABLE = "timetable"
KIND_STATIC = "static"
RELEASE_KINDS = (KIND_TIMETABLE, KIND_STATIC)

STORAGE_BUCKET = "bus-data"
STATIC_FILE_PREFIX = "bus-static"

KST = ZoneInfo("Asia/Seoul")
ROUTE_KEY_PATTERN = re.compile(r"^[0-9A-Za-z가-힣]+_(UP|DOWN)$")
TIME_PATTERN = re.compile(r"^(\d{1,2}):(\d{2})$")

# 앱 시작·복귀와 버스 위치 루프가 자주 읽으므로 잠시 캐시한다. 게시하면 바로 비운다.
_CACHE_TTL_SECONDS = 10.0
_release_cache: dict[str, tuple[ReleaseSnapshot | None, float]] = {}
# 앱 설정의 변경이력. 게시하면 함께 비운다.
_HISTORY_CACHE_TTL_SECONDS = 60.0
_history_cache: dict[str, tuple[list[dict[str, Any]], float]] = {}
# 시각이 이보다 많이 바뀌면 "07:10 외 6개 추가"처럼 줄인다.
SUMMARY_TIME_LIMIT = 5
NOTE_MAX_LENGTH = 200


class CityBusDataError(ValueError):
    """입력값이 잘못됐을 때. 라우터에서 422로 바꾼다."""


class CityBusNotFoundError(LookupError):
    pass


class CityBusStorageError(RuntimeError):
    """노선도 파일을 Storage에 올리지 못했을 때. 라우터에서 502로 바꾼다."""


@dataclass(frozen=True)
class ReleaseSnapshot:
    id: int
    kind: str
    version: str
    effective_from: datetime | None
    published_at: datetime
    payload: dict[str, Any] | None
    download_url: str | None
    sha256: str | None
    size_bytes: int | None


# 게시할 때마다 1씩 오른다. 같은 프로세스의 버스 위치 루프는 이 값이 바뀌었을 때만 시간표를 다시 확인한다.
_release_generation = 0


@dataclass(frozen=True)
class TimetableCheck:
    version: str | None  # 지금 적용 중인 게시본 버전. 게시본이 없으면 None
    payload: dict[str, Any] | None  # known_version과 다를 때만 채운다
    next_effective_at: datetime | None  # 아직 적용 전인 예약 게시본 중 가장 이른 시각


def clear_city_bus_cache() -> None:
    global _release_generation
    _release_cache.clear()
    _history_cache.clear()
    _release_generation += 1


def release_generation() -> int:
    return _release_generation


def _as_utc(value: datetime | None) -> datetime | None:
    # sqlite(테스트)는 시간대 없이 돌려주므로 저장할 때와 같이 UTC로 본다.
    if value is None:
        return None
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def _effective_at(release: CityBusRelease) -> datetime:
    return _as_utc(release.effective_from) or _as_utc(release.published_at)


def _snapshot(release: CityBusRelease) -> ReleaseSnapshot:
    return ReleaseSnapshot(
        id=release.id,
        kind=release.kind,
        version=release.version,
        effective_from=_as_utc(release.effective_from),
        published_at=_as_utc(release.published_at),
        payload=release.payload,
        download_url=release.download_url,
        sha256=release.sha256,
        size_bytes=release.size_bytes,
    )


# ---------------------------------------------------------------------------
# 검증
# ---------------------------------------------------------------------------

def normalize_route_key(value: str) -> str:
    key = (value or "").strip()
    if not ROUTE_KEY_PATTERN.match(key):
        raise CityBusDataError("노선 키는 '810_UP', '순환5_DOWN'처럼 번호_UP 또는 번호_DOWN 형식이어야 합니다.")
    return key


def normalize_times(values: list[str]) -> list[str]:
    """시각을 HH:MM으로 맞추고 오름차순으로 정렬한다. 형식 오류나 중복은 거절한다."""
    normalized: list[str] = []
    for raw in values:
        match = TIME_PATTERN.match(str(raw).strip())
        if not match:
            raise CityBusDataError(f"시각 형식이 올바르지 않습니다: {raw!r} (HH:MM)")
        hour, minute = int(match.group(1)), int(match.group(2))
        if hour > 23 or minute > 59:
            raise CityBusDataError(f"존재하지 않는 시각입니다: {raw!r}")
        normalized.append(f"{hour:02d}:{minute:02d}")

    duplicates = sorted({value for value in normalized if normalized.count(value) > 1})
    if duplicates:
        raise CityBusDataError(f"중복된 시각이 있습니다: {', '.join(duplicates)}")
    return sorted(normalized)


def validate_route_geojson(value: Any) -> dict[str, Any]:
    if not isinstance(value, dict) or value.get("type") != "FeatureCollection":
        raise CityBusDataError("노선 GeoJSON은 type이 FeatureCollection인 객체여야 합니다.")
    features = value.get("features")
    if not isinstance(features, list) or not features:
        raise CityBusDataError("노선 GeoJSON에 features가 없습니다.")
    return value


def validate_stops_json(value: Any) -> dict[str, Any]:
    try:
        items = value["response"]["body"]["items"]
    except (KeyError, TypeError):
        raise CityBusDataError("정류장 JSON은 공공데이터 응답 형식(response.body.items)이어야 합니다.") from None
    if not items:
        raise CityBusDataError("정류장 JSON에 정류장 목록이 비어 있습니다.")
    return value


def count_geojson_features(value: dict[str, Any] | None) -> int:
    if not isinstance(value, dict):
        return 0
    features = value.get("features")
    return len(features) if isinstance(features, list) else 0


def stop_items(value: dict[str, Any] | None) -> list[dict[str, Any]]:
    """공공데이터 정류장 응답의 정류장 목록. item이 하나뿐이면 객체로 오므로 리스트로 맞춘다."""
    try:
        items = value["response"]["body"]["items"]
    except (KeyError, TypeError):
        return []
    if isinstance(items, dict):
        items = items.get("item")
    if isinstance(items, dict):
        items = [items]
    return [item for item in items if isinstance(item, dict)] if isinstance(items, list) else []


def count_stops(value: dict[str, Any] | None) -> int:
    return len(stop_items(value))


# ---------------------------------------------------------------------------
# 초안 편집
# ---------------------------------------------------------------------------

# 노선 선형·정류장 원본은 노선도를 배포할 때만 필요하다. 나머지 조회에서는 읽지 않는다.
_MAP_DATA_DEFERRED = (defer(CityBusRoute.route_geojson), defer(CityBusRoute.stops_json))


def list_routes(db: Session, *, with_map_data: bool = False) -> list[CityBusRoute]:
    query = db.query(CityBusRoute)
    if not with_map_data:
        query = query.options(*_MAP_DATA_DEFERRED)
    return query.order_by(CityBusRoute.sort_order, CityBusRoute.route_key).all()


def get_route(db: Session, route_key: str) -> CityBusRoute:
    route = db.get(CityBusRoute, route_key, options=_MAP_DATA_DEFERRED)
    if route is None:
        raise CityBusNotFoundError(route_key)
    return route


def create_route(
    db: Session,
    *,
    route_key: str,
    origin: str,
    terminus: str,
    times: list[str],
    admin_id: int | None,
) -> CityBusRoute:
    key = normalize_route_key(route_key)
    if db.get(CityBusRoute, key) is not None:
        raise CityBusDataError(f"이미 있는 노선입니다: {key}")
    last_order = db.query(CityBusRoute.sort_order).order_by(CityBusRoute.sort_order.desc()).first()
    route = CityBusRoute(
        route_key=key,
        sort_order=(last_order[0] + 1) if last_order else 0,
        origin=origin.strip(),
        terminus=terminus.strip(),
        times=normalize_times(times),
        updated_by_admin_id=admin_id,
    )
    db.add(route)
    db.commit()
    db.refresh(route)
    return route


def update_route(
    db: Session,
    route_key: str,
    *,
    origin: str,
    terminus: str,
    times: list[str],
    admin_id: int | None,
) -> CityBusRoute:
    route = get_route(db, route_key)
    route.origin = origin.strip()
    route.terminus = terminus.strip()
    route.times = normalize_times(times)
    route.updated_by_admin_id = admin_id
    route.updated_at = datetime.now(timezone.utc)
    db.commit()
    db.refresh(route)
    return route


def delete_route(db: Session, route_key: str) -> None:
    route = get_route(db, route_key)
    db.delete(route)
    db.commit()


def reorder_routes(db: Session, route_keys: list[str]) -> list[CityBusRoute]:
    routes = {route.route_key: route for route in list_routes(db)}
    if sorted(route_keys) != sorted(routes):
        raise CityBusDataError("노선 순서에는 모든 노선이 한 번씩 들어가야 합니다.")
    for index, key in enumerate(route_keys):
        routes[key].sort_order = index
    db.commit()
    return list_routes(db)


def set_route_geojson(db: Session, route_key: str, value: Any, *, admin_id: int | None) -> CityBusRoute:
    route = get_route(db, route_key)
    route.route_geojson = validate_route_geojson(value)
    route.geojson_feature_count = count_geojson_features(route.route_geojson)
    route.updated_by_admin_id = admin_id
    route.updated_at = datetime.now(timezone.utc)
    db.commit()
    db.refresh(route)
    return route


def set_route_stops(db: Session, route_key: str, value: Any, *, admin_id: int | None) -> CityBusRoute:
    route = get_route(db, route_key)
    route.stops_json = validate_stops_json(value)
    route.stop_count = count_stops(route.stops_json)
    route.updated_by_admin_id = admin_id
    route.updated_at = datetime.now(timezone.utc)
    db.commit()
    db.refresh(route)
    return route


# ---------------------------------------------------------------------------
# 게시본
# ---------------------------------------------------------------------------

def has_timetable(route: CityBusRoute) -> bool:
    # 900번처럼 노선도만 있고 시간표가 없는 노선은 시간표 게시본에서 뺀다.
    return bool(route.origin or route.terminus or route.times)


def build_timetable_payload(routes: list[CityBusRoute], version: str) -> dict[str, Any]:
    """앱과 구버전 앱이 쓰는 bus_times.json 형식 그대로 만든다."""
    payload: dict[str, Any] = {"version": version}
    for route in routes:
        if not has_timetable(route):
            continue
        payload[route.route_key] = {
            "출발지": route.origin,
            "종점": route.terminus,
            "시간표": list(route.times or []),
        }
    return payload


def build_static_payload(routes: list[CityBusRoute], version: str) -> dict[str, Any]:
    """앱의 bus_static_data.json 형식({version, routes, stops})으로 만든다."""
    return {
        "version": version,
        "routes": {route.route_key: route.route_geojson for route in routes if route.route_geojson},
        "stops": {route.route_key: route.stops_json for route in routes if route.stops_json},
    }


def _timetable_content(payload: dict[str, Any] | None) -> dict[str, Any]:
    return {key: value for key, value in (payload or {}).items() if key != "version"}


# ---------------------------------------------------------------------------
# 변경 요약 (앱 설정의 변경이력)
# ---------------------------------------------------------------------------

def route_label(route_key: str) -> str:
    """810_UP → "810 상행", 순환5_DOWN → "순환5 하행"."""
    name, _, direction = route_key.rpartition("_")
    label = {"UP": "상행", "DOWN": "하행"}.get(direction)
    return f"{name} {label}" if name and label else route_key


def _times_phrase(times: list[str], verb: str) -> str:
    if len(times) > SUMMARY_TIME_LIMIT:
        return f"{times[0]} 외 {len(times) - 1}개 {verb}"
    return f"{', '.join(times)} {verb}"


def summarize_timetable_changes(previous: dict[str, Any] | None, current: dict[str, Any]) -> list[str]:
    """두 시간표 게시본(bus_times.json 형식)의 차이를 노선별 한 줄로 만든다."""
    before = _timetable_content(previous)
    after = _timetable_content(current)
    lines: list[str] = []
    for key in list(after) + [key for key in before if key not in after]:
        old, new = before.get(key), after.get(key)
        if old == new:
            continue
        label = route_label(key)
        if old is None:
            lines.append(f"{label} 노선 추가")
            continue
        if new is None:
            lines.append(f"{label} 노선 삭제")
            continue
        parts = []
        if (old.get("출발지"), old.get("종점")) != (new.get("출발지"), new.get("종점")):
            parts.append("출발지·종점 변경")
        old_times, new_times = old.get("시간표", []), new.get("시간표", [])
        added = [value for value in new_times if value not in old_times]
        removed = [value for value in old_times if value not in new_times]
        if added:
            parts.append(_times_phrase(added, "추가"))
        if removed:
            parts.append(_times_phrase(removed, "삭제"))
        if parts:
            lines.append(f"{label}: {', '.join(parts)}")
    return lines


def _json_hash(value: Any) -> str | None:
    if not value:
        return None
    body = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(body).hexdigest()


def route_hashes_for_payload(payload: dict[str, Any]) -> dict[str, dict[str, str | None]]:
    """노선도 파일({routes, stops})에서 노선별 선형·정류장 해시를 만든다."""
    routes = payload.get("routes") or {}
    stops = payload.get("stops") or {}
    return {
        key: {"geojson": _json_hash(routes.get(key)), "stops": _json_hash(stops.get(key))}
        for key in list(routes) + [key for key in stops if key not in routes]
    }


def summarize_static_changes(
    previous: dict[str, dict[str, str | None]] | None,
    current: dict[str, dict[str, str | None]],
) -> list[str]:
    before = previous or {}
    lines: list[str] = []
    for key in list(current) + [key for key in before if key not in current]:
        old, new = before.get(key), current.get(key)
        if old == new:
            continue
        label = route_label(key)
        if old is None:
            lines.append(f"{label} 노선 추가")
        elif new is None:
            lines.append(f"{label} 노선 삭제")
        else:
            parts = [name for part, name in (("geojson", "노선 선형"), ("stops", "정류장")) if old.get(part) != new.get(part)]
            lines.append(f"{label}: {'·'.join(parts)} 변경")
    return lines


def _previous_static_hashes(release: CityBusRelease | None) -> dict[str, dict[str, str | None]] | None:
    """직전 노선도 게시본의 노선별 해시. 이관 때 등록한 게시본처럼 해시가 없으면 Storage 파일로 계산한다."""
    if release is None:
        return None
    if release.route_hashes:
        return release.route_hashes
    if not release.download_url:
        return None
    try:
        response = httpx.get(release.download_url, timeout=30.0)
        response.raise_for_status()
        return route_hashes_for_payload(json.loads(response.content.decode("utf-8")))
    except (httpx.HTTPError, ValueError):
        logger.warning("Failed to read previous city bus static file %s", release.download_url, exc_info=True)
        return None


def normalize_note(note: str | None) -> str | None:
    value = (note or "").strip()
    if len(value) > NOTE_MAX_LENGTH:
        raise CityBusDataError(f"변경 메모는 {NOTE_MAX_LENGTH}자까지 쓸 수 있습니다.")
    return value or None


def list_public_history(db: Session, kind: str, *, limit: int = 30, now: datetime | None = None) -> list[dict[str, Any]]:
    """앱 설정의 변경이력. 이미 적용된 게시본만 최신순으로 돌려준다(예약분은 적용 시각 전에는 숨긴다)."""
    use_cache = now is None
    if use_cache:
        cached = _history_cache.get(kind)
        if cached is not None and cached[1] > time.monotonic():
            return cached[0]

    current = _as_utc(now) or datetime.now(timezone.utc)
    releases = (
        db.query(CityBusRelease)
        .options(defer(CityBusRelease.payload), defer(CityBusRelease.route_hashes))
        .filter(CityBusRelease.kind == kind)
        .all()
    )
    applied = sorted(
        (release for release in releases if _effective_at(release) <= current),
        key=lambda release: (_effective_at(release), release.id),
        reverse=True,
    )[:limit]
    items = [
        {
            "version": release.version,
            "effective_at": _effective_at(release),
            "note": release.note,
            "changes": release.changes,
        }
        for release in applied
    ]
    if use_cache:
        _history_cache[kind] = (items, time.monotonic() + _HISTORY_CACHE_TTL_SECONDS)
    return items


def list_releases(db: Session, kind: str | None = None) -> list[CityBusRelease]:
    query = db.query(CityBusRelease).options(defer(CityBusRelease.payload))
    if kind:
        query = query.filter(CityBusRelease.kind == kind)
    return query.order_by(CityBusRelease.id.desc()).all()


def get_release(db: Session, release_id: int) -> CityBusRelease:
    release = db.get(CityBusRelease, release_id)
    if release is None:
        raise CityBusNotFoundError(str(release_id))
    return release


def _pick_effective_release(releases: list[CityBusRelease], now: datetime) -> CityBusRelease | None:
    effective = [release for release in releases if _effective_at(release) <= now]
    if not effective:
        return None
    # 예약 게시가 섞여 있어도 가장 늦게 적용되기 시작한 게시본이 지금 버전이다.
    return max(effective, key=lambda release: (_effective_at(release), release.id))


def _find_effective_release(db: Session, kind: str, now: datetime) -> CityBusRelease | None:
    releases = (
        db.query(CityBusRelease)
        .options(defer(CityBusRelease.payload))
        .filter(CityBusRelease.kind == kind)
        .all()
    )
    return _pick_effective_release(releases, now)


def check_effective_timetable(
        db: Session,
        known_version: str | None,
        *,
        now: datetime | None = None,
) -> TimetableCheck:
    """버스 위치 루프용. 적용 중인 버전이 known_version과 같으면 시간표 내용은 읽지 않는다.

    DB 오류는 그대로 올린다 (호출하는 쪽이 지금 시간표를 계속 쓴다).
    """
    current = _as_utc(now) or datetime.now(timezone.utc)
    releases = (
        db.query(CityBusRelease)
        .options(defer(CityBusRelease.payload), defer(CityBusRelease.route_hashes))
        .filter(CityBusRelease.kind == KIND_TIMETABLE)
        .all()
    )
    next_effective_at = min(
        (_effective_at(release) for release in releases if _effective_at(release) > current),
        default=None,
    )
    release = _pick_effective_release(releases, current)
    if release is None:
        return TimetableCheck(version=None, payload=None, next_effective_at=next_effective_at)
    payload = None
    if release.version != known_version:
        db.refresh(release, attribute_names=["payload"])
        payload = release.payload
    return TimetableCheck(version=release.version, payload=payload, next_effective_at=next_effective_at)


def get_effective_release(db: Session, kind: str, *, now: datetime | None = None) -> ReleaseSnapshot | None:
    """지금 앱에 내려가야 하는 게시본. 없으면 None (호출하는 쪽이 예전 경로로 넘어간다)."""
    use_cache = now is None
    if use_cache:
        cached = _release_cache.get(kind)
        if cached is not None and cached[1] > time.monotonic():
            return cached[0]

    current = _as_utc(now) or datetime.now(timezone.utc)
    try:
        release = _find_effective_release(db, kind, current)
        snapshot = None
        if release is not None:
            # payload는 고른 한 건만 읽는다.
            db.refresh(release, attribute_names=["payload"])
            snapshot = _snapshot(release)
    except SQLAlchemyError:
        # 배포 순서가 어긋나 테이블이 아직 없어도 예전 경로로 계속 서비스한다.
        logger.exception("Failed to read city bus %s release", kind)
        db.rollback()
        snapshot = None

    if use_cache:
        _release_cache[kind] = (snapshot, time.monotonic() + _CACHE_TTL_SECONDS)
    return snapshot


def next_version(db: Session, kind: str, effective_at: datetime) -> str:
    """적용일(한국 시간) 기준 YYYY.MM.DD, 같은 날 두 번째부터는 .2, .3을 붙인다.

    앱은 날짜 형식이 아니면 문자열로 비교하므로 '2026.11.04.2' > '2026.11.04'가 성립한다.
    """
    base = effective_at.astimezone(KST).strftime("%Y.%m.%d")
    existing = {
        version
        for (version,) in db.query(CityBusRelease.version).filter(CityBusRelease.kind == kind).all()
    }
    if base not in existing:
        return base
    suffix = 2
    while f"{base}.{suffix}" in existing:
        suffix += 1
    return f"{base}.{suffix}"


def _resolve_effective_from(effective_from: datetime | None, now: datetime) -> datetime | None:
    value = _as_utc(effective_from)
    # 과거 시각으로 예약하면 즉시 게시와 같다.
    if value is None or value <= now:
        return None
    return value


def publish_timetable(
    db: Session,
    *,
    admin_id: int | None,
    effective_from: datetime | None = None,
    note: str | None = None,
    now: datetime | None = None,
) -> CityBusRelease:
    current = _as_utc(now) or datetime.now(timezone.utc)
    routes = [route for route in list_routes(db) if has_timetable(route)]
    if not routes:
        raise CityBusDataError("게시할 시간표가 있는 노선이 없습니다.")
    for route in routes:
        if not route.origin or not route.terminus:
            raise CityBusDataError(f"{route.route_key} 노선의 출발지·종점을 채워 주세요.")

    latest = (
        db.query(CityBusRelease)
        .filter(CityBusRelease.kind == KIND_TIMETABLE)
        .order_by(CityBusRelease.id.desc())
        .first()
    )
    draft_content = _timetable_content(build_timetable_payload(routes, ""))
    if latest is not None and _timetable_content(latest.payload) == draft_content:
        raise CityBusDataError("마지막 게시본과 달라진 내용이 없습니다.")

    note = normalize_note(note)
    scheduled = _resolve_effective_from(effective_from, current)
    version = next_version(db, KIND_TIMETABLE, scheduled or current)
    payload = build_timetable_payload(routes, version)
    release = CityBusRelease(
        kind=KIND_TIMETABLE,
        version=version,
        effective_from=scheduled,
        payload=payload,
        published_at=current,
        published_by_admin_id=admin_id,
        note=note,
        changes=None if latest is None else summarize_timetable_changes(latest.payload, payload),
    )
    db.add(release)
    db.commit()
    db.refresh(release)
    clear_city_bus_cache()
    return release


def storage_public_url(path: str) -> str:
    project_url = get_supabase_auth_config().project_url
    return f"{project_url}/storage/v1/object/public/{STORAGE_BUCKET}/{path}"


def upload_to_storage(path: str, body: bytes, *, content_type: str = "application/json") -> str:
    """bus-data 버킷에 파일을 올리고 공개 URL을 돌려준다. 같은 경로가 있으면 실패한다."""
    config = get_supabase_auth_config()
    if not config.service_role_key:
        raise CityBusStorageError("SUPABASE_SERVICE_ROLE_KEY가 없어 파일을 올릴 수 없습니다.")
    try:
        response = httpx.post(
            f"{config.project_url}/storage/v1/object/{STORAGE_BUCKET}/{path}",
            content=body,
            headers={
                "Authorization": f"Bearer {config.service_role_key}",
                "apikey": config.service_role_key,
                "Content-Type": content_type,
                # 버전마다 경로가 달라 파일이 바뀌지 않으므로 오래 캐시해도 된다.
                "Cache-Control": "max-age=31536000",
                "x-upsert": "false",
            },
            timeout=30.0,
        )
    except httpx.HTTPError as exc:
        raise CityBusStorageError(f"Storage 업로드 요청 실패: {exc}") from exc
    if response.status_code >= 400:
        raise CityBusStorageError(f"Storage 업로드 실패 ({response.status_code}): {response.text[:200]}")
    return storage_public_url(path)


def encode_static_payload(payload: dict[str, Any]) -> bytes:
    return json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode("utf-8")


def create_static_release(
    db: Session,
    *,
    version: str,
    body: bytes,
    effective_from: datetime | None,
    published_at: datetime,
    admin_id: int | None,
    note: str | None = None,
    changes: list[str] | None = None,
    route_hashes: dict[str, dict[str, str | None]] | None = None,
) -> CityBusRelease:
    """파일을 Storage에 올린 뒤에만 게시본을 기록한다. 업로드가 실패하면 아무것도 남기지 않는다."""
    url = upload_to_storage(f"{STATIC_FILE_PREFIX}/{version}.json", body)
    release = CityBusRelease(
        kind=KIND_STATIC,
        version=version,
        effective_from=effective_from,
        payload=None,
        download_url=url,
        sha256=hashlib.sha256(body).hexdigest(),
        size_bytes=len(body),
        published_at=published_at,
        published_by_admin_id=admin_id,
        note=note,
        changes=changes,
        route_hashes=route_hashes,
    )
    db.add(release)
    db.commit()
    db.refresh(release)
    clear_city_bus_cache()
    return release


def publish_static(
    db: Session,
    *,
    admin_id: int | None,
    effective_from: datetime | None = None,
    note: str | None = None,
    now: datetime | None = None,
) -> CityBusRelease:
    current = _as_utc(now) or datetime.now(timezone.utc)
    routes = list_routes(db, with_map_data=True)
    if not any(route.route_geojson or route.stops_json for route in routes):
        raise CityBusDataError("노선도나 정류장 데이터가 있는 노선이 없습니다.")

    note = normalize_note(note)
    scheduled = _resolve_effective_from(effective_from, current)
    version = next_version(db, KIND_STATIC, scheduled or current)
    payload = build_static_payload(routes, version)
    hashes = route_hashes_for_payload(payload)
    latest = (
        db.query(CityBusRelease)
        .options(defer(CityBusRelease.payload))
        .filter(CityBusRelease.kind == KIND_STATIC)
        .order_by(CityBusRelease.id.desc())
        .first()
    )
    previous_hashes = _previous_static_hashes(latest)
    return create_static_release(
        db,
        version=version,
        body=encode_static_payload(payload),
        effective_from=scheduled,
        published_at=current,
        admin_id=admin_id,
        note=note,
        changes=None if previous_hashes is None else summarize_static_changes(previous_hashes, hashes),
        route_hashes=hashes,
    )


def latest_release_published_at(db: Session, kind: str) -> datetime | None:
    row = (
        db.query(CityBusRelease.published_at)
        .filter(CityBusRelease.kind == kind)
        .order_by(CityBusRelease.id.desc())
        .first()
    )
    return _as_utc(row[0]) if row else None
