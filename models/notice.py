from sqlalchemy import Column, Integer, String, Text, DateTime, Boolean, Enum
from sqlalchemy.sql import func
from models import Base
import enum

class NoticeType(enum.Enum):
    APP = "App"
    UPDATE = "update"
    SHUTTLE = "shuttle"
    CITYBUS = "citybus"

class Notice(Base):
    __tablename__ = "notices"

    id = Column(Integer, primary_key=True, index=True)
    title = Column(String(255), nullable=False, index=True)
    content = Column(Text, nullable=False)
    notice_type = Column(Enum(NoticeType), nullable=False, default=NoticeType.APP)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    is_pinned = Column(Boolean, default=False) 