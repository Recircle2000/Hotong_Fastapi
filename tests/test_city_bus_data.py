import asyncio
import json
import os
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from unittest import mock

import httpx
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, event
from sqlalchemy.orm import sessionmaker
from starlette.middleware.sessions import SessionMiddleware

os.environ["SUPABASE_URL"] = "sqlite:///:memory:"
os.environ.pop("SUPABASE_PASSWORD", None)
os.environ["FIREBASE_CREDENTIALS_B64"] = ""

from database import get_db  # noqa: E402
from models import Base, CityBusRelease, CityBusRoute, User  # noqa: E402
from routers import admin_v2, admin_v2_city_bus, app_config, bus  # noqa: E402
from services import city_bus_bis, city_bus_data  # noqa: E402
from services.admin_auth import clear_login_failures  # noqa: E402
from services.app_settings import clear_app_settings_cache  # noqa: E402
from utils.security import hash_password  # noqa: E402


STORAGE_URL = "https://example.supabase.co/storage/v1/object/public/bus-data/"

FEATURE_COLLECTION = {
    "type": "FeatureCollection",
    "features": [{"type": "Feature", "properties": {}, "geometry": {"type": "Point", "coordinates": [127.0, 36.7]}}],
}
STOPS_RESPONSE = {
    "response": {
        "header": {"resultCode": "00"},
        "body": {"items": {"item": [{"nodenm": "호서대학교"}, {"nodenm": "천안아산역"}]}},
    }
}


