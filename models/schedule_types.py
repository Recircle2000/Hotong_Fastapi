from sqlalchemy import Column, Integer, String, Boolean, Date, ForeignKey
from sqlalchemy.orm import relationship
from models import Base

class ScheduleType(Base):
    __tablename__ = "schedule_types"

    id = Column(Integer, primary_key=True, index=True)
    schedule_type = Column(String(50), nullable=False, unique=True)
    schedule_type_name = Column(String(50), nullable=False, unique=True)
    is_activate = Column(Boolean, default=True)
    
    # 역참조 관계 설정
    exceptions = relationship("ScheduleException", back_populates="schedule_type_rel")

class ScheduleException(Base):
    __tablename__ = "schedule_exceptions"

    id = Column(Integer, primary_key=True, index=True)
    start_date = Column(Date, nullable=False)
    end_date = Column(Date, nullable=False)
    schedule_type = Column(String(50), ForeignKey("schedule_types.schedule_type"), nullable=False)
    reason = Column(String(255), nullable=True)
    is_activate = Column(Boolean, default=False)
    # 관계 설정
    schedule_type_rel = relationship("ScheduleType", back_populates="exceptions") 