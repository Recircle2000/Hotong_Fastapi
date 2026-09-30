from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import CheckConstraint, Column, DateTime, ForeignKey, Integer, String, Text, Uuid

from models import Base


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


TAXI_SANCTION_LEVELS = ("warning", "suspend_3d", "suspend_7d", "permanent")


class TaxiSanction(Base):
    """신고 검토 후 관리자가 부과한 택시팟 제재. 정지 중에는 새 팟 생성과 참여를 막는다."""

    __tablename__ = "taxi_sanctions"

    id = Column(Integer, primary_key=True)
    user_id = Column(Uuid(as_uuid=True), nullable=False, index=True)
    level = Column(String(20), nullable=False)
    # 사용자에게 그대로 보여주는 사유
    reason = Column(String(300), nullable=False)
    admin_note = Column(Text, nullable=True)
    starts_at = Column(DateTime(timezone=True), nullable=False)
    # 경고와 영구 정지는 끝나는 시각이 없다.
    ends_at = Column(DateTime(timezone=True), nullable=True)
    created_by_admin_id = Column(Integer, ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    created_at = Column(DateTime(timezone=True), nullable=False, default=utc_now)
    acknowledged_at = Column(DateTime(timezone=True), nullable=True)
    revoked_at = Column(DateTime(timezone=True), nullable=True)
    revoked_by_admin_id = Column(Integer, ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    revoke_reason = Column(String(300), nullable=True)

    __table_args__ = (
        CheckConstraint(
            "level in ('warning', 'suspend_3d', 'suspend_7d', 'permanent')",
            name="ck_taxi_sanctions_level",
        ),
    )
