import enum
from datetime import datetime, timedelta, timezone

from sqlalchemy import Column, DateTime, Enum, Integer, String, Text

from models import Base


KST = timezone(timedelta(hours=9))


def get_now_kst_naive() -> datetime:
    return datetime.now(KST).replace(tzinfo=None)


class EmergencyNoticeCategory(str, enum.Enum):
    SHUTTLE = "shuttle"
    ASAN_CITYBUS = "asan_citybus"
    CHEONAN_CITYBUS = "cheonan_citybus"
    SUBWAY = "subway"


class EmergencyNotice(Base):
    __tablename__ = "emergency_notices"

    id = Column(Integer, primary_key=True, index=True)
    category = Column(
        Enum(
            EmergencyNoticeCategory,
            name="emergencynoticecategory",
            values_callable=lambda x: [e.value for e in x],
        ),
        nullable=False,
        index=True,
    )
    title = Column(String(255), nullable=False)
    content = Column(Text, nullable=False)
    created_at = Column(DateTime, nullable=False, default=get_now_kst_naive)
    end_at = Column(DateTime, nullable=False, index=True)
