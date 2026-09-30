from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import Column, DateTime, Integer, String, Text

from models import Base


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


class AppSetting(Base):
    """운영 중에 관리자 대시보드에서 바꾸는 앱 설정(key-value, 값은 JSON 문자열)."""

    __tablename__ = "app_settings"

    key = Column(String(64), primary_key=True)
    value = Column(Text, nullable=False)
    updated_at = Column(DateTime(timezone=True), nullable=False, default=utc_now, onupdate=utc_now)
    updated_by_admin_id = Column(Integer, nullable=True)
