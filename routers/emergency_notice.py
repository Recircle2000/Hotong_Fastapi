from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends
from pydantic import BaseModel, ConfigDict
from sqlalchemy.orm import Session

from database import get_db
from models.emergency_notice import EmergencyNotice, EmergencyNoticeCategory


KST = timezone(timedelta(hours=9))

router = APIRouter(
    prefix="/emergency-notices",
    tags=["Emergency Notices"],
)


def get_now_kst_naive() -> datetime:
    return datetime.now(KST).replace(tzinfo=None)


class EmergencyNoticeResponse(BaseModel):
    id: int
    category: EmergencyNoticeCategory
    title: str
    content: str
    created_at: datetime
    end_at: datetime

    model_config = ConfigDict(from_attributes=True)


@router.get("/latest", response_model=EmergencyNoticeResponse | None)
def get_latest_emergency_notice(
    category: EmergencyNoticeCategory,
    db: Session = Depends(get_db),
):
    now_kst = get_now_kst_naive()
    notice = (
        db.query(EmergencyNotice)
        .filter(
            EmergencyNotice.category == category,
            EmergencyNotice.end_at >= now_kst,
        )
        .order_by(EmergencyNotice.created_at.desc())
        .first()
    )
    return notice
