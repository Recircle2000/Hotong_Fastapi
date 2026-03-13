from datetime import datetime

from fastapi import HTTPException, status
from sqlalchemy.orm import Session

from models.emergency_notice import EmergencyNotice, EmergencyNoticeCategory
from services.dashboard_utils import get_now_kst_naive

INVALID_TIME_RANGE_MESSAGE = "생성 시각은 종료 시각보다 늦을 수 없습니다."
EMERGENCY_NOTICE_NOT_FOUND_MESSAGE = "긴급공지 정보를 찾을 수 없습니다."
INVALID_EMERGENCY_NOTICE_CATEGORY_MESSAGE = "유효하지 않은 구분 값입니다."

EMERGENCY_NOTICE_CATEGORY_LABELS = {
    EmergencyNoticeCategory.SHUTTLE: "셔틀 긴급공지",
    EmergencyNoticeCategory.ASAN_CITYBUS: "아산 시내버스 긴급공지",
    EmergencyNoticeCategory.CHEONAN_CITYBUS: "천안 시내버스 긴급공지",
    EmergencyNoticeCategory.SUBWAY: "지하철 긴급공지",
}


def parse_emergency_notice_category(category: str | EmergencyNoticeCategory) -> EmergencyNoticeCategory:
    if isinstance(category, EmergencyNoticeCategory):
        return category

    try:
        return EmergencyNoticeCategory(category)
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=INVALID_EMERGENCY_NOTICE_CATEGORY_MESSAGE,
        ) from exc


def get_emergency_notice_status(
    notice: EmergencyNotice,
    now_kst: datetime | None = None,
) -> str:
    current_time = now_kst or get_now_kst_naive()
    if notice.created_at > current_time:
        return "pending"
    if notice.end_at >= current_time:
        return "active"
    return "expired"


def serialize_emergency_notice(
    notice: EmergencyNotice,
    now_kst: datetime | None = None,
) -> dict[str, object]:
    category = parse_emergency_notice_category(notice.category)
    return {
        "id": notice.id,
        "category": category.value,
        "category_label": EMERGENCY_NOTICE_CATEGORY_LABELS[category],
        "title": notice.title,
        "content": notice.content,
        "created_at": notice.created_at,
        "end_at": notice.end_at,
        "status": get_emergency_notice_status(notice, now_kst=now_kst),
    }


def list_admin_emergency_notices(db: Session) -> list[EmergencyNotice]:
    return db.query(EmergencyNotice).order_by(EmergencyNotice.created_at.desc()).all()


def create_admin_emergency_notice(
    db: Session,
    *,
    category: str | EmergencyNoticeCategory,
    title: str,
    content: str,
    created_at: datetime | None,
    end_at: datetime,
) -> EmergencyNotice:
    category_enum = parse_emergency_notice_category(category)
    created_at_value = created_at or get_now_kst_naive()
    if created_at_value > end_at:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=INVALID_TIME_RANGE_MESSAGE,
        )

    notice = EmergencyNotice(
        category=category_enum,
        title=title.strip(),
        content=content.strip(),
        created_at=created_at_value,
        end_at=end_at,
    )
    db.add(notice)
    db.commit()
    db.refresh(notice)
    return notice


def update_admin_emergency_notice(
    db: Session,
    *,
    notice_id: int,
    category: str | EmergencyNoticeCategory,
    title: str,
    content: str,
    created_at: datetime,
    end_at: datetime,
) -> EmergencyNotice:
    notice = db.query(EmergencyNotice).filter(EmergencyNotice.id == notice_id).first()
    if notice is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=EMERGENCY_NOTICE_NOT_FOUND_MESSAGE,
        )

    category_enum = parse_emergency_notice_category(category)
    if created_at > end_at:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=INVALID_TIME_RANGE_MESSAGE,
        )

    notice.category = category_enum
    notice.title = title.strip()
    notice.content = content.strip()
    notice.created_at = created_at
    notice.end_at = end_at
    db.commit()
    db.refresh(notice)
    return notice


def delete_admin_emergency_notice(db: Session, *, notice_id: int) -> bool:
    notice = db.query(EmergencyNotice).filter(EmergencyNotice.id == notice_id).first()
    if notice is None:
        return False

    db.delete(notice)
    db.commit()
    return True
