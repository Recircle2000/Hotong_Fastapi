from sqlalchemy import Column, Integer, String, Boolean
from . import Base

class SubwaySchedule(Base):
    __tablename__ = "subway_schedules"

    id = Column(Integer, primary_key=True, index=True)
    train_no = Column(String(20), index=True)      # trainno
    up_down_type = Column(String(10))              # upbdnbSe (상행/하행)
    day_type = Column(String(10))                  # wkndSe (평일/토요일/휴일)
    line_name = Column(String(20))                 # lineNm (1호선)
    branch_name = Column(String(20))               # brlnNm (경부선 등)
    station_name = Column(String(50))              # stnNm
    departure_station = Column(String(50))         # dptreStnNm
    arrival_station = Column(String(50))           # arvlStnNm
    departure_time = Column(String(10))            # trainDptreTm (HH:MM:SS)
    arrival_time = Column(String(10))              # trainArvlTm (HH:MM:SS)
    is_express = Column(Boolean, default=False)    # 급행 여부
