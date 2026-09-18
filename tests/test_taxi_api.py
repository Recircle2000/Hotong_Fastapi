import os
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, patch
from uuid import UUID, uuid4
from zoneinfo import ZoneInfo

os.environ.setdefault("SUPABASE_URL", "sqlite://")

from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from database import get_db
from models import Base, TaxiLocation, TaxiParty
from routers import taxi
from schemas.app_auth import CurrentAppUser
from utils.supabase_security import get_current_app_user


class TaxiApiTests(unittest.TestCase):
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
        cls.publish_message = patch(
            "routers.taxi.publish_message", new=AsyncMock()
        )
        cls.publish_updated = patch(
            "routers.taxi.publish_party_updated", new=AsyncMock()
        )
        cls.publish_message.start()
        cls.publish_updated.start()

    @classmethod
    def tearDownClass(cls):
        cls.publish_message.stop()
        cls.publish_updated.stop()
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

    def _create_party(self):
        locations = self.client.get("/api/taxi/locations").json()
        candidate = datetime.now(timezone.utc) + timedelta(hours=3)
        departure_at = candidate.replace(
            minute=(candidate.minute // 10) * 10,
            second=0,
            microsecond=0,
        )
        response = self.client.post(
            "/api/taxi/parties",
            json={
                "client_request_id": str(uuid4()),
                "departure_location_id": locations[0]["id"],
                "destination_location_id": locations[1]["id"],
                "departure_summary": "정문 택시승강장",
                "destination_summary": "3번 출구",
                "member_note": "검은 우산을 찾아주세요.",
                "departure_at": departure_at.isoformat(),
                "max_members": 2,
            },
        )
        self.assertEqual(response.status_code, 201, response.text)
        return response.json(), departure_at

    def test_create_list_and_private_detail(self):
        created, departure_at = self._create_party()
        self.assertTrue(created["is_owner"])
        self.assertRegex(created["meeting_code"], r"^[2-9A-HJ-NP-Z]{4}$")
        self.assertEqual(created["members"][0]["label"], "방장")
        self.assertEqual(created["recruitment_status"], "recruiting")
        self.assertEqual(created["chat_status"], "writable")
        self.assertIn("chat_writable_until", created)
        self.assertIn("chat_visible_until", created)
        self.assertNotIn("owner_id", created)

        target_date = departure_at.astimezone(ZoneInfo("Asia/Seoul")).date()
        listing = self.client.get(
            "/api/taxi/parties", params={"date": target_date.isoformat()}
        )
        self.assertEqual(listing.status_code, 200)
        self.assertEqual(listing.json()["items"][0]["id"], created["id"])
        self.assertEqual(listing.headers["cache-control"], "no-store")

        type(self).current_user_id = uuid4()
        outsider = self.client.get(f"/api/taxi/parties/{created['id']}")
        self.assertEqual(outsider.status_code, 200)
        self.assertIsNone(outsider.json()["member_note"])

    def test_join_is_idempotent_and_owner_cannot_leave(self):
        created, _ = self._create_party()
        owner_id = type(self).current_user_id
        member_id = uuid4()
        type(self).current_user_id = member_id

        first = self.client.post(f"/api/taxi/parties/{created['id']}/join")
        second = self.client.post(f"/api/taxi/parties/{created['id']}/join")
        self.assertEqual(first.status_code, 200)
        self.assertEqual(second.status_code, 200)
        self.assertEqual(first.json()["current_members"], 2)
        self.assertEqual(first.json()["member_note"], "검은 우산을 찾아주세요.")

        left = self.client.delete(f"/api/taxi/parties/{created['id']}/members/me")
        self.assertEqual(left.status_code, 200)

        type(self).current_user_id = owner_id
        owner_left = self.client.delete(f"/api/taxi/parties/{created['id']}/members/me")
        self.assertEqual(owner_left.status_code, 409)
        self.assertEqual(owner_left.json()["detail"]["code"], "OWNER_CANNOT_LEAVE")

    def test_departed_party_is_returned_as_recent_chat_not_active(self):
        created, _ = self._create_party()
        with self.SessionLocal() as db:
            party = db.query(TaxiParty).filter(TaxiParty.id == UUID(created["id"])).one()
            party.departure_at = datetime.now(timezone.utc) - timedelta(hours=1)
            db.commit()

        active = self.client.get("/api/taxi/my-parties", params={"scope": "active"})
        recent = self.client.get(
            "/api/taxi/my-parties", params={"scope": "recent_chats"}
        )

        self.assertEqual(active.status_code, 200)
        self.assertEqual(active.json(), [])
        self.assertEqual(recent.status_code, 200)
        self.assertEqual(recent.json()[0]["id"], created["id"])
        self.assertEqual(recent.json()[0]["recruitment_status"], "ended")
        self.assertEqual(recent.json()[0]["chat_status"], "writable")


if __name__ == "__main__":
    unittest.main()
