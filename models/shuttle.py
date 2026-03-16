from sqlalchemy import Boolean, Column, Double, Enum, ForeignKey, Integer, String, Time, text
from sqlalchemy.orm import relationship
from models import Base

class ShuttleStation(Base):
    __tablename__ = "shuttle_stations"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String(255), nullable=False)
    latitude = Column(Double, nullable=False)
    longitude = Column(Double, nullable=False)
    description = Column(String(500), nullable=True)
    image_url = Column(String(500), nullable=True)
    is_active = Column(Boolean, nullable=False, default=True, server_default=text("1"))
    routes = relationship("ShuttleRoute", secondary="shuttle_station_routes", back_populates="stations")

class ShuttleRoute(Base):
    __tablename__ = "shuttle_routes"

    id = Column(Integer, primary_key=True, index=True)
    route_name = Column(String(255), nullable=False)
    direction = Column(Enum('UP', 'DOWN', name='direction_enum'), nullable=False)
    description = Column(String(500), nullable=True)
    
    stations = relationship("ShuttleStation", secondary="shuttle_station_routes", back_populates="routes")
    schedules = relationship("Schedule", back_populates="route")

class ShuttleStationRoute(Base):
    __tablename__ = "shuttle_station_routes"

    id = Column(Integer, primary_key=True, index=True)
    station_id = Column(Integer, ForeignKey("shuttle_stations.id", ondelete="CASCADE"))
    route_id = Column(Integer, ForeignKey("shuttle_routes.id", ondelete="CASCADE"))

class Schedule(Base):
    __tablename__ = "schedules"

    id = Column(Integer, primary_key=True, index=True)
    route_id = Column(Integer, ForeignKey("shuttle_routes.id", ondelete="CASCADE"))
    schedule_type = Column(String(20), nullable=False)  # 'weekday', 'weekend', 'holiday', 'special'
    start_time = Column(Time, nullable=False)
    end_time = Column(Time, nullable=False)

    route = relationship("ShuttleRoute", back_populates="schedules") 
    stops = relationship("ScheduleStop", back_populates="schedule", cascade="all, delete")

class ScheduleStop(Base):
    __tablename__ = "schedule_stops"

    id = Column(Integer, primary_key=True, index=True)
    schedule_id = Column(Integer, ForeignKey("schedules.id", ondelete="CASCADE"))
    station_id = Column(Integer, ForeignKey("shuttle_stations.id", ondelete="CASCADE"))
    arrival_time = Column(Time, nullable=False)
    stop_order = Column(Integer, nullable=False)

    schedule = relationship("Schedule", back_populates="stops")
    station = relationship("ShuttleStation")
