import asyncio
import json
import os
import unittest
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

os.environ.setdefault("SUPABASE_URL", "sqlite://")

from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from database import get_db
from models import Base, PushDevice, TaxiLocation
from routers import push
from schemas.app_auth import CurrentAppUser
from schemas.taxi import TaxiPartyCreateRequest
from services.push import (
    PushNotification,
    build_taxi_message_notifications,
    register_device,
    remove_tokens,
    unregister_device,
)
from services.taxi import create_chat_message, create_party, join_party, leave_party
from utils import taxi_push
from utils.fcm import build_message, is_stale_token_response


class PushServiceTests(unittest.TestCase):
    def setUp(self):
        engine = create_engine(
            "sqlite://",
            connect_args={"check_same_thread": False},
            poolclass=StaticPool,
        )
        Base.metadata.create_all(engine)
        self.SessionLocal = sessionmaker(bind=engine)
        self.db = self.SessionLocal()
        self.now = datetime.now(timezone.utc).replace(second=0, microsecond=0)
        self.owner_id = uuid4()
        self.user_id = uuid4()
        self.departure = TaxiLocation(name="아산캠퍼스", category="campus", sort_order=1)
        self.destination = TaxiLocation(name="천안아산역", category="station", sort_order=2)
        self.db.add_all([self.departure, self.destination])
        self.db.commit()

    def tearDown(self):
        self.db.close()

    def _create_party(self):
        minutes = 60 - self.now.minute % 5
        payload = TaxiPartyCreateRequest(
            client_request_id=uuid4(),
            departure_location_id=self.departure.id,
            destination_location_id=self.destination.id,
            departure_summary="정문 택시승강장",
            departure_at=self.now + timedelta(minutes=minutes),
            max_members=4,
        )
        return create_party(self.db, self.owner_id, payload, now=self.now)

    def test_register_moves_token_to_latest_user(self):
        register_device(self.db, self.owner_id, "token-1", "android")
        register_device(self.db, self.user_id, "token-1", "ios")

        devices = self.db.query(PushDevice).all()
        self.assertEqual(len(devices), 1)
        self.assertEqual(devices[0].user_id, self.user_id)
        self.assertEqual(devices[0].platform, "ios")

    def test_unregister_only_removes_own_token(self):
        register_device(self.db, self.owner_id, "token-1", "android")

        unregister_device(self.db, self.user_id, "token-1")
        self.assertEqual(self.db.query(PushDevice).count(), 1)

        unregister_device(self.db, self.owner_id, "token-1")
        self.assertEqual(self.db.query(PushDevice).count(), 0)

    def test_chat_message_notifies_other_members_only(self):
        party = self._create_party()
        join_party(self.db, party.id, self.user_id, now=self.now)
        register_device(self.db, self.owner_id, "owner-token", "android")
        register_device(self.db, self.user_id, "member-token", "ios")

        message = create_chat_message(self.db, party.id, self.user_id, uuid4(), "곧 도착해요")
        notifications = build_taxi_message_notifications(self.db, message.id)

        self.assertEqual([item.token for item in notifications], ["owner-token"])
        self.assertEqual(notifications[0].title, "아산캠퍼스 → 천안아산역")
        self.assertEqual(notifications[0].body, "참여자 1: 곧 도착해요")
        self.assertEqual(notifications[0].data["party_id"], str(party.id))
        self.assertEqual(notifications[0].collapse_key, str(party.id))

    def test_member_change_skips_the_actor_and_departed_member(self):
        party = self._create_party()
        register_device(self.db, self.owner_id, "owner-token", "android")
        register_device(self.db, self.user_id, "member-token", "ios")

        _, joined = join_party(self.db, party.id, self.user_id, now=self.now)
        on_join = build_taxi_message_notifications(self.db, joined.id, actor_id=self.user_id)
        self.assertEqual([item.token for item in on_join], ["owner-token"])
        self.assertEqual(on_join[0].body, "참여자 1님이 참여했습니다.")

        left = leave_party(self.db, party.id, self.user_id, now=self.now)
        on_leave = build_taxi_message_notifications(self.db, left.id, actor_id=self.user_id)
        self.assertEqual([item.token for item in on_leave], ["owner-token"])

    def test_long_message_is_truncated(self):
        party = self._create_party()
        join_party(self.db, party.id, self.user_id, now=self.now)
        register_device(self.db, self.owner_id, "owner-token", "android")

        message = create_chat_message(self.db, party.id, self.user_id, uuid4(), "가" * 300)
        body = build_taxi_message_notifications(self.db, message.id)[0].body

        self.assertEqual(len(body), 100)
        self.assertTrue(body.endswith("…"))

    def test_remove_tokens(self):
        register_device(self.db, self.owner_id, "a", "android")
        register_device(self.db, self.owner_id, "b", "android")

        remove_tokens(self.db, ["a"])

        self.assertEqual([d.token for d in self.db.query(PushDevice).all()], ["b"])

    def test_send_removes_stale_tokens(self):
        party = self._create_party()
        join_party(self.db, party.id, self.user_id, now=self.now)
        register_device(self.db, self.owner_id, "stale", "android")
        message = create_chat_message(self.db, party.id, self.user_id, uuid4(), "안녕하세요")

        client = MagicMock()
        client.send_all = AsyncMock(return_value=["stale"])
        with patch.object(taxi_push, "SessionLocal", self.SessionLocal), patch.object(
            taxi_push, "get_fcm_client", return_value=client
        ):
            asyncio.run(taxi_push.send_taxi_message_push(message.id))

        sent = client.send_all.await_args.args[0]
        self.assertEqual([item.token for item in sent], ["stale"])
        self.db.expire_all()
        self.assertEqual(self.db.query(PushDevice).count(), 0)

    def test_send_is_skipped_without_fcm_configuration(self):
        with patch.object(taxi_push, "get_fcm_client", return_value=None), patch.object(
            taxi_push, "_build_notifications"
        ) as build:
            asyncio.run(taxi_push.send_taxi_message_push(1))
        build.assert_not_called()


