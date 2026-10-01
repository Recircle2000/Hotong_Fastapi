from __future__ import annotations

import json
import logging
import time
from datetime import datetime, timezone
from typing import Any

from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from models import AppSetting


logger = logging.getLogger(__name__)

TAXI_ENABLED_KEY = "taxi_enabled"

# 앱이 시작·복귀할 때마다 설정을 읽으므로 DB(Supabase) 왕복을 줄이려고 잠시 캐시한다.
# 워커가 여러 개여도 최대 이 시간 안에 새 값이 반영된다.
_CACHE_TTL_SECONDS = 10.0
_cache: dict[str, tuple[Any, float]] = {}


def clear_app_settings_cache() -> None:
    _cache.clear()


def _get_setting(db: Session, key: str, default: Any) -> Any:
    cached = _cache.get(key)
    if cached is not None and cached[1] > time.monotonic():
        return cached[0]
    try:
        row = db.get(AppSetting, key)
        value = default if row is None else json.loads(row.value)
    except SQLAlchemyError:
        # 배포 순서가 어긋나 테이블이 아직 없을 때도 기존 동작(기본값)으로 계속 서비스한다.
        # 호출하는 쪽은 잠금·쓰기 전에만 읽으므로 되돌려도 잃는 작업이 없다.
        logger.exception("Failed to read app setting %s; using default", key)
        db.rollback()
        value = default
    _cache[key] = (value, time.monotonic() + _CACHE_TTL_SECONDS)
    return value


def _set_setting(db: Session, key: str, value: Any, *, admin_id: int | None) -> AppSetting:
    row = db.get(AppSetting, key)
    encoded = json.dumps(value)
    if row is None:
        row = AppSetting(key=key, value=encoded, updated_by_admin_id=admin_id)
        db.add(row)
    else:
        row.value = encoded
        row.updated_by_admin_id = admin_id
        row.updated_at = datetime.now(timezone.utc)
    db.commit()
    db.refresh(row)
    _cache.pop(key, None)
    return row


def is_taxi_enabled(db: Session) -> bool:
    """택시 서비스 운영 여부. 설정이 없으면 기존처럼 운영 중으로 본다."""
    return bool(_get_setting(db, TAXI_ENABLED_KEY, True))


def set_taxi_enabled(db: Session, enabled: bool, *, admin_id: int | None) -> AppSetting:
    return _set_setting(db, TAXI_ENABLED_KEY, bool(enabled), admin_id=admin_id)


def get_taxi_setting_updated_at(db: Session) -> datetime | None:
    row = db.get(AppSetting, TAXI_ENABLED_KEY)
    return None if row is None else row.updated_at
