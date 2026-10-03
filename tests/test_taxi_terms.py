import os
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, patch
from uuid import uuid4

os.environ.setdefault("SUPABASE_URL", "sqlite://")
# 로컬 .env에 실제 서비스 계정 키가 있어도 테스트에서는 FCM에 보내지 않는다.
os.environ["FIREBASE_CREDENTIALS_B64"] = ""

from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from database import get_db
from models import Base, TaxiLocation, TaxiTermsAgreement
from routers import taxi
from schemas.app_auth import CurrentAppUser
from schemas.taxi import TaxiMessageSendEvent
from services.taxi import TaxiServiceError
from services.taxi_terms import TAXI_TERMS_VERSION, agree_terms, terms_required
from utils.supabase_security import get_current_app_user


class TaxiTermsTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.db_fd, cls.db_path = tempfile.mkstemp(suffix=".db")
        cls.engine = create_engine(
            f"sqlite:///{cls.db_path}",
            connect_args={"check_same_thread": False},
        )
        cls.SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=cls.engine)
        Base.metadata.create_all(cls.engine)
        cls.current_user_id = uuid4()

        app = FastAPI()
        app.include_router(taxi.router)

        def override_get_db():
            with cls.SessionLocal() as db:
                yield db

        app.dependency_overrides[get_db] = override_get_db
        app.dependency_overrides[get_current_app_user] = lambda: CurrentAppUser(
            user_id=cls.current_user_id
        )
        cls.client = TestClient(app)
        cls.patches = [
            patch("routers.taxi.publish_message", new=AsyncMock()),
            patch("routers.taxi.publish_party_updated", new=AsyncMock()),
            patch("routers.taxi.SessionLocal", new=cls.SessionLocal),
        ]
        for item in cls.patches:
            item.start()

    @classmethod
    def tearDownClass(cls):
        for item in cls.patches:
            item.stop()
        Base.metadata.drop_all(cls.engine)
        cls.engine.dispose()
        os.close(cls.db_fd)
        os.unlink(cls.db_path)

    def setUp(self):
        type(self).current_user_id = uuid4()
        with self.SessionLocal() as db:
            for table in reversed(Base.metadata.sorted_tables):
                db.execute(table.delete())
            db.add_all(
                [
                    TaxiLocation(name="아산캠퍼스", category="campus", sort_order=1),
                    TaxiLocation(name="천안아산역", category="station", sort_order=2),
                ]
            )
            db.commit()

    def _agree(self, version=TAXI_TERMS_VERSION):
        return self.client.put("/api/taxi/me/terms", json={"version": version})

    def _create_party(self):
        locations = self.client.get("/api/taxi/locations").json()
        candidate = datetime.now(timezone.utc) + timedelta(hours=3)
        departure_at = candidate.replace(minute=(candidate.minute // 10) * 10, second=0, microsecond=0)
        return self.client.post(
            "/api/taxi/parties",
            json={
                "client_request_id": str(uuid4()),
                "departure_location_id": locations[0]["id"],
                "destination_location_id": locations[1]["id"],
                "departure_summary": "정문 택시승강장",
                "departure_at": departure_at.isoformat(),
                "max_members": 4,
            },
        )

    def _terms_required(self):
        return self.client.get("/api/taxi/me/restriction").json()["terms_required"]

    def test_required_until_agreed(self):
        self.assertTrue(self._terms_required())
        self.assertTrue(self.client.get("/api/taxi/home", params={"date": "2026-10-03"}).json()["restriction"]["terms_required"])

        self.assertEqual(self._agree().status_code, 204)
        self.assertFalse(self._terms_required())
        # 다시 동의해도 기록은 하나다.
        self.assertEqual(self._agree().status_code, 204)
        with self.SessionLocal() as db:
            self.assertEqual(db.query(TaxiTermsAgreement).count(), 1)

    def test_outdated_version_is_rejected(self):
        response = self._agree(TAXI_TERMS_VERSION + 1)
        self.assertEqual(response.status_code, 409)
        self.assertEqual(response.json()["detail"]["code"], "TERMS_OUTDATED")
        self.assertTrue(self._terms_required())

    def test_old_agreement_requires_agreeing_again(self):
        with self.SessionLocal() as db:
            db.add(TaxiTermsAgreement(user_id=self.current_user_id, version=TAXI_TERMS_VERSION))
            db.commit()
            with patch("services.taxi_terms.TAXI_TERMS_VERSION", TAXI_TERMS_VERSION + 1):
                self.assertTrue(terms_required(db, self.current_user_id))
                agree_terms(db, self.current_user_id, TAXI_TERMS_VERSION + 1)
                self.assertFalse(terms_required(db, self.current_user_id))

    def test_create_join_and_chat_need_agreement(self):
        owner_id = self.current_user_id
        blocked = self._create_party()
        self.assertEqual(blocked.status_code, 403)
        self.assertEqual(blocked.json()["detail"]["code"], "TERMS_REQUIRED")

        self._agree()
        created = self._create_party()
        self.assertEqual(created.status_code, 201, created.text)
        party_id = created.json()["id"]

        member_id = uuid4()
        type(self).current_user_id = member_id
        join = self.client.post(f"/api/taxi/parties/{party_id}/join")
        self.assertEqual(join.status_code, 403)
        self.assertEqual(join.json()["detail"]["code"], "TERMS_REQUIRED")
        # 둘러보기는 동의 없이도 된다.
        self.assertEqual(self.client.get(f"/api/taxi/parties/{party_id}").status_code, 200)

        self._agree()
        self.assertEqual(self.client.post(f"/api/taxi/parties/{party_id}/join").status_code, 200)

        # 동의 기록이 없는 참여자(약관 도입 전부터 참여 중이던 사용자)는 채팅을 보낼 수 없다.
        with self.SessionLocal() as db:
            db.query(TaxiTermsAgreement).filter(TaxiTermsAgreement.user_id == member_id).delete()
            db.commit()
        event = TaxiMessageSendEvent(
            type="message.send",
            party_id=party_id,
            client_message_id=uuid4(),
            content="안녕하세요",
        )
        with self.assertRaises(TaxiServiceError) as raised:
            taxi._save_socket_message(member_id, event)
        self.assertEqual(raised.exception.code, "TERMS_REQUIRED")

        events, _, created_new = taxi._save_socket_message(owner_id, event.model_copy(update={"client_message_id": uuid4()}))
        self.assertTrue(created_new)
        self.assertTrue(events)


if __name__ == "__main__":
    unittest.main()
