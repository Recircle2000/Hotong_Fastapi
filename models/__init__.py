from sqlalchemy.orm import declarative_base

Base = declarative_base()

# 각 모델을 import하여 Base에 등록
from .user import User
from .bus import BusRoute, BusLocation
from .shuttle import ShuttleStation, ShuttleRoute, ShuttleStationRoute
from .notice import Notice
from .emergency_notice import EmergencyNotice
from .schedule_types import ScheduleType, ScheduleException
from .subway_schedule import SubwaySchedule
from .taxi import TaxiLocation, TaxiMessage, TaxiParty, TaxiPartyMember
from .app_setting import AppSetting
from .taxi_sanction import TaxiSanction, TaxiSanctionHold
from .taxi_report import TaxiReport
from .taxi_push import TaxiPushToken
