from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import CheckConstraint, Column, DateTime, Integer, String, Uuid

from models import Base


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


class PushDevice(Base):
    """앱 설치본 하나의 FCM 토큰. 토큰은 기기에 하나라 다른 계정으로 로그인하면 주인이 바뀐다."""

    __tablename__ = "push_devices"

    id = Column(Integer, primary_key=True)
    user_id = Column(Uuid(as_uuid=True), nullable=False, index=True)
    token = Column(String(512), nullable=False, unique=True)
    platform = Column(String(20), nullable=False)
    created_at = Column(DateTime(timezone=True), nullable=False, default=utc_now)
    updated_at = Column(DateTime(timezone=True), nullable=False, default=utc_now, onupdate=utc_now)

    __table_args__ = (
        CheckConstraint("platform in ('android', 'ios')", name="ck_push_devices_platform"),
    )
