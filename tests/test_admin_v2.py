import os
import tempfile
import unittest

from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from starlette.middleware.sessions import SessionMiddleware

from database import get_db
from models import Base, User
from routers import admin_v2
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


if __name__ == "__main__":
    unittest.main()
