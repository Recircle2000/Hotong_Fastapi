from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import (
    JSON,
    CheckConstraint,
    Column,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    Uuid,
)
from sqlalchemy.dialects.postgresql import JSONB

from models import Base


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


TAXI_REPORT_REASONS = ("no_show", "abuse", "payment", "other")
TAXI_REPORT_STATUSES = ("pending", "resolved", "dismissed")


class TaxiReport(Base):
    """택시팟 참여자 신고. 채팅은 48시간 뒤 지워지므로 신고 시점의 채팅을 증거로 저장한다."""

    __tablename__ = "taxi_reports"

    id = Column(Integer, primary_key=True)
    party_id = Column(
        Uuid(as_uuid=True),
        ForeignKey("taxi_parties.id", ondelete="SET NULL"),
        nullable=True,
    )
    reporter_id = Column(Uuid(as_uuid=True), nullable=False, index=True)
    target_id = Column(Uuid(as_uuid=True), nullable=False, index=True)
    # 신고 당시 앱에 보이던 익명 라벨(방장 / 참여자 N)
    target_label = Column(String(20), nullable=False)
    reason = Column(String(20), nullable=False)
    detail = Column(String(500), nullable=True)
    # 메시지는 보관 기한이 지나면 지워지므로 FK를 걸지 않는다.
    message_id = Column(Integer, nullable=True)
    evidence = Column(JSON().with_variant(JSONB(), "postgresql"), nullable=True)
    status = Column(String(20), nullable=False, default="pending", server_default="pending")
    admin_note = Column(Text, nullable=True)
    reviewed_by_admin_id = Column(Integer, ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    reviewed_at = Column(DateTime(timezone=True), nullable=True)
    evidence_purged_at = Column(DateTime(timezone=True), nullable=True)
    created_at = Column(DateTime(timezone=True), nullable=False, default=utc_now)

    __table_args__ = (
        UniqueConstraint("party_id", "reporter_id", "target_id", name="uq_taxi_reports_once_per_target"),
        CheckConstraint(
            "reason in ('no_show', 'abuse', 'payment', 'other')",
            name="ck_taxi_reports_reason",
        ),
        CheckConstraint(
            "status in ('pending', 'resolved', 'dismissed')",
            name="ck_taxi_reports_status",
        ),
        Index("ix_taxi_reports_status_created", "status", "created_at"),
    )
