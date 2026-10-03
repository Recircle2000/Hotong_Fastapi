import os
import tempfile
import unittest
from datetime import time

from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from starlette.middleware.sessions import SessionMiddleware

os.environ["SUPABASE_URL"] = "sqlite:///:memory:"
os.environ.pop("SUPABASE_PASSWORD", None)

from database import get_db
from models import Base, User
from models.schedule_types import ScheduleType
from models.shuttle import Schedule, ScheduleStop, ShuttleRoute, ShuttleStation
from routers import admin_v2
from services.shuttle_timetable import (
    build_admin_shuttle_timetable,
    format_timetable_time,
)
from utils.security import hash_password


class AdminShuttleTimetableTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.db_fd, cls.db_path = tempfile.mkstemp(suffix=".db")
        cls.engine = create_engine(
            f"sqlite:///{cls.db_path}",
            connect_args={"check_same_thread": False},
        )
        cls.SessionLocal = sessionmaker(
            autocommit=False,
            autoflush=False,
            bind=cls.engine,
        )
        Base.metadata.create_all(bind=cls.engine)

        cls.app = FastAPI()
        cls.app.add_middleware(SessionMiddleware, secret_key="test-session-secret")
        cls.app.include_router(admin_v2.router)

        def override_get_db():
            db = cls.SessionLocal()
            try:
                yield db
            finally:
                db.close()

        cls.app.dependency_overrides[get_db] = override_get_db

    @classmethod
    def tearDownClass(cls):
        Base.metadata.drop_all(bind=cls.engine)
        cls.engine.dispose()
        os.close(cls.db_fd)
        os.unlink(cls.db_path)

    def setUp(self):
        with self.SessionLocal() as db:
            for table in reversed(Base.metadata.sorted_tables):
                db.execute(table.delete())

            db.add(
                User(
                    email="admin@example.com",
                    hashed_password=hash_password("secret123"),
                    is_admin=True,
                )
            )
            db.add_all(
                [
                    ScheduleType(
                        id=1,
                        schedule_type="Weekday",
                        schedule_type_name="평일(월~목)",
                        is_activate=True,
                    ),
                    ScheduleType(
                        id=2,
                        schedule_type="NoData",
                        schedule_type_name="데이터 없음",
                        is_activate=True,
                    ),
                    ScheduleType(
                        id=3,
                        schedule_type="OldSchedule",
                        schedule_type_name="이전 시간표",
                        is_activate=False,
                    ),
                ]
            )
            db.add_all(
                [
                    ShuttleRoute(id=1, route_name="KTX 순환", direction="UP"),
                    ShuttleRoute(id=2, route_name="온양방향", direction="UP"),
                ]
            )
            db.add_all(
                [
                    ShuttleStation(
                        id=1,
                        name="아산캠퍼스 [출발]",
                        latitude=36.0,
                        longitude=127.0,
                        is_active=True,
                    ),
                    ShuttleStation(
                        id=2,
                        name="천안아산역",
                        latitude=36.1,
                        longitude=127.1,
                        is_active=True,
                    ),
                    ShuttleStation(
                        id=3,
                        name="아산캠퍼스 [도착]",
                        latitude=36.2,
                        longitude=127.2,
                        is_active=True,
                    ),
                ]
            )
            db.flush()

            early_schedule = Schedule(
                id=10,
                route_id=1,
                schedule_type="Weekday",
                start_time=time(8, 0),
                end_time=time(8, 30),
            )
            late_schedule = Schedule(
                id=11,
                route_id=1,
                schedule_type="Weekday",
                start_time=time(9, 0),
                end_time=time(9, 30),
            )
            inactive_schedule = Schedule(
                id=12,
                route_id=2,
                schedule_type="OldSchedule",
                start_time=time(10, 0),
                end_time=time(10, 30),
            )
            db.add_all([late_schedule, early_schedule, inactive_schedule])
            db.flush()

            db.add_all(
                [
                    ScheduleStop(
                        schedule_id=10,
                        station_id=1,
                        arrival_time=time(8, 0),
                        stop_order=1,
                    ),
                    ScheduleStop(
                        schedule_id=10,
                        station_id=2,
                        arrival_time=time(8, 10),
                        stop_order=2,
                    ),
                    ScheduleStop(
                        schedule_id=10,
                        station_id=3,
                        arrival_time=time(8, 30),
                        stop_order=4,
                    ),
                    ScheduleStop(
                        schedule_id=11,
                        station_id=2,
                        arrival_time=time(9, 10),
                        stop_order=2,
                    ),
                    ScheduleStop(
                        schedule_id=11,
                        station_id=3,
                        arrival_time=time(9, 30),
                        stop_order=4,
                    ),
                    ScheduleStop(
                        schedule_id=12,
                        station_id=1,
                        arrival_time=time(10, 0),
                        stop_order=1,
                    ),
                    ScheduleStop(
                        schedule_id=12,
                        station_id=3,
                        arrival_time=time(10, 30),
                        stop_order=2,
                    ),
                ]
            )
            db.commit()

        self.client = TestClient(self.app)

    def login(self):
        response = self.client.post(
            "/api/admin-v2/auth/login",
            json={"email": "admin@example.com", "password": "secret123"},
            follow_redirects=False,
        )
        self.assertEqual(response.status_code, 200)

    def test_build_timetable_groups_sorts_and_marks_missing_stops(self):
        with self.SessionLocal() as db:
            sections = build_admin_shuttle_timetable(db)

        self.assertEqual(
            [section["schedule_type"] for section in sections],
            ["Weekday", "OldSchedule"],
        )
        self.assertNotIn(
            "NoData",
            [section["schedule_type"] for section in sections],
        )

        weekday_route = sections[0]["routes"][0]
        self.assertEqual(
            [station["station_name"] for station in weekday_route["stations"]],
            ["아산캠퍼스 [출발]", "천안아산역", "아산캠퍼스 [도착]"],
        )
        self.assertEqual(weekday_route["rows"][0]["schedule_id"], 10)
        self.assertEqual(weekday_route["rows"][0]["times"], ["08:00", "08:10", "08:30"])
        self.assertEqual(weekday_route["rows"][1]["times"], ["—", "09:10", "09:30"])

        self.assertFalse(sections[1]["is_active"])
        self.assertEqual(format_timetable_time(None), "—")

    def test_timetable_api_requires_admin_session(self):
        response = self.client.get("/api/admin-v2/shuttle-timetable")

        self.assertEqual(response.status_code, 401)
        self.assertEqual(response.json()["detail"], "인증이 필요합니다.")

    def test_timetable_api_returns_grouped_route_matrices(self):
        self.login()

        response = self.client.get("/api/admin-v2/shuttle-timetable")

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual([section["schedule_type"] for section in payload], ["Weekday", "OldSchedule"])
        self.assertEqual(payload[0]["schedule_type_name"], "평일(월~목)")
        self.assertEqual(payload[0]["routes"][0]["route_name"], "KTX 순환")
        self.assertEqual(payload[0]["routes"][0]["rows"][0]["times"], ["08:00", "08:10", "08:30"])
        self.assertEqual(payload[0]["routes"][0]["rows"][1]["times"], ["—", "09:10", "09:30"])
        self.assertFalse(payload[1]["is_active"])


if __name__ == "__main__":
    unittest.main()