class FcmPayloadTests(unittest.TestCase):
    def test_message_groups_by_party(self):
        message = build_message(
            PushNotification(
                token="t",
                title="제목",
                body="본문",
                data={"party_id": "p"},
                collapse_key="p",
            )
        )
        self.assertEqual(message["android"]["notification"]["tag"], "p")
        self.assertEqual(message["apns"]["headers"]["apns-collapse-id"], "p")
        self.assertEqual(message["data"], {"party_id": "p"})

    def test_stale_token_detection(self):
        unregistered = json.dumps(
            {
                "error": {
                    "code": 404,
                    "details": [
                        {
                            "@type": "type.googleapis.com/google.firebase.fcm.v1.FcmError",
                            "errorCode": "UNREGISTERED",
                        }
                    ],
                }
            }
        )
        self.assertTrue(is_stale_token_response(404, unregistered))
        self.assertTrue(
            is_stale_token_response(
                403, json.dumps({"error": {"details": [{"errorCode": "SENDER_ID_MISMATCH"}]}})
            )
        )
        self.assertFalse(is_stale_token_response(500, "server error"))
        self.assertFalse(
            is_stale_token_response(400, json.dumps({"error": {"details": [{"errorCode": "INVALID_ARGUMENT"}]}}))
        )


class PushApiTests(unittest.TestCase):
    def setUp(self):
        engine = create_engine(
            "sqlite://",
            connect_args={"check_same_thread": False},
            poolclass=StaticPool,
        )
        Base.metadata.create_all(engine)
        self.SessionLocal = sessionmaker(bind=engine)
        self.user_id = uuid4()
        app = FastAPI()
        app.include_router(push.router)

        def override_get_db():
            with self.SessionLocal() as db:
                yield db

        app.dependency_overrides[get_db] = override_get_db
        app.dependency_overrides[push.get_current_app_user] = lambda: CurrentAppUser(user_id=self.user_id)
        self.client = TestClient(app)

    def test_register_and_unregister(self):
        response = self.client.put("/api/push/devices", json={"token": "abc", "platform": "android"})
        self.assertEqual(response.status_code, 204)
        with self.SessionLocal() as db:
            self.assertEqual(db.query(PushDevice).one().user_id, self.user_id)

        response = self.client.request("DELETE", "/api/push/devices", json={"token": "abc"})
        self.assertEqual(response.status_code, 204)
        with self.SessionLocal() as db:
            self.assertEqual(db.query(PushDevice).count(), 0)

    def test_rejects_unknown_platform(self):
        response = self.client.put("/api/push/devices", json={"token": "abc", "platform": "web"})
        self.assertEqual(response.status_code, 422)


if __name__ == "__main__":
    unittest.main()
