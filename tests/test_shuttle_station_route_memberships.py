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
from models.schedule_types import ScheduleType
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
        self.cache_writes = []

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
        self.cache_writes.append((key, expire))
        self.cache_store[key] = data
        return True

    def _seed_route_station_data(self):
        with self.SessionLocal() as db:
            db.add_all(
                [
                    ShuttleRoute(id=7, route_name="통합 노선", direction="UP"),
                    ShuttleRoute(id=8, route_name="빈 노선", direction="DOWN"),
                    ShuttleStation(
                        id=10,
                        name="정문",
                        latitude=36.7691,
                        longitude=127.0739,
                        description=None,
                        image_url=None,
                        is_active=True,
                    ),
                    ShuttleStation(
                        id=20,
                        name="터미널",
                        latitude=36.7685,
                        longitude=127.0751,
                        description=None,
                        image_url=None,
                        is_active=True,
                    ),
                    ShuttleStation(
                        id=30,
                        name="KTX",
                        latitude=36.7670,
                        longitude=127.0740,
                        description=None,
                        image_url=None,
                        is_active=True,
                    ),
                    ShuttleStation(
                        id=40,
                        name="비활성 정류장",
                        latitude=36.7660,
                        longitude=127.0720,
                        description=None,
                        image_url=None,
                        is_active=False,
                    ),
                    Schedule(
                        id=701,
                        route_id=7,
                        schedule_type="Weekday",
                        start_time=time(8, 0),
                        end_time=time(9, 0),
                    ),
                    Schedule(
                        id=702,
                        route_id=7,
                        schedule_type="Saturday",
                        start_time=time(10, 0),
                        end_time=time(11, 0),
                    ),
                ]
            )
            db.add_all(
                [
                    ScheduleStop(
                        schedule_id=701,
                        station_id=10,
                        arrival_time=time(8, 10),
                        stop_order=1,
                    ),
                    ScheduleStop(
                        schedule_id=701,
                        station_id=20,
                        arrival_time=time(8, 30),
                        stop_order=2,
                    ),
                    ScheduleStop(
                        schedule_id=701,
                        station_id=30,
                        arrival_time=time(8, 40),
                        stop_order=3,
                    ),
                    ScheduleStop(
                        schedule_id=702,
                        station_id=10,
                        arrival_time=time(10, 10),
                        stop_order=1,
                    ),
                    ScheduleStop(
                        schedule_id=702,
                        station_id=30,
                        arrival_time=time(10, 20),
                        stop_order=2,
                    ),
                    ScheduleStop(
                        schedule_id=702,
                        station_id=40,
                        arrival_time=time(10, 5),
                        stop_order=1,
                    ),
                ]
            )
            db.commit()

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

    def _seed_journey_data(self):
        with self.SessionLocal() as db:
            db.add(
                ScheduleType(
                    schedule_type="Weekday",
                    schedule_type_name="평일",
                    is_activate=True,
                )
            )
            db.add_all(
                [
                    ShuttleRoute(id=21, route_name="캠퍼스 직행", direction="UP"),
                    ShuttleRoute(id=22, route_name="역방향", direction="DOWN"),
                    ShuttleStation(
                        id=101,
                        name="아산캠퍼스 [출발]",
                        latitude=36.1,
                        longitude=127.1,
                        is_active=True,
                    ),
                    ShuttleStation(
                        id=102,
                        name="중간 정류장",
                        latitude=36.2,
                        longitude=127.2,
                        is_active=True,
                    ),
                    ShuttleStation(
                        id=103,
                        name="도착 정류장",
                        latitude=36.3,
                        longitude=127.3,
                        is_active=True,
                    ),
                    ShuttleStation(
                        id=104,
                        name="비활성 목적지",
                        latitude=36.4,
                        longitude=127.4,
                        is_active=False,
                    ),
                    Schedule(
                        id=2101,
                        route_id=21,
                        schedule_type="Weekday",
                        start_time=time(8, 0),
                        end_time=time(9, 0),
                    ),
                    Schedule(
                        id=2102,
                        route_id=21,
                        schedule_type="Weekday",
                        start_time=time(9, 0),
                        end_time=time(10, 0),
                    ),
                    Schedule(
                        id=2201,
                        route_id=22,
                        schedule_type="Weekday",
                        start_time=time(8, 0),
                        end_time=time(9, 0),
                    ),
                ]
            )
            db.add_all(
                [
                    ScheduleStop(schedule_id=2101, station_id=101, arrival_time=time(8, 5), stop_order=1),
                    ScheduleStop(schedule_id=2101, station_id=102, arrival_time=time(8, 15), stop_order=2),
                    ScheduleStop(schedule_id=2101, station_id=103, arrival_time=time(8, 35), stop_order=3),
                    ScheduleStop(schedule_id=2101, station_id=104, arrival_time=time(8, 45), stop_order=4),
                    ScheduleStop(schedule_id=2102, station_id=101, arrival_time=time(9, 10), stop_order=1),
                    ScheduleStop(schedule_id=2102, station_id=103, arrival_time=time(9, 30), stop_order=2),
                    ScheduleStop(schedule_id=2201, station_id=103, arrival_time=time(8, 10), stop_order=1),
                    ScheduleStop(schedule_id=2201, station_id=101, arrival_time=time(8, 40), stop_order=2),
                ]
            )
            db.commit()

    def _seed_asan_cheonan_asan_group_data(self):
        with self.SessionLocal() as db:
            db.add(
                ScheduleType(
                    schedule_type="Weekday",
                    schedule_type_name="평일",
                    is_activate=True,
                )
            )
            db.add_all(
                [
                    ShuttleRoute(id=31, route_name="아캠 → 천캠", direction="UP"),
                    ShuttleRoute(id=32, route_name="KTX 순환", direction="DOWN"),
                    ShuttleStation(
                        id=201,
                        name="아산캠퍼스 [출발]",
                        latitude=36.7,
                        longitude=127.0,
                        is_active=True,
                    ),
                    ShuttleStation(
                        id=202,
                        name="천안아산역 [천캠방향]",
                        latitude=36.8,
                        longitude=127.1,
                        is_active=True,
                    ),
                    ShuttleStation(
                        id=203,
                        name="천안아산역 [아캠방향]",
                        latitude=36.8,
                        longitude=127.1,
                        is_active=True,
                    ),
                    ShuttleStation(
                        id=204,
                        name="아산캠퍼스 [도착]",
                        latitude=36.9,
                        longitude=127.2,
                        is_active=True,
                    ),
                    Schedule(
                        id=3101,
                        route_id=31,
                        schedule_type="Weekday",
                        start_time=time(18, 0),
                        end_time=time(19, 0),
                    ),
                    Schedule(
                        id=3201,
                        route_id=32,
                        schedule_type="Weekday",
                        start_time=time(18, 10),
                        end_time=time(18, 50),
                    ),
                    Schedule(
                        id=3102,
                        route_id=31,
                        schedule_type="Weekday",
                        start_time=time(19, 0),
                        end_time=time(19, 30),
                    ),
                    Schedule(
                        id=3202,
                        route_id=32,
                        schedule_type="Weekday",
                        start_time=time(19, 10),
                        end_time=time(19, 40),
                    ),
                ]
            )
            db.add_all(
                [
                    ScheduleStop(
                        schedule_id=3101,
                        station_id=201,
                        arrival_time=time(18, 0),
                        stop_order=1,
                    ),
                    ScheduleStop(
                        schedule_id=3101,
                        station_id=202,
                        arrival_time=time(18, 25),
                        stop_order=2,
                    ),
                    ScheduleStop(
                        schedule_id=3201,
                        station_id=201,
                        arrival_time=time(18, 10),
                        stop_order=1,
                    ),
                    ScheduleStop(
                        schedule_id=3201,
                        station_id=203,
                        arrival_time=time(18, 30),
                        stop_order=2,
                    ),
                    ScheduleStop(
                        schedule_id=3102,
                        station_id=202,
                        arrival_time=time(19, 0),
                        stop_order=1,
                    ),
                    ScheduleStop(
                        schedule_id=3102,
                        station_id=204,
                        arrival_time=time(19, 20),
                        stop_order=2,
                    ),
                    ScheduleStop(
                        schedule_id=3202,
                        station_id=203,
                        arrival_time=time(19, 10),
                        stop_order=1,
                    ),
                    ScheduleStop(
                        schedule_id=3202,
                        station_id=204,
                        arrival_time=time(19, 30),
                        stop_order=2,
                    ),
                ]
            )
            db.commit()

    def _seed_chungmu_hospital_group_data(self):
        with self.SessionLocal() as db:
            db.add(
                ScheduleType(
                    schedule_type="Weekday",
                    schedule_type_name="평일",
                    is_activate=True,
                )
            )
            db.add_all(
                [
                    ShuttleRoute(id=41, route_name="천캠 방향", direction="UP"),
                    ShuttleRoute(id=42, route_name="아캠 방향", direction="DOWN"),
                    ShuttleStation(
                        id=401,
                        name="천안 충무병원",
                        latitude=36.798219,
                        longitude=127.133672,
                        is_active=True,
                    ),
                    ShuttleStation(
                        id=402,
                        name="천안 충무병원 맞은편",
                        latitude=36.798257,
                        longitude=127.132494,
                        is_active=True,
                    ),
                    ShuttleStation(
                        id=403,
                        name="천안캠퍼스 [도착]",
                        latitude=36.82,
                        longitude=127.18,
                        is_active=True,
                    ),
                    ShuttleStation(
                        id=404,
                        name="아산캠퍼스 [도착]",
                        latitude=36.74,
                        longitude=127.08,
                        is_active=True,
                    ),
                    ShuttleStation(
                        id=405,
                        name="중간 하차 불가 정류장",
                        latitude=36.81,
                        longitude=127.15,
                        is_active=True,
                    ),
                    Schedule(
                        id=4101,
                        route_id=41,
                        schedule_type="Weekday",
                        start_time=time(8, 0),
                        end_time=time(8, 30),
                    ),
                    Schedule(
                        id=4201,
                        route_id=42,
                        schedule_type="Weekday",
                        start_time=time(9, 0),
                        end_time=time(9, 30),
                    ),
                ]
            )
            db.add_all(
                [
                    ScheduleStop(
                        schedule_id=4101,
                        station_id=401,
                        arrival_time=time(8, 0),
                        stop_order=1,
                    ),
                    ScheduleStop(
                        schedule_id=4101,
                        station_id=405,
                        arrival_time=time(8, 10),
                        stop_order=2,
                    ),
                    ScheduleStop(
                        schedule_id=4101,
                        station_id=403,
                        arrival_time=time(8, 20),
                        stop_order=3,
                    ),
                    ScheduleStop(
                        schedule_id=4201,
                        station_id=402,
                        arrival_time=time(9, 0),
                        stop_order=1,
                    ),
                    ScheduleStop(
                        schedule_id=4201,
                        station_id=404,
                        arrival_time=time(9, 20),
                        stop_order=2,
                    ),
                ]
            )
            db.commit()

    def _seed_campus_group_data(self):
        with self.SessionLocal() as db:
            db.add(
                ScheduleType(
                    schedule_type="Weekday",
                    schedule_type_name="평일",
                    is_activate=True,
                )
            )
            db.add_all(
                [
                    ShuttleRoute(id=51, route_name="아산캠퍼스행", direction="DOWN"),
                    ShuttleRoute(id=52, route_name="천안캠퍼스행", direction="UP"),
                    ShuttleStation(
                        id=501,
                        name="공통 출발지",
                        latitude=36.79,
                        longitude=127.1,
                        is_active=True,
                    ),
                    ShuttleStation(
                        id=502,
                        name="아산캠퍼스 [출발]",
                        latitude=36.738529,
                        longitude=127.077037,
                        is_active=True,
                    ),
                    ShuttleStation(
                        id=503,
                        name="아산캠퍼스 [도착]",
                        latitude=36.73861,
                        longitude=127.076775,
                        is_active=True,
                    ),
                    ShuttleStation(
                        id=504,
                        name="천안캠퍼스 [출발]",
                        latitude=36.829613,
                        longitude=127.181358,
                        is_active=True,
                    ),
                    ShuttleStation(
                        id=505,
                        name="천안캠퍼스 [도착]",
                        latitude=36.829601,
                        longitude=127.181351,
                        is_active=True,
                    ),
                    Schedule(
                        id=5101,
                        route_id=51,
                        schedule_type="Weekday",
                        start_time=time(10, 0),
                        end_time=time(10, 30),
                    ),
                    Schedule(
                        id=5201,
                        route_id=52,
                        schedule_type="Weekday",
                        start_time=time(11, 0),
                        end_time=time(11, 30),
                    ),
                ]
            )
            db.add_all(
                [
                    ScheduleStop(
                        schedule_id=5101,
                        station_id=501,
                        arrival_time=time(10, 0),
                        stop_order=1,
                    ),
                    ScheduleStop(
                        schedule_id=5101,
                        station_id=503,
                        arrival_time=time(10, 25),
                        stop_order=2,
                    ),
                    ScheduleStop(
                        schedule_id=5201,
                        station_id=501,
                        arrival_time=time(11, 0),
                        stop_order=1,
                    ),
                    ScheduleStop(
                        schedule_id=5201,
                        station_id=505,
                        arrival_time=time(11, 25),
                        stop_order=2,
                    ),
                ]
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

    def test_route_stations_uses_order_from_schedule_with_most_active_stops(self):
        self._seed_route_station_data()

        response = self.client.get("/shuttle/routes/7/stations")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            response.json(),
            [
                {"stop_order": 1, "station_id": 10, "station_name": "정문"},
                {"stop_order": 2, "station_id": 20, "station_name": "터미널"},
                {"stop_order": 3, "station_id": 30, "station_name": "KTX"},
            ],
        )
        self.assertIn(("route_stations:7:all", None), self.cache_writes)

    def test_route_stations_returns_empty_list_when_route_has_no_stops(self):
        self._seed_route_station_data()

        response = self.client.get("/shuttle/routes/8/stations")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), [])
        self.assertIn(("route_stations:8:all", None), self.cache_writes)

    def test_route_stations_returns_404_when_route_does_not_exist(self):
        response = self.client.get("/shuttle/routes/999/stations")

        self.assertEqual(response.status_code, 404)
        self.assertEqual(response.json()["detail"], "Route with id 999 not found")

    def test_journey_destinations_only_returns_active_downstream_stations(self):
        self._seed_journey_data()

        response = self.client.get(
            "/shuttle/journey-destinations",
            params={"origin_station_id": 101, "date": "2026-08-24"},
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            response.json(),
            [
                {"station_id": 103, "station_name": "도착 정류장"},
                {"station_id": 102, "station_name": "중간 정류장"},
            ],
        )

    def test_journeys_returns_only_same_schedule_forward_trips_in_time_order(self):
        self._seed_journey_data()

        response = self.client.get(
            "/shuttle/journeys",
            params={
                "origin_station_id": 101,
                "destination_station_id": 103,
                "date": "2026-08-24",
            },
        )

        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertEqual(body["schedule_type_name"], "평일")
        self.assertEqual([item["schedule_id"] for item in body["journeys"]], [2101, 2102])
        self.assertEqual(body["journeys"][0]["duration_minutes"], 30)
        self.assertEqual(body["journeys"][0]["intermediate_stop_count"], 1)

    def test_journeys_rejects_intermediate_stop_to_intermediate_stop(self):
        self._seed_journey_data()

        response = self.client.get(
            "/shuttle/journeys",
            params={
                "origin_station_id": 103,
                "destination_station_id": 102,
                "date": "2026-08-24",
            },
        )

        self.assertEqual(response.status_code, 400)

    def test_journeys_rejects_same_or_inactive_station(self):
        self._seed_journey_data()

        same_response = self.client.get(
            "/shuttle/journeys",
            params={
                "origin_station_id": 101,
                "destination_station_id": 101,
                "date": "2026-08-24",
            },
        )
        inactive_response = self.client.get(
            "/shuttle/journeys",
            params={
                "origin_station_id": 101,
                "destination_station_id": 104,
                "date": "2026-08-24",
            },
        )

        self.assertEqual(same_response.status_code, 400)
        self.assertEqual(inactive_response.status_code, 404)

    def test_asan_departure_merges_cheonan_asan_destination_directions(self):
        self._seed_asan_cheonan_asan_group_data()

        response = self.client.get(
            "/shuttle/journey-destinations",
            params={"origin_station_id": 201, "date": "2026-08-24"},
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            response.json(),
            [{"station_id": 202, "station_name": "천안아산역"}],
        )

    def test_asan_to_cheonan_asan_returns_both_direction_schedules(self):
        self._seed_asan_cheonan_asan_group_data()

        response = self.client.get(
            "/shuttle/journeys",
            params={
                "origin_station_id": 201,
                "destination_station_id": 202,
                "date": "2026-08-24",
            },
        )

        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertEqual(body["destination_station_name"], "천안아산역")
        self.assertEqual(
            [journey["schedule_id"] for journey in body["journeys"]],
            [3101, 3201],
        )

    def test_directional_origin_matches_schedules_from_both_station_ids(self):
        self._seed_asan_cheonan_asan_group_data()

        destinations_response = self.client.get(
            "/shuttle/journey-destinations",
            params={"origin_station_id": 203, "date": "2026-08-24"},
        )
        journeys_response = self.client.get(
            "/shuttle/journeys",
            params={
                "origin_station_id": 203,
                "destination_station_id": 204,
                "date": "2026-08-24",
            },
        )

        self.assertEqual(destinations_response.status_code, 200)
        self.assertEqual(
            destinations_response.json(),
            [{"station_id": 204, "station_name": "아산캠퍼스"}],
        )
        self.assertEqual(journeys_response.status_code, 200)
        body = journeys_response.json()
        self.assertEqual(body["origin_station_name"], "천안아산역")
        self.assertEqual(
            [journey["schedule_id"] for journey in body["journeys"]],
            [3102, 3202],
        )

    def test_chungmu_hospital_origin_returns_both_direction_destinations(self):
        self._seed_chungmu_hospital_group_data()

        destinations_response = self.client.get(
            "/shuttle/journey-destinations",
            params={"origin_station_id": 401, "date": "2026-08-24"},
        )
        asan_direction_journey_response = self.client.get(
            "/shuttle/journeys",
            params={
                "origin_station_id": 401,
                "destination_station_id": 404,
                "date": "2026-08-24",
            },
        )
        intermediate_journey_response = self.client.get(
            "/shuttle/journeys",
            params={
                "origin_station_id": 401,
                "destination_station_id": 405,
                "date": "2026-08-24",
            },
        )

        self.assertEqual(destinations_response.status_code, 200)
        self.assertEqual(
            destinations_response.json(),
            [
                {"station_id": 404, "station_name": "아산캠퍼스"},
                {"station_id": 403, "station_name": "천안캠퍼스"},
            ],
        )
        self.assertEqual(intermediate_journey_response.status_code, 400)
        self.assertEqual(asan_direction_journey_response.status_code, 200)
        body = asan_direction_journey_response.json()
        self.assertEqual(body["origin_station_name"], "천안 충무병원")
        self.assertEqual(
            [journey["schedule_id"] for journey in body["journeys"]],
            [4201],
        )

    def test_campus_departure_and_arrival_stations_are_grouped(self):
        self._seed_campus_group_data()

        destinations_response = self.client.get(
            "/shuttle/journey-destinations",
            params={"origin_station_id": 501, "date": "2026-08-24"},
        )
        asan_journey_response = self.client.get(
            "/shuttle/journeys",
            params={
                "origin_station_id": 501,
                "destination_station_id": 502,
                "date": "2026-08-24",
            },
        )
        cheonan_journey_response = self.client.get(
            "/shuttle/journeys",
            params={
                "origin_station_id": 501,
                "destination_station_id": 504,
                "date": "2026-08-24",
            },
        )

        self.assertEqual(destinations_response.status_code, 200)
        self.assertEqual(
            destinations_response.json(),
            [
                {"station_id": 503, "station_name": "아산캠퍼스"},
                {"station_id": 505, "station_name": "천안캠퍼스"},
            ],
        )
        self.assertEqual(asan_journey_response.status_code, 200)
        self.assertEqual(
            [
                journey["schedule_id"]
                for journey in asan_journey_response.json()["journeys"]
            ],
            [5101],
        )
        self.assertEqual(cheonan_journey_response.status_code, 200)
        self.assertEqual(
            [
                journey["schedule_id"]
                for journey in cheonan_journey_response.json()["journeys"]
            ],
            [5201],
        )

    def test_invalidate_shuttle_station_cache_includes_route_membership_pattern(self):
        with patch("routers.admin_v2.delete_pattern") as mock_delete_pattern:
            admin_v2.invalidate_shuttle_station_cache()

        mock_delete_pattern.assert_has_calls(
            [
                call("stations:*"),
                call("station_schedules:*"),
                call("schedule_stops:*"),
                call("station_route_memberships:*"),
                call("route_stations:*"),
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
        self.assertIn(call("route_stations:*"), mock_delete_pattern.mock_calls)

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
        self.assertIn(call("route_stations:*"), mock_delete_pattern.mock_calls)

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
        self.assertIn(call("route_stations:*"), mock_delete_pattern.mock_calls)


if __name__ == "__main__":
    unittest.main()
