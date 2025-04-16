from sqlalchemy import Column, Integer, String, Boolean
from models import Base  # DB 연결

class User(Base):
    __tablename__ = "users"

    id = Column(Integer, primary_key=True, index=True)
    email = Column(String(255), unique=True, index=True)
    hashed_password = Column(String(255))
    is_verified = Column(Boolean, default=False)
    is_admin = Column(Boolean, default=False)
