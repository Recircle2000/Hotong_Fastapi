import os

from dotenv import load_dotenv
from sqlalchemy import create_engine
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker

load_dotenv()

DB_URL = os.getenv("DATABASE_URL")

if not DB_URL:
    raise RuntimeError("DATABASE_URL is not set.")

if DB_URL.startswith("sqlite"):
    engine = create_engine(
        DB_URL,
        connect_args={"check_same_thread": False},
    )
else:
    engine = create_engine(
        DB_URL,
        pool_size=10,
        max_overflow=20,
        pool_recycle=3600,
        pool_pre_ping=True,
    )

SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
