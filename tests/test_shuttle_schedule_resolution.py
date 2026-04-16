import os
import sys
import tempfile
import types
import unittest
from datetime import date
from unittest.mock import patch

from sqlalchemy import Boolean, Column, Integer, String, create_engine
from sqlalchemy.orm import declarative_base, sessionmaker

os.environ["SUPABASE_URL"] = "sqlite:///:memory:"
os.environ.pop("SUPABASE_PASSWORD", None)

holidayskr_stub = types.ModuleType("holidayskr")
holidayskr_stub.is_holiday = lambda _date: False
sys.modules["holidayskr"] = holidayskr_stub

from routers.shuttle import resolve_schedule_type


Base = declarative_base()


class ScheduleTypeOnly(Base):
    __tablename__ = "schedule_types"

    id = Column(Integer, primary_key=True)
    schedule_type = Column(String(50), nullable=False, unique=True)
    schedule_type_name = Column(String(50), nullable=False, unique=True)
    is_activate = Column(Boolean, default=True)


class ShuttleScheduleResolutionTests(unittest.TestCase):
    def setUp(self):
        self.db_fd, self.db_path = tempfile.mkstemp(suffix=".db")
        self.engine = create_engine(
            f"sqlite:///{self.db_path}",
            connect_args={"check_same_thread": False},
        )
        Base.metadata.create_all(bind=self.engine)
        self.SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=self.engine)

        with self.SessionLocal() as db:
            db.add_all(
                [
                    ScheduleTypeOnly(schedule_type="Weekday", schedule_type_name="평일", is_activate=True),
                    ScheduleTypeOnly(schedule_type="Weekday_friday", schedule_type_name="금요일", is_activate=True),
                    ScheduleTypeOnly(schedule_type="Saturday", schedule_type_name="토요일", is_activate=True),
                    ScheduleTypeOnly(schedule_type="Holiday", schedule_type_name="공휴일", is_activate=True),
                ]
            )
            db.commit()

    def tearDown(self):
        self.engine.dispose()
        os.close(self.db_fd)
        os.unlink(self.db_path)

    @patch("routers.shuttle.set_cache")
    @patch("routers.shuttle.get_cache", return_value=None)
    @patch("routers.shuttle.is_holiday", return_value=False)
    def test_resolve_schedule_type_falls_back_when_schedule_exceptions_table_is_missing(
        self,
        _mock_holiday,
        _mock_get_cache,
        _mock_set_cache,
    ):
        with self.SessionLocal() as db:
            schedule_type, schedule_type_name = resolve_schedule_type(db, date(2026, 4, 9))

        self.assertEqual(schedule_type, "Weekday")
        self.assertEqual(schedule_type_name, "평일")


if __name__ == "__main__":
    unittest.main()
