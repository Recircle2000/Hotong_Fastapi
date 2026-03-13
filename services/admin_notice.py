from datetime import datetime
from typing import Any

from sqlalchemy.orm import Session

from models.notice import Notice, NoticeType
from schemas.admin_v2 import AdminNoticeResponse


def normalize_notice_type(value: str | None) -> NoticeType:
    try:
        return NoticeType(value or NoticeType.APP.value)
    except ValueError:
        return NoticeType.APP


def coerce_is_pinned(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    if value is None:
        return False
    if isinstance(value, str):
        return value.strip().lower() in {"1", "true", "on", "yes"}
    return bool(value)


def list_admin_notices(db: Session) -> list[Notice]:
    return db.query(Notice).order_by(Notice.is_pinned.desc(), Notice.created_at.desc()).all()


def create_admin_notice(
    db: Session,
    *,
    title: str,
    content: str,
    notice_type: str | None = None,
    is_pinned: Any = False,
) -> Notice:
    notice = Notice(
        title=title,
        content=content,
        notice_type=normalize_notice_type(notice_type),
        is_pinned=coerce_is_pinned(is_pinned),
        created_at=datetime.now(),
    )
    db.add(notice)
    db.commit()
    db.refresh(notice)
    return notice


def update_admin_notice(
    db: Session,
    *,
    notice_id: int,
    title: str,
    content: str,
    notice_type: str | None = None,
    is_pinned: Any = False,
) -> Notice | None:
    notice = db.query(Notice).filter(Notice.id == notice_id).first()
    if not notice:
        return None

    notice.title = title
    notice.content = content
    notice.notice_type = normalize_notice_type(notice_type)
    notice.is_pinned = coerce_is_pinned(is_pinned)
    db.commit()
    db.refresh(notice)
    return notice


def delete_admin_notice(db: Session, *, notice_id: int) -> bool:
    notice = db.query(Notice).filter(Notice.id == notice_id).first()
    if not notice:
        return False
    db.delete(notice)
    db.commit()
    return True


def serialize_notice(notice: Notice) -> AdminNoticeResponse:
    return AdminNoticeResponse(
        id=notice.id,
        title=notice.title,
        content=notice.content,
        notice_type=notice.notice_type.value if notice.notice_type else NoticeType.APP.value,
        is_pinned=bool(notice.is_pinned),
        created_at=notice.created_at,
    )
