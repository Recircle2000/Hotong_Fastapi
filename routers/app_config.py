from typing import Literal

from fastapi import APIRouter, Depends, Query, Response
from sqlalchemy.orm import Session

from database import get_db
from schemas.app_config import AppConfigResponse, BusDataConfig, BusDataHistoryItem, BusDataRelease
from services.app_settings import is_taxi_enabled
from services.city_bus_data import KIND_STATIC, KIND_TIMETABLE, get_effective_release, list_public_history


router = APIRouter(prefix="/api", tags=["App Config"])

TIMETABLE_DOWNLOAD_PATH = "/bus-timetable"


def build_bus_data_config(db: Session) -> BusDataConfig:
    timetable = get_effective_release(db, KIND_TIMETABLE)
    static = get_effective_release(db, KIND_STATIC)
    return BusDataConfig(
        timetable=None if timetable is None else BusDataRelease(
            version=timetable.version,
            download_url=TIMETABLE_DOWNLOAD_PATH,
            effective_from=timetable.effective_from,
        ),
        static=None if static is None or not static.download_url else BusDataRelease(
            version=static.version,
            download_url=static.download_url,
            effective_from=static.effective_from,
            sha256=static.sha256,
        ),
    )


@router.get("/app-config", response_model=AppConfigResponse)
def get_app_config(response: Response, db: Session = Depends(get_db)):
    """로그인 없이 읽는 앱 설정. 앱이 시작·복귀할 때 메뉴 구성과 시내버스 데이터 버전을 정한다."""
    response.headers["Cache-Control"] = "no-store"
    return AppConfigResponse(
        taxi_enabled=is_taxi_enabled(db),
        bus_data=build_bus_data_config(db),
    )


@router.get("/bus-data/history", response_model=list[BusDataHistoryItem])
def get_bus_data_history(
    response: Response,
    kind: Literal["timetable", "static"] = Query(...),
    db: Session = Depends(get_db),
):
    """앱 설정에서 보는 시내버스 시간표·노선 변경이력. 이미 적용된 게시본만 최신순으로."""
    response.headers["Cache-Control"] = "public, max-age=60"
    return list_public_history(db, kind)
