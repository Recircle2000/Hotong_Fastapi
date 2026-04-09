from dotenv import load_dotenv
from sqlalchemy.orm import sessionmaker
from db_config import create_configured_engine, get_database_url
from models import Base

load_dotenv()

DB_URL = get_database_url()
engine = create_configured_engine(DB_URL)

SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
