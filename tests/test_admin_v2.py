import os
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from uuid import uuid4

from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from starlette.middleware.sessions import SessionMiddleware

os.environ["SUPABASE_URL"] = "sqlite:///:memory:"
os.environ.pop("SUPABASE_PASSWORD", None)
# 로컬 .env에 실제 서비스 계정 키가 있어도 테스트에서는 FCM에 보내지 않는다.
os.environ["FIREBASE_CREDENTIALS_B64"] = ""

from database import get_db
from models import Base, TaxiLocation, User
from routers import admin_v2, app_config
from schemas.taxi import TaxiPartyCreateRequest, TaxiReportCreateRequest
from services.app_settings import clear_app_settings_cache
from services.taxi import create_chat_message, create_party, join_party
from services.taxi_report import create_report
from utils.security import hash_password


class AdminV2ApiTests(unittest.TestCase):
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
        cls.app.add_middleware(SessionMiddleware, secret_key="test-session-secret")
        cls.app.include_router(admin_v2.router)
        cls.app.include_router(app_config.router)

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
            db.add(
                User(
                    email="user@example.com",
                    hashed_password=hash_password("secret123"),
                    is_admin=False,
                )
            )
            db.commit()

    def test_login_success_sets_session_and_returns_user(self):
        response = self.client.post(
            "/api/admin-v2/auth/login",
            json={"email": "admin@example.com", "password": "secret123"},
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["user"]["email"], "admin@example.com")

        session_response = self.client.get("/api/admin-v2/auth/session")
        self.assertEqual(session_response.status_code, 200)
        self.assertTrue(session_response.json()["authenticated"])

    def test_login_rejects_invalid_password(self):
        response = self.client.post(
            "/api/admin-v2/auth/login",
            json={"email": "admin@example.com", "password": "wrong-password"},
        )
        self.assertEqual(response.status_code, 401)

    def test_login_rejects_non_admin_user(self):
        response = self.client.post(
            "/api/admin-v2/auth/login",
            json={"email": "user@example.com", "password": "secret123"},
        )
        self.assertEqual(response.status_code, 403)

    def test_notices_require_json_auth(self):
        response = self.client.get("/api/admin-v2/notices")
        self.assertEqual(response.status_code, 401)
        self.assertEqual(response.json()["detail"], "인증이 필요합니다.")

    def test_notice_crud_and_pinned_order(self):
        login_response = self.client.post(
            "/api/admin-v2/auth/login",
            json={"email": "admin@example.com", "password": "secret123"},
        )
        self.assertEqual(login_response.status_code, 200)

        first_notice = self.client.post(
            "/api/admin-v2/notices",
            json={
                "title": "일반 공지",
                "content": "내용 1",
                "notice_type": "App",
                "is_pinned": False,
            },
        )
        self.assertEqual(first_notice.status_code, 201)

        second_notice = self.client.post(
            "/api/admin-v2/notices",
            json={
                "title": "고정 공지",
                "content": "내용 2",
                "notice_type": "shuttle",
                "is_pinned": True,
            },
        )
        self.assertEqual(second_notice.status_code, 201)
        self.assertEqual(second_notice.json()["notice_type"], "shuttle")

        list_response = self.client.get("/api/admin-v2/notices")
        self.assertEqual(list_response.status_code, 200)
        notices = list_response.json()
        self.assertEqual(notices[0]["title"], "고정 공지")
        self.assertEqual(notices[1]["title"], "일반 공지")

        update_response = self.client.put(
            f"/api/admin-v2/notices/{second_notice.json()['id']}",
            json={
                "title": "고정 공지 수정",
                "content": "수정 내용",
                "notice_type": "citybus",
                "is_pinned": True,
            },
        )
        self.assertEqual(update_response.status_code, 200)
        self.assertEqual(update_response.json()["notice_type"], "citybus")

        delete_response = self.client.delete(f"/api/admin-v2/notices/{first_notice.json()['id']}")
        self.assertEqual(delete_response.status_code, 204)

        final_list = self.client.get("/api/admin-v2/notices")
        self.assertEqual(len(final_list.json()), 1)
        self.assertEqual(final_list.json()[0]["title"], "고정 공지 수정")

    def test_logout_clears_session(self):
        login_response = self.client.post(
            "/api/admin-v2/auth/login",
            json={"email": "admin@example.com", "password": "secret123"},
        )
        self.assertEqual(login_response.status_code, 200)

        logout_response = self.client.post("/api/admin-v2/auth/logout")
        self.assertEqual(logout_response.status_code, 200)
        self.assertTrue(logout_response.json()["success"])

        session_response = self.client.get("/api/admin-v2/auth/session")
        self.assertEqual(session_response.status_code, 401)

    def test_emergency_notice_crud_and_status(self):
        login_response = self.client.post(
            "/api/admin-v2/auth/login",
            json={"email": "admin@example.com", "password": "secret123"},
        )
        self.assertEqual(login_response.status_code, 200)

        created = self.client.post(
            "/api/admin-v2/emergency-notices",
            json={
                "category": "shuttle",
                "title": "셔틀 우회 안내",
                "content": "정문 공사로 우회합니다.",
                "created_at": "2099-03-14T09:00:00",
                "end_at": "2099-03-14T12:00:00",
            },
        )
        self.assertEqual(created.status_code, 201)
        self.assertEqual(created.json()["category"], "shuttle")
        self.assertEqual(created.json()["status"], "pending")

        listing = self.client.get("/api/admin-v2/emergency-notices")
        self.assertEqual(listing.status_code, 200)
        self.assertEqual(len(listing.json()), 1)
        self.assertEqual(listing.json()[0]["category_label"], "셔틀 긴급공지")

        updated = self.client.put(
            f"/api/admin-v2/emergency-notices/{created.json()['id']}",
            json={
                "category": "subway",
                "title": "지하철 지연",
                "content": "1호선 지연 중입니다.",
                "created_at": "2099-03-14T10:00:00",
                "end_at": "2099-03-14T13:00:00",
            },
        )
        self.assertEqual(updated.status_code, 200)
        self.assertEqual(updated.json()["category"], "subway")

        deleted = self.client.delete(f"/api/admin-v2/emergency-notices/{created.json()['id']}")
        self.assertEqual(deleted.status_code, 204)
        self.assertEqual(self.client.get("/api/admin-v2/emergency-notices").json(), [])

    def test_emergency_notice_rejects_invalid_time_range(self):
        login_response = self.client.post(
            "/api/admin-v2/auth/login",
            json={"email": "admin@example.com", "password": "secret123"},
        )
        self.assertEqual(login_response.status_code, 200)

        response = self.client.post(
            "/api/admin-v2/emergency-notices",
            json={
                "category": "shuttle",
                "title": "잘못된 시간",
                "content": "종료 시각 검증",
                "created_at": "2099-03-14T12:00:00",
                "end_at": "2099-03-14T11:00:00",
            },
        )
        self.assertEqual(response.status_code, 400)

    def test_shuttle_station_crud(self):
        login_response = self.client.post(
            "/api/admin-v2/auth/login",
            json={"email": "admin@example.com", "password": "secret123"},
        )
        self.assertEqual(login_response.status_code, 200)

        created = self.client.post(
            "/api/admin-v2/shuttle-stations",
            json={
                "name": "정문",
                "latitude": 36.7691,
                "longitude": 127.0739,
                "description": "학교 정문 정류장",
                "image_url": "https://example.com/station-main.jpg",
                "is_active": True,
            },
        )
        self.assertEqual(created.status_code, 201)
        self.assertTrue(created.json()["is_active"])

        created_inactive = self.client.post(
            "/api/admin-v2/shuttle-stations",
            json={
                "name": "후문",
                "latitude": 36.7685,
                "longitude": 127.0751,
                "description": None,
                "image_url": None,
                "is_active": False,
            },
        )
        self.assertEqual(created_inactive.status_code, 201)
        self.assertFalse(created_inactive.json()["is_active"])

        listing = self.client.get("/api/admin-v2/shuttle-stations")
        self.assertEqual(listing.status_code, 200)
        stations = listing.json()
        self.assertEqual(len(stations), 2)
        self.assertEqual(stations[0]["name"], "정문")
        self.assertTrue(stations[0]["is_active"])
        self.assertEqual(stations[1]["name"], "후문")
        self.assertFalse(stations[1]["is_active"])

        updated = self.client.put(
            f"/api/admin-v2/shuttle-stations/{created_inactive.json()['id']}",
            json={
                "name": "후문 변경",
                "latitude": 36.7688,
                "longitude": 127.0755,
                "description": "순환 셔틀 임시 정류장",
                "image_url": "",
                "is_active": True,
            },
        )
        self.assertEqual(updated.status_code, 200)
        self.assertEqual(updated.json()["name"], "후문 변경")
        self.assertTrue(updated.json()["is_active"])
        self.assertIsNone(updated.json()["image_url"])

        deleted = self.client.delete(f"/api/admin-v2/shuttle-stations/{created.json()['id']}")
        self.assertEqual(deleted.status_code, 204)

        final_listing = self.client.get("/api/admin-v2/shuttle-stations")
        self.assertEqual(final_listing.status_code, 200)
        final_stations = final_listing.json()
        self.assertEqual(len(final_stations), 1)
        self.assertEqual(final_stations[0]["name"], "후문 변경")

    def test_taxi_service_switch_updates_public_app_config(self):
        clear_app_settings_cache()
        self.assertTrue(self.client.get("/api/app-config").json()["taxi_enabled"])
        self.assertEqual(
            self.client.put("/api/admin-v2/app-settings", json={"taxi_enabled": False}).status_code,
            401,
        )

        self.client.post(
            "/api/admin-v2/auth/login",
            json={"email": "admin@example.com", "password": "secret123"},
        )
        updated = self.client.put("/api/admin-v2/app-settings", json={"taxi_enabled": False})
        self.assertEqual(updated.status_code, 200)
        self.assertFalse(updated.json()["taxi_enabled"])
        self.assertIsNotNone(updated.json()["taxi_updated_at"])
        self.assertFalse(self.client.get("/api/app-config").json()["taxi_enabled"])
        self.assertFalse(self.client.get("/api/admin-v2/app-settings").json()["taxi_enabled"])

        self.client.put("/api/admin-v2/app-settings", json={"taxi_enabled": True})
        self.assertTrue(self.client.get("/api/app-config").json()["taxi_enabled"])

    def _seed_taxi_reports(self):
        now = datetime(2026, 9, 13, 3, 0, tzinfo=timezone.utc)
        owner_id, member_id, other_id = uuid4(), uuid4(), uuid4()
        with self.SessionLocal() as db:
            departure = TaxiLocation(name="아산캠퍼스", category="campus", sort_order=1)
            destination = TaxiLocation(name="천안아산역", category="station", sort_order=2)
            db.add_all([departure, destination])
            db.commit()
            party = create_party(
                db,
                owner_id,
                TaxiPartyCreateRequest(
                    client_request_id=uuid4(),
                    departure_location_id=departure.id,
                    destination_location_id=destination.id,
                    departure_summary="정문",
                    departure_at=now + timedelta(hours=3),
                    max_members=4,
                ),
                now=now,
            )
            join_party(db, party.id, member_id, now=now)
            join_party(db, party.id, other_id, now=now)
            message = create_chat_message(db, party.id, member_id, uuid4(), "안 갈게요", now=now)
            first = create_report(
                db,
                party.id,
                owner_id,
                TaxiReportCreateRequest(target_label="참여자 1", reason="no_show", message_id=message.id),
                now=now,
            )
            second = create_report(
                db,
                party.id,
                other_id,
                TaxiReportCreateRequest(target_label="참여자 1", reason="abuse", detail="욕설"),
                now=now,
            )
            create_report(
                db,
                party.id,
                member_id,
                TaxiReportCreateRequest(target_label="방장", reason="payment"),
                now=now,
            )
            return first.id, second.id, member_id

    def test_taxi_reports_list_detail_and_review(self):
        first_id, second_id, member_id = self._seed_taxi_reports()
        self.assertEqual(self.client.get("/api/admin-v2/taxi-reports").status_code, 401)
        self.client.post(
            "/api/admin-v2/auth/login",
            json={"email": "admin@example.com", "password": "secret123"},
        )

        listing = self.client.get("/api/admin-v2/taxi-reports", params={"status": "pending"})
        self.assertEqual(listing.status_code, 200, listing.text)
        items = listing.json()["items"]
        self.assertEqual(len(items), 3)
        # 사용자 ID는 응답 어디에도 나오지 않고 익명 ID로만 구분한다.
        self.assertNotIn(str(member_id), listing.text)
        by_id = {item["id"]: item for item in items}
        target_key = by_id[first_id]["target_key"]
        self.assertRegex(target_key, r"^[0-9a-f]{6}$")
        self.assertEqual(by_id[first_id]["target_stats"], {"total_reports": 2, "distinct_reporters": 2})
        self.assertEqual(by_id[first_id]["departure_location_name"], "아산캠퍼스")

        same_target = self.client.get("/api/admin-v2/taxi-reports", params={"target": target_key})
        self.assertEqual({item["id"] for item in same_target.json()["items"]}, {first_id, second_id})

        page = self.client.get("/api/admin-v2/taxi-reports", params={"limit": 2})
        self.assertEqual(len(page.json()["items"]), 2)
        rest = self.client.get(
            "/api/admin-v2/taxi-reports",
            params={"limit": 2, "cursor": page.json()["next_cursor"]},
        )
        self.assertEqual(len(rest.json()["items"]), 1)
        self.assertIsNone(rest.json()["next_cursor"])

        detail = self.client.get(f"/api/admin-v2/taxi-reports/{first_id}").json()
        self.assertEqual(detail["reported_message_id"], detail["messages"][-1]["id"])
        self.assertEqual(detail["messages"][-1]["content"], "안 갈게요")
        self.assertTrue(detail["messages"][-1]["is_target"])
        self.assertEqual([item["id"] for item in detail["other_reports"]], [second_id])
        self.assertFalse(detail["evidence_purged"])

        reviewed = self.client.patch(
            f"/api/admin-v2/taxi-reports/{first_id}",
            json={"status": "resolved", "admin_note": " 경고 예정 "},
        )
        self.assertEqual(reviewed.status_code, 200, reviewed.text)
        self.assertEqual(reviewed.json()["status"], "resolved")
        self.assertEqual(reviewed.json()["admin_note"], "경고 예정")
        self.assertIsNotNone(reviewed.json()["reviewed_at"])
        pending = self.client.get("/api/admin-v2/taxi-reports", params={"status": "pending"})
        self.assertEqual(len(pending.json()["items"]), 2)

        reopened = self.client.patch(f"/api/admin-v2/taxi-reports/{first_id}", json={"status": "pending"})
        self.assertIsNone(reopened.json()["reviewed_at"])
        self.assertEqual(self.client.get("/api/admin-v2/taxi-reports/999999").status_code, 404)

    def test_taxi_sanction_from_report_list_and_revoke(self):
        first_id, second_id, member_id = self._seed_taxi_reports()
        url = f"/api/admin-v2/taxi-reports/{first_id}/sanction"
        payload = {"level": "suspend_3d", "reason": " 노쇼 반복 ", "resolve_pending_reports": True}
        self.assertEqual(self.client.post(url, json=payload).status_code, 401)
        self.client.post(
            "/api/admin-v2/auth/login",
            json={"email": "admin@example.com", "password": "secret123"},
        )

        before = self.client.get(f"/api/admin-v2/taxi-reports/{first_id}").json()
        self.assertEqual(before["suggested_level"], "warning")
        self.assertEqual(before["target_sanctions"], [])

        issued = self.client.post(url, json=payload)
        self.assertEqual(issued.status_code, 200, issued.text)
        detail = issued.json()
        self.assertEqual(detail["status"], "resolved")
        self.assertIsNotNone(detail["sanction_id"])
        self.assertEqual(detail["suggested_level"], "suspend_3d")
        sanction = detail["target_sanctions"][0]
        self.assertEqual(sanction["level"], "suspend_3d")
        self.assertEqual(sanction["reason"], "노쇼 반복")
        self.assertEqual(sanction["report_count"], 2)
        self.assertEqual(sanction["target_key"], detail["target_key"])
        self.assertNotIn(str(member_id), issued.text)
        # 같은 대상의 대기 신고도 함께 처리됐다.
        second = self.client.get(f"/api/admin-v2/taxi-reports/{second_id}").json()
        self.assertEqual(second["status"], "resolved")
        self.assertEqual(second["sanction_id"], detail["sanction_id"])

        active = self.client.get("/api/admin-v2/taxi-sanctions", params={"active": "true"}).json()
        self.assertEqual([item["id"] for item in active["items"]], [sanction["id"]])
        self.assertTrue(active["items"][0]["is_active"])
        by_target = self.client.get(
            "/api/admin-v2/taxi-sanctions",
            params={"target": detail["target_key"]},
        ).json()
        self.assertEqual(len(by_target["items"]), 1)

        revoked = self.client.post(
            f"/api/admin-v2/taxi-sanctions/{sanction['id']}/revoke",
            json={"reason": "이의제기 인정"},
        )
        self.assertEqual(revoked.status_code, 200, revoked.text)
        self.assertFalse(revoked.json()["is_active"])
        self.assertEqual(revoked.json()["revoke_reason"], "이의제기 인정")
        self.assertEqual(
            self.client.get("/api/admin-v2/taxi-sanctions", params={"active": "true"}).json()["items"],
            [],
        )
        again = self.client.post(
            f"/api/admin-v2/taxi-sanctions/{sanction['id']}/revoke",
            json={"reason": "다시"},
        )
        self.assertEqual(again.status_code, 409)
        self.assertEqual(
            self.client.post(url, json={"level": "ban", "reason": "x"}).status_code,
            422,
        )

    def test_taxi_location_crud_and_duplicate_name(self):
        login_response = self.client.post(
            "/api/admin-v2/auth/login",
            json={"email": "admin@example.com", "password": "secret123"},
        )
        self.assertEqual(login_response.status_code, 200)

        created = self.client.post(
            "/api/admin-v2/taxi-locations",
            json={
                "name": "아산캠퍼스",
                "category": "campus",
                "sort_order": 1,
                "is_active": True,
            },
        )
        self.assertEqual(created.status_code, 201)
        self.assertEqual(created.json()["category"], "campus")

        duplicate = self.client.post(
            "/api/admin-v2/taxi-locations",
            json={
                "name": "아산캠퍼스",
                "category": "campus",
                "sort_order": 2,
                "is_active": True,
            },
        )
        self.assertEqual(duplicate.status_code, 409)
        self.assertEqual(duplicate.json()["detail"]["code"], "LOCATION_NAME_EXISTS")

        updated = self.client.put(
            f"/api/admin-v2/taxi-locations/{created.json()['id']}",
            json={
                "name": "아산캠퍼스 정문",
                "category": "campus",
                "sort_order": 3,
                "is_active": False,
            },
        )
        self.assertEqual(updated.status_code, 200)
        self.assertFalse(updated.json()["is_active"])

        listing = self.client.get("/api/admin-v2/taxi-locations")
        self.assertEqual(listing.status_code, 200)
        self.assertEqual(listing.json()[0]["name"], "아산캠퍼스 정문")

        deleted = self.client.delete(
            f"/api/admin-v2/taxi-locations/{created.json()['id']}"
        )
        self.assertEqual(deleted.status_code, 204)


if __name__ == "__main__":
    unittest.main()
