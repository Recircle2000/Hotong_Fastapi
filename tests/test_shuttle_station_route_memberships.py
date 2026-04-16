import os
import sys
import tempfile
import types
import unittest
from datetime import time
from unittest.mock import call, patch

from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

os.environ["SUPABASE_URL"] = "sqlite:///:memory:"
os.environ.pop("SUPABASE_PASSWORD", None)

holidayskr_stub = types.ModuleType("holidayskr")
holidayskr_stub.is_holiday = lambda _date: False
sys.modules["holidayskr"] = holidayskr_stub

from database import get_db
from models import Base
from models.shuttle import Schedule, ScheduleStop, ShuttleRoute, ShuttleStation
from routers import admin_v2, shuttle
from schemas.shuttle import ScheduleCreate, ScheduleStopCreate, ScheduleUpdate


class ShuttleStationRouteMembershipTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.db_fd, cls.db_path = tempfile.mkstemp(suffix=".db")
        cls.engine = create_engine(
            f"sqlite:///{cls.db_path}",
            connect_args={"check_same_thread": False},
        )
        cls.SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=cls.engine)
        Base.metadata.create_all(bind=cls.engine)

        cls.app = FastAPI()
        cls.app.include_router(shuttle.router, prefix="/shuttle")

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
        self.client = TestClient(self.app)
        self.cache_store = {}

        self.get_cache_patcher = patch(
            "routers.shuttle.get_cache",
            side_effect=lambda key: self.cache_store.get(key),
        )
        self.set_cache_patcher = patch(
            "routers.shuttle.set_cache",
            side_effect=self._set_cache,
        )
        self.get_cache_patcher.start()
        self.set_cache_patcher.start()

        with self.SessionLocal() as db:
            for table in reversed(Base.metadata.sorted_tables):
                db.execute(table.delete())
            db.commit()

    def tearDown(self):
        self.get_cache_patcher.stop()
        self.set_cache_patcher.stop()

    def _set_cache(self, key, data, expire=None):
        del expire
        self.cache_store[key] = data
        return True

    def _seed_route_membership_data(self):
        with self.SessionLocal() as db:
            db.add_all(
                [
                    ShuttleRoute(id=1, route_name="아산", direction="UP"),
                    ShuttleRoute(id=2, route_name="천안", direction="DOWN"),
                    ShuttleRoute(id=4, route_name="KTX", direction="UP"),
                    ShuttleStation(
                        id=1,
                        name="정문",
                        latitude=36.7691,
                        longitude=127.0739,
                        description="메인 정류장",
                        image_url=None,
                        is_active=True,
                    ),
                    ShuttleStation(
                        id=2,
                        name="후문",
                        latitude=36.7685,
                        longitude=127.0751,
                        description=None,
                        image_url=None,
                        is_active=True,
                    ),
                    ShuttleStation(
                        id=3,
                        name="임시 정류장",
                        latitude=36.7670,
                        longitude=127.0740,
                        description=None,
                        image_url=None,
                        is_active=False,
                    ),
                    ShuttleStation(
                        id=4,
                        name="매핑 없음",
                        latitude=36.7660,
                        longitude=127.0720,
                        description=None,
                        image_url=None,
                        is_active=True,
                    ),
                    Schedule(
                        id=101,
                        route_id=2,
                        schedule_type="Weekday",
                        start_time=time(8, 0),
                        end_time=time(9, 0),
                    ),
                    Schedule(
                        id=102,
                        route_id=1,
                        schedule_type="Weekday",
                        start_time=time(8, 30),
                        end_time=time(9, 30),
                    ),
                    Schedule(
                        id=103,
                        route_id=4,
                        schedule_type="Weekday",
                        start_time=time(10, 0),
                        end_time=time(11, 0),
                    ),
                    Schedule(
                        id=104,
                        route_id=2,
                        schedule_type="Saturday",
                        start_time=time(11, 0),
                        end_time=time(12, 0),
                    ),
                ]
            )
            db.add_all(
                [
                    ScheduleStop(
                        schedule_id=101,
                        station_id=1,
                        arrival_time=time(8, 10),
                        stop_order=1,
                    ),
                    ScheduleStop(
                        schedule_id=102,
                        station_id=1,
                        arrival_time=time(8, 40),
                        stop_order=1,
                    ),
                    ScheduleStop(
                        schedule_id=103,
                        station_id=1,
                        arrival_time=time(10, 10),
                        stop_order=1,
                    ),
                    ScheduleStop(
                        schedule_id=104,
                        station_id=1,
                        arrival_time=time(11, 10),
                        stop_order=1,
                    ),
                    ScheduleStop(
                        schedule_id=103,
                        station_id=2,
                        arrival_time=time(10, 20),
                        stop_order=2,
                    ),
                    ScheduleStop(
                        schedule_id=103,
                        station_id=3,
                        arrival_time=time(10, 30),
                        stop_order=3,
                    ),
                ]
            )
            db.commit()

    def _seed_schedule_dependencies(self, db):
        db.add(
            ShuttleRoute(id=1, route_name="아산", direction="UP")
        )
        db.add(
            ShuttleStation(
                id=10,
                name="정문",
                latitude=36.7691,
                longitude=127.0739,
                description=None,
                image_url=None,
                is_active=True,
            )
        )
        db.commit()

    def _create_schedule(self, db, schedule_id=201):
        db.add(
            Schedule(
                id=schedule_id,
                route_id=1,
                schedule_type="Weekday",
                start_time=time(8, 0),
                end_time=time(9, 0),
            )
        )
        db.add(
            ScheduleStop(
                schedule_id=schedule_id,
                station_id=10,
                arrival_time=time(8, 10),
                stop_order=1,
            )
        )
        db.commit()

    def test_route_memberships_returns_sorted_distinct_route_ids_for_active_stations_only(self):
        self._seed_route_membership_data()

        response = self.client.get("/shuttle/stations/route-memberships")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            response.json(),
            [
                {"station_id": 1, "route_ids": [1, 2, 4]},
                {"station_id": 2, "route_ids": [4]},
            ],
        )

    def test_route_memberships_returns_empty_list_when_no_data_exists(self):
        response = self.client.get("/shuttle/stations/route-memberships")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), [])

    def test_invalidate_shuttle_station_cache_includes_route_membership_pattern(self):
        with patch("routers.admin_v2.delete_pattern") as mock_delete_pattern:
            admin_v2.invalidate_shuttle_station_cache()

        mock_delete_pattern.assert_has_calls(
            [
                call("stations:*"),
                call("station_schedules:*"),
                call("schedule_stops:*"),
                call("station_route_memberships:*"),
            ]
        )

    def test_create_schedule_invalidates_route_membership_cache(self):
        with self.SessionLocal() as db:
            self._seed_schedule_dependencies(db)
            payload = ScheduleCreate(
                route_id=1,
                schedule_type="Weekday",
                start_time=time(7, 0),
                end_time=time(8, 0),
                stops=[
                    ScheduleStopCreate(
                        station_id=10,
                        arrival_time=time(7, 10),
                        stop_order=1,
                    )
                ],
            )

            with patch("routers.shuttle.delete_pattern") as mock_delete_pattern:
                response = shuttle.create_schedule(
                    schedule_data=payload,
                    db=db,
                    current_admin=object(),
                )

        self.assertEqual(response["message"], "Schedule created successfully")
        self.assertIn(call("station_route_memberships:*"), mock_delete_pattern.mock_calls)

    def test_update_schedule_invalidates_route_membership_cache(self):
        with self.SessionLocal() as db:
            self._seed_schedule_dependencies(db)
            self._create_schedule(db, schedule_id=202)
            payload = ScheduleUpdate(
                start_time=time(8, 30),
                end_time=time(9, 30),
                stops=[
                    ScheduleStopCreate(
                        station_id=10,
                        arrival_time=time(8, 40),
                        stop_order=1,
                    )
                ],
            )

            with patch("routers.shuttle.delete_pattern") as mock_delete_pattern:
                response = shuttle.update_schedule(
                    schedule_id=202,
                    schedule_data=payload,
                    db=db,
                    current_admin=object(),
                )

        self.assertEqual(response["message"], "Schedule updated successfully")
        self.assertIn(call("station_route_memberships:*"), mock_delete_pattern.mock_calls)

    def test_delete_schedule_invalidates_route_membership_cache(self):
        with self.SessionLocal() as db:
            self._seed_schedule_dependencies(db)
            self._create_schedule(db, schedule_id=203)

            with patch("routers.shuttle.delete_pattern") as mock_delete_pattern:
                response = shuttle.delete_schedule(
                    schedule_id=203,
                    db=db,
                    current_admin=object(),
                )

        self.assertEqual(response["message"], "Schedule deleted successfully")
        self.assertIn(call("station_route_memberships:*"), mock_delete_pattern.mock_calls)


if __name__ == "__main__":
    unittest.main()
