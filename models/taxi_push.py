from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import CheckConstraint, Column, DateTime, String, Uuid

from models import Base


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


class TaxiPushToken(Base):
    """택시팟 알림을 받을 기기의 FCM 토큰. 기기 하나는 마지막으로 등록한 계정에만 묶인다."""

    __tablename__ = "taxi_push_tokens"

    token = Column(String(512), primary_key=True)
    user_id = Column(Uuid(as_uuid=True), nullable=False, index=True)
    platform = Column(String(10), nullable=False)
    created_at = Column(DateTime(timezone=True), nullable=False, default=utc_now)
    # 앱이 택시 화면에 들어올 때마다 갱신한다. 오래 갱신되지 않은 토큰은 정리된다.
    updated_at = Column(DateTime(timezone=True), nullable=False, default=utc_now)

    __table_args__ = (
        CheckConstraint("platform in ('android', 'ios')", name="ck_taxi_push_tokens_platform"),
    )
