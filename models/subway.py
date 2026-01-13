from pydantic import BaseModel
from typing import List, Optional, Dict

class SubwayArrivalInfo(BaseModel):
    subwayId: str        # 지하철호선ID
    updnLine: str        # 상하행선구분
    btrainNo: str        # 열차번호 (k + 번호)
    bstatnNm: str     # 도착지방면
    statnNm: str         # 지하철역명
    arvlMsg2: str        # 첫번째도착메세지 (도착, 출발, 진입 등)
    arvlMsg3: str        # 두번째도착메세지 (종합운동장 도착, 12분 후 (광명사거리) 등)
    barvlDt: str         # 열차도착예정시간 (단위:초)
    recptnDt: str        # 열차도착정보를 생성한 시각

class SubwayArrivalResponse(BaseModel):
    station: str
    arrivals: List[SubwayArrivalInfo]

class TrainScheduleInfo(BaseModel):
    trainno: str
    arrival_station: str
    departure_time: str
    is_express: bool

class StationScheduleResponse(BaseModel):
    day_type: str
    station_name: str
    timetable: Dict[str, List[TrainScheduleInfo]]