class CityBusDataTests(unittest.TestCase):
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
        cls.app.add_middleware(SessionMiddleware, secret_key="test-secret")
        cls.app.include_router(admin_v2.router)
        cls.app.include_router(admin_v2_city_bus.router)
        cls.app.include_router(app_config.router)
        cls.app.include_router(bus.router)

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
        clear_login_failures()
        clear_app_settings_cache()
        city_bus_data.clear_city_bus_cache()
        # 버스 라우터는 요청 밖(위치 갱신 루프)에서도 시간표를 읽으므로 세션 팩토리를 직접 바꾼다.
        patcher = mock.patch.object(bus, "SessionLocal", self.SessionLocal)
        patcher.start()
        self.addCleanup(patcher.stop)
        missing_file = mock.patch.object(bus, "TIMETABLE_FILE_PATH", "does-not-exist.json")
        missing_file.start()
        self.addCleanup(missing_file.stop)
        # 버스 위치 루프가 들고 있는 시간표 상태도 테스트마다 비운다.
        for state in (
            mock.patch.dict(bus.bus_timetable, clear=True),
            mock.patch.dict(bus.parsed_bus_timetable, clear=True),
            mock.patch.object(bus, "loaded_timetable_version", None),
            mock.patch.object(bus, "timetable_next_check_at", None),
            mock.patch.object(bus, "timetable_seen_generation", None),
            mock.patch.object(bus, "timetable_next_effective_at", None),
        ):
            state.start()
            self.addCleanup(state.stop)

        self.client = TestClient(self.app)
        with self.SessionLocal() as db:
            for table in reversed(Base.metadata.sorted_tables):
                db.execute(table.delete())
            db.add(User(email="admin@example.com", hashed_password=hash_password("secret123"), is_admin=True))
            db.add(CityBusRoute(route_key="810_UP", sort_order=0, origin="아산터미널", terminus="호서대", times=["07:10", "08:20"]))
            db.add(CityBusRoute(route_key="810_DOWN", sort_order=1, origin="호서대", terminus="아산터미널", times=["09:00"]))
            db.commit()

    def login(self):
        response = self.client.post(
            "/api/admin-v2/auth/login",
            json={"email": "admin@example.com", "password": "secret123"},
        )
        self.assertEqual(response.status_code, 200)

    def publish_timetable(self, **body):
        return self.client.post("/api/admin-v2/city-bus/releases/timetable", json=body)

    # --- 초안 편집 -------------------------------------------------------

    def test_admin_api_requires_login(self):
        self.assertEqual(self.client.get("/api/admin-v2/city-bus/routes").status_code, 401)

    def test_update_route_normalizes_and_sorts_times(self):
        self.login()
        response = self.client.put(
            "/api/admin-v2/city-bus/routes/810_UP",
            json={"origin": "아산터미널", "terminus": "호서대", "times": ["9:05", "07:10", " 08:20 "]},
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["times"], ["07:10", "08:20", "09:05"])

    def test_update_route_rejects_bad_or_duplicate_times(self):
        self.login()
        for times in (["25:00"], ["7시"], ["07:10", "7:10"]):
            response = self.client.put(
                "/api/admin-v2/city-bus/routes/810_UP",
                json={"origin": "아산터미널", "terminus": "호서대", "times": times},
            )
            self.assertEqual(response.status_code, 422, times)

    def test_create_route_validates_key(self):
        self.login()
        bad = self.client.post(
            "/api/admin-v2/city-bus/routes",
            json={"route_key": "810", "origin": "a", "terminus": "b", "times": []},
        )
        self.assertEqual(bad.status_code, 422)
        good = self.client.post(
            "/api/admin-v2/city-bus/routes",
            json={"route_key": "순환5_UP", "origin": "천안아산역", "terminus": "호서대", "times": ["06:50"]},
        )
        self.assertEqual(good.status_code, 201)
        self.assertEqual(good.json()["sort_order"], 2)

    def test_upload_geojson_and_stops_validate_shape(self):
        self.login()
        bad = self.client.put("/api/admin-v2/city-bus/routes/810_UP/geojson", json={"type": "Feature"})
        self.assertEqual(bad.status_code, 422)
        geojson = self.client.put("/api/admin-v2/city-bus/routes/810_UP/geojson", json=FEATURE_COLLECTION)
        self.assertEqual(geojson.json()["geojson_feature_count"], 1)
        stops = self.client.put("/api/admin-v2/city-bus/routes/810_UP/stops", json=STOPS_RESPONSE)
        self.assertEqual(stops.json()["stop_count"], 2)
        missing = self.client.put("/api/admin-v2/city-bus/routes/999_UP/stops", json=STOPS_RESPONSE)
        self.assertEqual(missing.status_code, 404)

    def test_route_list_and_edits_do_not_read_map_json(self):
        self.login()
        self.client.put("/api/admin-v2/city-bus/routes/810_UP/geojson", json=FEATURE_COLLECTION)
        self.client.put("/api/admin-v2/city-bus/routes/810_UP/stops", json=STOPS_RESPONSE)

        selects: list[str] = []

        def record(conn, cursor, statement, parameters, context, executemany):
            if statement.lstrip().upper().startswith("SELECT") and "city_bus_routes" in statement:
                selects.append(statement)

        event.listen(self.engine, "before_cursor_execute", record)
        try:
            listed = self.client.get("/api/admin-v2/city-bus/routes").json()
            self.client.put(
                "/api/admin-v2/city-bus/routes/810_UP",
                json={"origin": "아산터미널", "terminus": "호서대", "times": ["07:00"]},
            )
            self.client.put("/api/admin-v2/city-bus/routes/810_DOWN/geojson", json=FEATURE_COLLECTION)
            self.publish_timetable()
        finally:
            event.remove(self.engine, "before_cursor_execute", record)

        self.assertTrue(selects)
        for statement in selects:
            self.assertNotIn("route_geojson", statement)
            self.assertNotIn("stops_json", statement)
        first = next(route for route in listed if route["route_key"] == "810_UP")
        self.assertEqual((first["geojson_feature_count"], first["stop_count"]), (1, 2))

    # --- 시간표 게시 -----------------------------------------------------

    def test_publish_timetable_serves_same_format_as_bus_times_json(self):
        self.login()
        release = self.publish_timetable()
        self.assertEqual(release.status_code, 201)
        version = release.json()["version"]
        self.assertTrue(release.json()["is_current"])

        timetable = self.client.get("/bus-timetable")
        self.assertEqual(timetable.status_code, 200)
        self.assertEqual(
            timetable.json(),
            {
                "version": version,
                "810_UP": {"출발지": "아산터미널", "종점": "호서대", "시간표": ["07:10", "08:20"]},
                "810_DOWN": {"출발지": "호서대", "종점": "아산터미널", "시간표": ["09:00"]},
            },
        )
        self.assertEqual(list(timetable.json())[:3], ["version", "810_UP", "810_DOWN"])
        not_modified = self.client.get("/bus-timetable", headers={"If-None-Match": timetable.headers["etag"]})
        self.assertEqual(not_modified.status_code, 304)

        self.assertEqual(self.client.get("/bus-timetable/version").json(), {"version": version})
        config = self.client.get("/api/app-config").json()
        self.assertEqual(
            config["bus_data"]["timetable"],
            {"version": version, "download_url": "/bus-timetable", "effective_from": None, "sha256": None},
        )
        self.assertIsNone(config["bus_data"]["static"])

    def test_publish_without_changes_is_rejected_and_same_day_gets_suffix(self):
        self.login()
        first = self.publish_timetable().json()["version"]
        self.assertEqual(self.publish_timetable().status_code, 422)

        self.client.put(
            "/api/admin-v2/city-bus/routes/810_DOWN",
            json={"origin": "호서대", "terminus": "아산터미널", "times": ["09:00", "10:00"]},
        )
        second = self.publish_timetable().json()["version"]
        self.assertEqual(second, f"{first}.2")
        # 앱은 날짜 형식이 아니면 문자열로 비교하므로 새 버전이 더 커야 한다.
        self.assertGreater(second, first)
        self.assertEqual(self.client.get("/bus-timetable/version").json()["version"], second)

    def test_scheduled_release_waits_until_effective_time(self):
        now = datetime(2026, 11, 4, 3, 0, tzinfo=timezone.utc)
        with self.SessionLocal() as db:
            current = city_bus_data.publish_timetable(db, admin_id=None, now=now)
            route = db.get(CityBusRoute, "810_UP")
            route.times = ["07:30"]
            db.commit()
            scheduled = city_bus_data.publish_timetable(
                db,
                admin_id=None,
                effective_from=now + timedelta(days=3),
                now=now,
            )
            self.assertEqual(current.version, "2026.11.04")
            # 버전은 적용일 기준이라 예약본이 더 크다.
            self.assertEqual(scheduled.version, "2026.11.07")

            before = city_bus_data.get_effective_release(db, "timetable", now=now + timedelta(days=1))
            after = city_bus_data.get_effective_release(db, "timetable", now=now + timedelta(days=3, minutes=1))
            self.assertEqual(before.version, "2026.11.04")
            self.assertEqual(after.version, "2026.11.07")
            self.assertEqual(after.payload["810_UP"]["시간표"], ["07:30"])

    def test_map_only_route_is_left_out_of_timetable(self):
        self.login()
        created = self.client.post("/api/admin-v2/city-bus/routes", json={"route_key": "900_UP"})
        self.assertEqual(created.status_code, 201)
        self.publish_timetable()
        self.assertNotIn("900_UP", self.client.get("/bus-timetable").json())

        # 출발지만 채우고 종점을 비우면 게시를 막는다.
        self.client.put("/api/admin-v2/city-bus/routes/900_UP", json={"origin": "탕정", "times": ["07:00"]})
        self.assertEqual(self.publish_timetable().status_code, 422)

    def test_release_file_download(self):
        self.login()
        release_id = self.publish_timetable().json()["id"]
        response = self.client.get(f"/api/admin-v2/city-bus/releases/{release_id}/file")
        self.assertEqual(response.status_code, 200)
        self.assertIn("bus_times.json", response.headers["content-disposition"])
        self.assertIn("810_UP", response.json())

    def test_bus_loop_reads_published_timetable(self):
        with self.SessionLocal() as db:
            city_bus_data.publish_timetable(db, admin_id=None)
        bus.loaded_timetable_version = None
        bus.load_bus_timetable()
        self.assertEqual(bus.parsed_bus_timetable["810_UP"], [(7, 10), (8, 20)])

    def _release_selects(self, action):
        selects: list[str] = []

        def record(conn, cursor, statement, parameters, context, executemany):
            if statement.lstrip().upper().startswith("SELECT") and "city_bus_releases" in statement:
                selects.append(statement)

        event.listen(self.engine, "before_cursor_execute", record)
        try:
            result = action()
        finally:
            event.remove(self.engine, "before_cursor_execute", record)
        return result, selects

    def test_timetable_check_skips_payload_when_version_unchanged(self):
        with self.SessionLocal() as db:
            version = city_bus_data.publish_timetable(db, admin_id=None).version

        with self.SessionLocal() as db:
            first = city_bus_data.check_effective_timetable(db, None)
        self.assertEqual(first.version, version)
        self.assertEqual(first.payload["810_UP"]["시간표"], ["07:10", "08:20"])

        with self.SessionLocal() as db:
            same, selects = self._release_selects(lambda: city_bus_data.check_effective_timetable(db, version))
        self.assertEqual(same.version, version)
        self.assertIsNone(same.payload)
        self.assertEqual(len(selects), 1)
        self.assertNotIn("city_bus_releases.payload", selects[0])

    def test_timetable_check_reports_next_scheduled_time(self):
        now = datetime(2026, 11, 4, 3, 0, tzinfo=timezone.utc)
        with self.SessionLocal() as db:
            current = city_bus_data.publish_timetable(db, admin_id=None, now=now)
            db.get(CityBusRoute, "810_UP").times = ["07:30"]
            db.commit()
            city_bus_data.publish_timetable(db, admin_id=None, effective_from=now + timedelta(days=3), now=now)

            check = city_bus_data.check_effective_timetable(db, current.version, now=now + timedelta(days=1))
            self.assertEqual(check.version, current.version)
            self.assertEqual(check.next_effective_at, now + timedelta(days=3))

            later = city_bus_data.check_effective_timetable(db, current.version, now=now + timedelta(days=3, seconds=1))
            self.assertEqual(later.version, "2026.11.07")
            self.assertEqual(later.payload["810_UP"]["시간표"], ["07:30"])
            self.assertIsNone(later.next_effective_at)

    def test_bus_timetable_reload_rules(self):
        now = datetime(2026, 11, 4, 3, 0, tzinfo=timezone.utc)
        # 처음에는 무조건 읽는다.
        self.assertTrue(bus.timetable_reload_due(100.0, now, 5))

        bus.timetable_next_check_at = 100.0 + bus.BUS_TIMETABLE_RECHECK_SECONDS
        bus.timetable_seen_generation = 5
        self.assertFalse(bus.timetable_reload_due(200.0, now, 5))
        # 대시보드에서 게시했다.
        self.assertTrue(bus.timetable_reload_due(200.0, now, 6))
        # 정기 확인 시각이 됐다.
        self.assertTrue(bus.timetable_reload_due(100.0 + bus.BUS_TIMETABLE_RECHECK_SECONDS, now, 5))

        bus.timetable_next_effective_at = now + timedelta(hours=1)
        self.assertFalse(bus.timetable_reload_due(200.0, now + timedelta(minutes=59), 5))
        # 예약 게시가 적용되는 시각이 지났다.
        self.assertTrue(bus.timetable_reload_due(200.0, now + timedelta(hours=1), 5))

    def test_bus_loop_reads_db_only_after_publish(self):
        with self.SessionLocal() as db:
            first = city_bus_data.publish_timetable(db, admin_id=None).version

        asyncio.run(bus.refresh_timetable_if_due())
        self.assertEqual(bus.loaded_timetable_version, first)

        # 바뀐 게 없으면 DB를 읽지 않는다.
        _, selects = self._release_selects(lambda: asyncio.run(bus.refresh_timetable_if_due()))
        self.assertEqual(selects, [])

        with self.SessionLocal() as db:
            db.get(CityBusRoute, "810_UP").times = ["06:40"]
            db.commit()
            second = city_bus_data.publish_timetable(db, admin_id=None).version

        asyncio.run(bus.refresh_timetable_if_due())
        self.assertEqual(bus.loaded_timetable_version, second)
        self.assertEqual(bus.parsed_bus_timetable["810_UP"], [(6, 40)])

    def test_bus_loop_keeps_timetable_when_db_check_fails(self):
        with self.SessionLocal() as db:
            version = city_bus_data.publish_timetable(db, admin_id=None).version
        self.assertTrue(bus.load_bus_timetable())

        with mock.patch.object(bus, "check_effective_timetable", side_effect=RuntimeError("db down")):
            self.assertFalse(bus.load_bus_timetable())
        self.assertEqual(bus.loaded_timetable_version, version)
        self.assertEqual(bus.parsed_bus_timetable["810_UP"], [(7, 10), (8, 20)])

    def test_missing_release_falls_back_to_file(self):
        with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False, encoding="utf-8") as handle:
            json.dump({"version": "2026.11.01", "810_UP": {"시간표": ["06:00"]}}, handle)
        self.addCleanup(os.unlink, handle.name)
        with mock.patch.object(bus, "TIMETABLE_FILE_PATH", handle.name):
            self.assertEqual(self.client.get("/bus-timetable/version").json(), {"version": "2026.11.01"})
        config = self.client.get("/api/app-config").json()
        self.assertIsNone(config["bus_data"]["timetable"])

    # --- 노선도 게시 -----------------------------------------------------

    def test_publish_static_uploads_file_and_exposes_it_in_app_config(self):
        self.login()
        self.client.put("/api/admin-v2/city-bus/routes/810_UP/geojson", json=FEATURE_COLLECTION)
        self.client.put("/api/admin-v2/city-bus/routes/810_UP/stops", json=STOPS_RESPONSE)

        uploads = []

        def fake_upload(path, body, content_type="application/json"):
            uploads.append((path, json.loads(body)))
            return STORAGE_URL + path

        with mock.patch.object(city_bus_data, "upload_to_storage", side_effect=fake_upload):
            response = self.client.post("/api/admin-v2/city-bus/releases/static", json={})
        self.assertEqual(response.status_code, 201)
        version = response.json()["version"]

        path, payload = uploads[0]
        self.assertEqual(path, f"bus-static/{version}.json")
        self.assertEqual(payload["version"], version)
        self.assertEqual(payload["routes"], {"810_UP": FEATURE_COLLECTION})
        self.assertEqual(payload["stops"], {"810_UP": STOPS_RESPONSE})

        static = self.client.get("/api/app-config").json()["bus_data"]["static"]
        self.assertEqual(static["version"], version)
        self.assertEqual(static["download_url"], STORAGE_URL + path)
        self.assertEqual(len(static["sha256"]), 64)

    def test_failed_upload_leaves_no_release(self):
        self.login()
        self.client.put("/api/admin-v2/city-bus/routes/810_UP/geojson", json=FEATURE_COLLECTION)
        with mock.patch.object(
            city_bus_data,
            "upload_to_storage",
            side_effect=city_bus_data.CityBusStorageError("boom"),
        ):
            response = self.client.post("/api/admin-v2/city-bus/releases/static", json={})
        self.assertEqual(response.status_code, 502)
        with self.SessionLocal() as db:
            self.assertEqual(db.query(CityBusRelease).count(), 0)


    # --- BIS 시간표 비교 --------------------------------------------------

    def test_bis_timetable_returns_times_without_saving(self):
        self.login()
        fetched = city_bus_bis.BisTimetable(source="asan", source_url="https://bus.asan.go.kr/x", times=["07:00", "08:40"])
        with mock.patch.object(city_bus_bis, "fetch_bis_timetable", return_value=fetched) as fetch:
            response = self.client.get("/api/admin-v2/city-bus/routes/810_UP/bis-timetable")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["times"], ["07:00", "08:40"])
        self.assertEqual(response.json()["source"], "asan")
        self.assertEqual(fetch.call_args.args[0], city_bus_bis.BisSource("asan", "288000091"))
        with self.SessionLocal() as db:
            self.assertEqual(db.get(CityBusRoute, "810_UP").times, ["07:10", "08:20"])

    def test_bis_timetable_errors(self):
        self.assertEqual(self.client.get("/api/admin-v2/city-bus/routes/810_UP/bis-timetable").status_code, 401)
        self.login()
        self.assertEqual(self.client.get("/api/admin-v2/city-bus/routes/999_UP/bis-timetable").status_code, 404)
        with self.SessionLocal() as db:
            db.add(CityBusRoute(route_key="900_UP", sort_order=2, origin="", terminus="", times=[]))
            db.commit()
        missing = self.client.get("/api/admin-v2/city-bus/routes/900_UP/bis-timetable")
        self.assertEqual(missing.status_code, 422)
        with mock.patch.object(city_bus_bis, "fetch_bis_timetable", side_effect=city_bus_bis.CityBusBisError("down")):
            failed = self.client.get("/api/admin-v2/city-bus/routes/810_UP/bis-timetable")
        self.assertEqual(failed.status_code, 502)
        self.assertEqual(failed.json()["detail"], "down")

    # --- 정류장 공공데이터 비교 ---------------------------------------------

    def test_stops_compare_uses_stored_route_id_without_saving(self):
        self.login()
        stored = {"response": {"body": {"items": {"item": [
            {"nodeid": "A", "nodeord": 1, "nodenm": "호서대", "gpslati": 36.7, "gpslong": 127.0, "routeid": "ASB285000245"},
        ]}}}}
        self.client.put("/api/admin-v2/city-bus/routes/810_UP/stops", json=stored)
        fetched = {"response": {"header": {"resultCode": "00"}, "body": {"totalCount": 1, "items": {"item": [
            {"nodeid": "A", "nodeord": 1, "nodenm": "호서대학교", "gpslati": 36.7, "gpslong": 127.0, "routeid": "ASB285000245"},
        ]}}}}
        with mock.patch.object(city_bus_bis, "fetch_route_stops", return_value=fetched) as fetch:
            response = self.client.get("/api/admin-v2/city-bus/routes/810_UP/stops-compare")
        self.assertEqual(response.status_code, 200)
        fetch.assert_called_once_with("ASB285000245", "34040")
        body = response.json()
        self.assertEqual(body["renamed"], [{"nodeid": "A", "nodeord": 1, "nodenm": "호서대학교", "before": "호서대"}])
        self.assertEqual(body["fetched"], fetched)
        with self.SessionLocal() as db:
            self.assertEqual(db.get(CityBusRoute, "810_UP").stops_json, stored)

    def test_stops_compare_errors(self):
        self.assertEqual(self.client.get("/api/admin-v2/city-bus/routes/810_UP/stops-compare").status_code, 401)
        self.login()
        self.assertEqual(self.client.get("/api/admin-v2/city-bus/routes/999_UP/stops-compare").status_code, 404)
        with self.SessionLocal() as db:
            db.add(CityBusRoute(route_key="900_UP", sort_order=2, origin="", terminus="", times=[]))
            db.commit()
        self.assertEqual(self.client.get("/api/admin-v2/city-bus/routes/900_UP/stops-compare").status_code, 422)
        with mock.patch.object(city_bus_bis, "fetch_route_stops", side_effect=city_bus_bis.CityBusBisError("키 오류")):
            failed = self.client.get("/api/admin-v2/city-bus/routes/810_UP/stops-compare")
        self.assertEqual(failed.status_code, 502)
        self.assertEqual(failed.json()["detail"], "키 오류")

    # --- 변경이력 ---------------------------------------------------------

    def test_route_label(self):
        self.assertEqual(city_bus_data.route_label("810_UP"), "810 상행")
        self.assertEqual(city_bus_data.route_label("순환5_DOWN"), "순환5 하행")
        self.assertEqual(city_bus_data.route_label("weird"), "weird")

    def test_summarize_timetable_changes(self):
        before = {
            "version": "a",
            "810_UP": {"출발지": "터미널", "종점": "호서대", "시간표": ["07:10", "08:20"]},
            "820_UP": {"출발지": "터미널", "종점": "호서대", "시간표": ["09:00"]},
            "821_UP": {"출발지": "터미널", "종점": "호서대", "시간표": ["10:00"]},
        }
        after = {
            "version": "b",
            "810_UP": {"출발지": "터미널", "종점": "호서대", "시간표": ["07:10", "09:30"]},
            "820_UP": {"출발지": "아산역", "종점": "호서대", "시간표": ["09:00"]},
            "822_DOWN": {"출발지": "호서대", "종점": "터미널", "시간표": ["12:20"]},
        }
        self.assertEqual(
            city_bus_data.summarize_timetable_changes(before, after),
            [
                "810 상행: 09:30 추가, 08:20 삭제",
                "820 상행: 출발지·종점 변경",
                "822 하행 노선 추가",
                "821 상행 노선 삭제",
            ],
        )

    def test_summarize_timetable_shortens_many_times(self):
        before = {"24_UP": {"출발지": "a", "종점": "b", "시간표": []}}
        after = {"24_UP": {"출발지": "a", "종점": "b", "시간표": [f"{hour:02d}:00" for hour in range(6, 13)]}}
        self.assertEqual(city_bus_data.summarize_timetable_changes(before, after), ["24 상행: 06:00 외 6개 추가"])

    def test_summarize_static_changes(self):
        before = {"810_UP": {"geojson": "g1", "stops": "s1"}, "820_UP": {"geojson": "g", "stops": "s"}, "900_UP": {"geojson": "x", "stops": None}}
        after = {"810_UP": {"geojson": "g1", "stops": "s2"}, "820_UP": {"geojson": "g2", "stops": "s2"}, "1001_UP": {"geojson": None, "stops": "s"}}
        self.assertEqual(
            city_bus_data.summarize_static_changes(before, after),
            ["810 상행: 정류장 변경", "820 상행: 노선 선형·정류장 변경", "1001 상행 노선 추가", "900 상행 노선 삭제"],
        )

    def test_publish_timetable_stores_note_and_changes(self):
        self.login()
        first = self.publish_timetable(note="  첫 배포  ")
        self.assertEqual(first.status_code, 201)
        self.assertEqual(first.json()["note"], "첫 배포")
        self.assertIsNone(first.json()["changes"])

        self.client.put(
            "/api/admin-v2/city-bus/routes/810_UP",
            json={"origin": "아산터미널", "terminus": "호서대", "times": ["07:10", "08:20", "09:40"]},
        )
        second = self.publish_timetable()
        self.assertEqual(second.status_code, 201)
        self.assertIsNone(second.json()["note"])
        self.assertEqual(second.json()["changes"], ["810 상행: 09:40 추가"])

        self.assertEqual(self.publish_timetable(note="가" * 201).status_code, 422)

    def test_public_history_lists_applied_releases_newest_first(self):
        self.login()
        self.publish_timetable(note="첫 배포")
        self.client.put(
            "/api/admin-v2/city-bus/routes/810_UP",
            json={"origin": "아산터미널", "terminus": "호서대", "times": ["07:10"]},
        )
        self.publish_timetable()
        self.client.put(
            "/api/admin-v2/city-bus/routes/810_UP",
            json={"origin": "아산터미널", "terminus": "호서대", "times": ["07:15"]},
        )
        future = (datetime.now(timezone.utc) + timedelta(days=3)).isoformat()
        self.publish_timetable(effective_from=future, note="예약")

        self.client.cookies.clear()
        response = self.client.get("/api/bus-data/history?kind=timetable")
        self.assertEqual(response.status_code, 200)
        self.assertIn("max-age=60", response.headers["cache-control"])
        items = response.json()
        self.assertEqual(len(items), 2)
        self.assertEqual(items[0]["changes"], ["810 상행: 08:20 삭제"])
        self.assertIsNone(items[1]["changes"])
        self.assertEqual(items[1]["note"], "첫 배포")
        self.assertEqual(self.client.get("/api/bus-data/history?kind=static").json(), [])
        self.assertEqual(self.client.get("/api/bus-data/history?kind=nope").status_code, 422)

    def test_publish_static_summarizes_against_previous_file_without_hashes(self):
        self.login()
        self.client.put("/api/admin-v2/city-bus/routes/810_UP/geojson", json=FEATURE_COLLECTION)
        self.client.put("/api/admin-v2/city-bus/routes/810_UP/stops", json=STOPS_RESPONSE)
        # 이관 때처럼 해시 없이 등록된 직전 게시본. 그 Storage 파일에는 정류장만 다르다.
        old_file = {"version": "old", "routes": {"810_UP": FEATURE_COLLECTION}, "stops": {"810_UP": {"response": {"body": {"items": []}}}}}
        with self.SessionLocal() as db:
            db.add(CityBusRelease(
                kind="static",
                version="2026.09.14",
                download_url=STORAGE_URL + "bus-static/2026.09.14.json",
                published_at=datetime.now(timezone.utc) - timedelta(days=1),
            ))
            db.commit()

        def fake_get(url, timeout=None):
            self.assertEqual(url, STORAGE_URL + "bus-static/2026.09.14.json")
            return httpx.Response(200, content=json.dumps(old_file).encode("utf-8"), request=httpx.Request("GET", url))

        with mock.patch.object(city_bus_data, "upload_to_storage", side_effect=lambda path, body, **kw: STORAGE_URL + path), \
                mock.patch.object(city_bus_data.httpx, "get", side_effect=fake_get):
            first = self.client.post("/api/admin-v2/city-bus/releases/static", json={"note": "정류장 갱신"})
        self.assertEqual(first.status_code, 201)
        self.assertEqual(first.json()["changes"], ["810 상행: 정류장 변경"])

        # 다음 게시는 저장된 해시와 비교하므로 Storage를 다시 읽지 않는다.
        self.client.put("/api/admin-v2/city-bus/routes/810_DOWN/stops", json=STOPS_RESPONSE)
        with mock.patch.object(city_bus_data, "upload_to_storage", side_effect=lambda path, body, **kw: STORAGE_URL + path), \
                mock.patch.object(city_bus_data.httpx, "get", side_effect=AssertionError("no download")):
            second = self.client.post("/api/admin-v2/city-bus/releases/static", json={})
        self.assertEqual(second.status_code, 201)
        self.assertEqual(second.json()["changes"], ["810 하행 노선 추가"])


if __name__ == "__main__":
    unittest.main()
