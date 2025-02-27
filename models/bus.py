from sqlalchemy import Column, Integer, String, Float, ForeignKey
from sqlalchemy.orm import relationship
from models import Base

class BusRoute(Base):
    __tablename__ = "bus_routes"

    id = Column(Integer, primary_key=True, index=True)
    route_name = Column(String(255), unique=True, index=True)
    route_id = Column(String(255), unique=True, index=True)

class BusLocation(Base):
    __tablename__ = "bus_locations"

    id = Column(Integer, primary_key=True, index=True)
    route_id = Column(String(255), ForeignKey("bus_routes.route_id"))
    latitude = Column(Float)
    longitude = Column(Float)
    bus_number = Column(String(50))
