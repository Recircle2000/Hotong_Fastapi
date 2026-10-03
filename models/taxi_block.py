from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import Column, DateTime, ForeignKey, Integer, String, UniqueConstraint, Uuid

from models import Base


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


class TaxiBlock(Base):
    """다른 참여자를 차단한 기록. 차단하면 서로의 팟에서 다시 만나지 않는다."""

    __tablename__ = "taxi_blocks"

    id = Column(Integer, primary_key=True)
    blocker_id = Column(Uuid(as_uuid=True), nullable=False, index=True)
    blocked_id = Column(Uuid(as_uuid=True), nullable=False, index=True)
    party_id = Column(
        Uuid(as_uuid=True),
        ForeignKey("taxi_parties.id", ondelete="SET NULL"),
        nullable=True,
    )
    # 팟이 보관 기한이 지나 지워져도 차단 목록에 보여줄 수 있게 차단 당시 정보를 남긴다.
    target_label = Column(String(20), nullable=False)
    departure_name = Column(String(80), nullable=False)
    destination_name = Column(String(80), nullable=False)
    departure_at = Column(DateTime(timezone=True), nullable=False)
    created_at = Column(DateTime(timezone=True), nullable=False, default=utc_now)

    __table_args__ = (
        UniqueConstraint("blocker_id", "blocked_id", name="uq_taxi_blocks_pair"),
    )
