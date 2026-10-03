from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import Column, DateTime, Integer, Uuid

from models import Base


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


class TaxiTermsAgreement(Base):
    """택시팟 이용약관에 동의한 기록. 사용자마다 마지막으로 동의한 버전 하나만 둔다."""

    __tablename__ = "taxi_terms_agreements"

    user_id = Column(Uuid(as_uuid=True), primary_key=True)
    version = Column(Integer, nullable=False)
    agreed_at = Column(DateTime(timezone=True), nullable=False, default=utc_now)
