from sqlalchemy.orm import declarative_base

Base = declarative_base()

# 각 모델을 import하여 Base에 등록
from .user import User
from .bus import BusRoute, BusLocation
from .shuttle import ShuttleStation, ShuttleRoute, ShuttleStationRoute
