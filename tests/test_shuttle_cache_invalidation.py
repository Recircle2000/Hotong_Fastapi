import fnmatch
import os
import sys
import tempfile
import types
import unittest
from datetime import time
from unittest.mock import patch

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
from routers import shuttle
from utils.security import get_current_admin

# 시간표 변경과 무관해서 무효화되지 않아도 되는 캐시 키 패턴
UNRELATED_KEY_PATTERNS = ("routes:*", "stations:*", "schedule_types", "schedule_exceptions")


class FakeRedis:
    """실제 Redis처럼 글롭 패턴으로 키를 지우는 인메모리 캐시."""

    def __init__(self):
        self.store = {}

    def get(self, key):
        return self.store.get(key)

    def set(self, key, data, expire=None):
        self.store[key] = data
        return True

    def delete_pattern(self, pattern):
        keys = [key for key in self.store if fnmatch.fnmatchcase(key, pattern)]
        for key in keys:
            del self.store[key]
        return len(keys)


class ShuttleScheduleCacheInvalidationTests(unittest.TestCase):
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
        cls.app.dependency_overrides[get_current_admin] = lambda: object()

    @classmethod
    def tearDownClass(cls):
        Base.metadata.drop_all(bind=cls.engine)
        cls.engine.dispose()
        os.close(cls.db_fd)
        os.unlink(cls.db_path)

    def setUp(self):
        self.client = TestClient(self.app)
        self.cache = FakeRedis()
        self.patchers = [
            patch("routers.shuttle.get_cache", side_effect=self.cache.get),
            patch("routers.shuttle.set_cache", side_effect=self.cache.set),
            patch("routers.shuttle.delete_pattern", side_effect=self.cache.delete_pattern),
        ]
        for patcher in self.patchers:
            patcher.start()

        with self.SessionLocal() as db:
            for table in reversed(Base.metadata.sorted_tables):
                db.execute(table.delete())
            db.add(ShuttleRoute(id=1, route_name="아캠-천캠", direction="UP"))
            for station_id in (1, 2, 4, 5):
                db.add(
                    ShuttleStation(
                        id=station_id,
                        name=f"정류장{station_id}",
                        latitude=36.0,
                        longitude=127.0,
                        is_active=True,
                    )
                )
            db.add(
                Schedule(
                    id=1,
                    route_id=1,
                    schedule_type="Weekday",
                    start_time=time(8, 30),
                    end_time=time(8, 48),
                )
            )
            for order, (station_id, minute) in enumerate(((1, 30), (2, 43), (4, 48)), start=1):
                db.add(
                    ScheduleStop(
                        schedule_id=1,
                        station_id=station_id,
                        arrival_time=time(8, minute),
                        stop_order=order,
                    )
                )
            db.commit()

    def tearDown(self):
        for patcher in self.patchers:
            patcher.stop()

    def _warm_caches(self, schedule_id=1):
        """시간표 변경의 영향을 받는 읽기 API를 모두 호출해 캐시에 채운다."""
        responses = {
            "route_stations": self.client.get("/shuttle/routes/1/stations"),
            "schedules": self.client.get("/shuttle/schedules?route_id=1&schedule_type=Weekday"),
            "schedule_stops": self.client.get(f"/shuttle/schedules/{schedule_id}/stops"),
            "station_schedules": self.client.get("/shuttle/stations/1/schedules"),
            "memberships": self.client.get("/shuttle/stations/route-memberships"),
        }
        for name, response in responses.items():
            self.assertEqual(response.status_code, 200, f"{name}: {response.text}")
        return responses

    def _stale_keys(self):
        return [
            key
            for key in self.cache.store
            if not any(fnmatch.fnmatchcase(key, pattern) for pattern in UNRELATED_KEY_PATTERNS)
        ]

    def _payload(self, station_ids, hour=10):
        return {
            "route_id": 1,
            "schedule_type": "Weekday",
            "start_time": f"{hour}:00:00",
            "end_time": f"{hour}:30:00",
            "stops": [
                {
                    "station_id": station_id,
                    "arrival_time": f"{hour}:{index * 5:02d}:00",
                    "stop_order": index + 1,
                }
                for index, station_id in enumerate(station_ids)
            ],
        }

    def test_warming_populates_every_dependent_cache_key(self):
        self._warm_caches()

        keys = set(self.cache.store)
        self.assertIn("route_stations:1:all", keys)
        self.assertIn("schedules:1:Weekday", keys)
        self.assertIn("schedule_stops:1", keys)
        self.assertIn("station_schedules:1", keys)
        self.assertIn("station_route_memberships:active", keys)

    def test_create_schedule_clears_all_dependent_caches(self):
        self._warm_caches()
        self.assertEqual(len(self.client.get("/shuttle/routes/1/stations").json()), 3)

        response = self.client.post("/shuttle/admin/schedules", json=self._payload([1, 2, 4, 5]))
        self.assertEqual(response.status_code, 201, response.text)

        self.assertEqual(self._stale_keys(), [])

    def test_create_schedule_is_visible_through_every_read_api(self):
        self._warm_caches()

        response = self.client.post("/shuttle/admin/schedules", json=self._payload([1, 2, 4, 5]))
        new_id = response.json()["id"]

        route_stations = self.client.get("/shuttle/routes/1/stations").json()
        self.assertEqual([item["station_id"] for item in route_stations], [1, 2, 4, 5])

        schedules = self.client.get("/shuttle/schedules?route_id=1&schedule_type=Weekday").json()
        self.assertEqual({item["id"] for item in schedules}, {1, new_id})

        self.assertEqual(len(self.client.get(f"/shuttle/schedules/{new_id}/stops").json()), 4)

        station_schedules = self.client.get("/shuttle/stations/1/schedules").json()
        self.assertEqual({item["schedule_id"] for item in station_schedules}, {1, new_id})

    def test_bulk_create_keeps_route_stations_fresh_after_each_insert(self):
        # CSV/붙여넣기 일괄 등록처럼 연속 호출해도 매번 최신 값을 돌려줘야 한다.
        counts = []
        for hour, station_ids in ((10, [1, 2]), (11, [1, 2, 4]), (12, [1, 2, 4, 5])):
            self.client.get("/shuttle/routes/1/stations")
            self.client.post("/shuttle/admin/schedules", json=self._payload(station_ids, hour))
            counts.append(len(self.client.get("/shuttle/routes/1/stations").json()))

        self.assertEqual(counts, [3, 3, 4])

    def test_update_schedule_clears_all_dependent_caches(self):
        self._warm_caches()

        response = self.client.put(
            "/shuttle/admin/schedules/1",
            json={"stops": self._payload([1, 2, 4, 5])["stops"]},
        )
        self.assertEqual(response.status_code, 200, response.text)

        self.assertEqual(self._stale_keys(), [])
        route_stations = self.client.get("/shuttle/routes/1/stations").json()
        self.assertEqual([item["station_id"] for item in route_stations], [1, 2, 4, 5])
        self.assertEqual(len(self.client.get("/shuttle/schedules/1/stops").json()), 4)

    def test_delete_schedule_clears_all_dependent_caches(self):
        self._warm_caches()

        response = self.client.delete("/shuttle/admin/schedules/1")
        self.assertEqual(response.status_code, 200, response.text)

        self.assertEqual(self._stale_keys(), [])
        self.assertEqual(self.client.get("/shuttle/routes/1/stations").json(), [])
        self.assertEqual(
            self.client.get("/shuttle/schedules?route_id=1&schedule_type=Weekday").status_code,
            404,
        )


if __name__ == "__main__":
    unittest.main()
