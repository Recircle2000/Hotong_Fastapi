from sqlalchemy import Column, Integer, String, Double, Enum, ForeignKey
from sqlalchemy.orm import relationship
from models import Base

class ShuttleStation(Base):
    __tablename__ = "shuttle_stations"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String(255), nullable=False)
    latitude = Column(Double, nullable=False)
    longitude = Column(Double, nullable=False)
    
    routes = relationship("ShuttleRoute", secondary="shuttle_station_routes", back_populates="stations")

class ShuttleRoute(Base):
    __tablename__ = "shuttle_routes"

    id = Column(Integer, primary_key=True, index=True)
    route_name = Column(String(255), nullable=False)
    direction = Column(Enum('UP', 'DOWN', name='direction_enum'), nullable=False)
    
    stations = relationship("ShuttleStation", secondary="shuttle_station_routes", back_populates="routes")

class ShuttleStationRoute(Base):
    __tablename__ = "shuttle_station_routes"

    id = Column(Integer, primary_key=True, index=True)
    station_id = Column(Integer, ForeignKey("shuttle_stations.id", ondelete="CASCADE"))
    route_id = Column(Integer, ForeignKey("shuttle_routes.id", ondelete="CASCADE")) 