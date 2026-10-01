from fastapi import APIRouter, Depends, Response
from sqlalchemy.orm import Session

from database import get_db
from schemas.app_config import AppConfigResponse
from services.app_settings import is_taxi_enabled


router = APIRouter(prefix="/api", tags=["App Config"])


@router.get("/app-config", response_model=AppConfigResponse)
def get_app_config(response: Response, db: Session = Depends(get_db)):
    """로그인 없이 읽는 앱 기능 스위치. 앱이 시작·복귀할 때 메뉴 구성을 정한다."""
    response.headers["Cache-Control"] = "no-store"
    return AppConfigResponse(taxi_enabled=is_taxi_enabled(db))
