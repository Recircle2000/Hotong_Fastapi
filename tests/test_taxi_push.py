import asyncio
import os
import unittest
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

os.environ.setdefault("SUPABASE_URL", "sqlite://")
# 로컬 .env에 실제 서비스 계정 키가 있어도 테스트에서는 FCM에 보내지 않는다.
os.environ["FIREBASE_CREDENTIALS_B64"] = ""

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from models import Base, TaxiLocation, TaxiPushToken
from schemas.taxi import TaxiPartyCreateRequest, TaxiPartyUpdateRequest
from services import taxi_push
from services.app_settings import clear_app_settings_cache
from services.taxi import (
    cancel_party,
    create_chat_message,
    create_party,
    join_party,
    leave_party,
    update_party,
)
from services.taxi_push import TaxiPush, build_push, deliver_message_push, register_token, remove_token
from utils import taxi_realtime


class TaxiPushTests(unittest.TestCase):
    def setUp(self):
        clear_app_settings_cache()
        engine = create_engine(
            "sqlite://",
            connect_args={"check_same_thread": False},
            poolclass=StaticPool,
        )
        Base.metadata.create_all(engine)
        self.Session = sessionmaker(bind=engine)
        self.db = self.Session()
        self.now = datetime(2026, 9, 13, 3, 0, tzinfo=timezone.utc)
        self.owner_id = uuid4()
        self.user_id = uuid4()
        self.other_id = uuid4()
        self.departure = TaxiLocation(name="아산캠퍼스", category="campus", sort_order=1)
        self.destination = TaxiLocation(name="천안아산역", category="station", sort_order=2)
        self.db.add_all([self.departure, self.destination])
        self.db.commit()
        self.party = create_party(
            self.db,
            self.owner_id,
            TaxiPartyCreateRequest(
                client_request_id=uuid4(),
                departure_location_id=self.departure.id,
                destination_location_id=self.destination.id,
                departure_summary="정문 택시승강장",
                departure_at=self.now + timedelta(hours=3),
                max_members=4,
            ),
            now=self.now,
        )
        join_party(self.db, self.party.id, self.user_id, now=self.now)
        for user_id, token in (
            (self.owner_id, "owner-token"),
            (self.user_id, "user-token"),
            (self.other_id, "other-token"),
        ):
            register_token(self.db, user_id, token, "android", now=self.now)

    def tearDown(self):
        self.db.close()

    def _chat(self, sender_id, content="정문 앞에 있어요"):
        return create_chat_message(self.db, self.party.id, sender_id, uuid4(), content, now=self.now)

    def test_token_is_moved_to_the_last_account_and_removed_by_owner_only(self):
        later = self.now + timedelta(days=1)
        register_token(self.db, self.other_id, "user-token", "ios", now=later)

        row = self.db.get(TaxiPushToken, "user-token")
        self.assertEqual(row.user_id, self.other_id)
        self.assertEqual(row.platform, "ios")
        self.assertEqual(row.updated_at.replace(tzinfo=timezone.utc), later)
        self.assertEqual(row.created_at.replace(tzinfo=timezone.utc), self.now)

        remove_token(self.db, self.user_id, "user-token")
        self.assertIsNotNone(self.db.get(TaxiPushToken, "user-token"))
        remove_token(self.db, self.other_id, "user-token")
        self.assertIsNone(self.db.get(TaxiPushToken, "user-token"))

    def test_chat_goes_to_other_members_with_sender_label(self):
        push = build_push(self.db, self._chat(self.user_id))

        self.assertEqual(push.tokens, ["owner-token"])
        self.assertEqual(push.title, "아산캠퍼스 → 천안아산역")
        self.assertEqual(push.body, "참여자 1: 정문 앞에 있어요")
        self.assertEqual(push.data, {"type": "taxi_message", "party_id": str(self.party.id)})

        from_owner = build_push(self.db, self._chat(self.owner_id, "곧 도착해요"))
        self.assertEqual(from_owner.tokens, ["user-token"])
        self.assertEqual(from_owner.body, "방장: 곧 도착해요")

    def test_long_chat_is_truncated(self):
        push = build_push(self.db, self._chat(self.user_id, "가" * 300))

        self.assertEqual(push.body, "참여자 1: " + "가" * 100 + "…")

    def test_every_device_of_a_member_is_notified(self):
        register_token(self.db, self.owner_id, "owner-tablet", "ios", now=self.now)

        push = build_push(self.db, self._chat(self.user_id))

        self.assertCountEqual(push.tokens, ["owner-token", "owner-tablet"])

    def test_join_skips_the_joiner_and_leave_skips_the_leaver(self):
        _, joined = join_party(self.db, self.party.id, self.other_id, now=self.now)
        push = build_push(self.db, joined, self.other_id)
        self.assertCountEqual(push.tokens, ["owner-token", "user-token"])
        self.assertEqual(push.body, "참여자 2님이 참여했습니다.")

        left = leave_party(self.db, self.party.id, self.other_id, now=self.now)
        push = build_push(self.db, left)
        self.assertCountEqual(push.tokens, ["owner-token", "user-token"])
        self.assertEqual(push.body, "참여자 2님이 나갔습니다.")

        # 나간 사람은 그 뒤 채팅 알림도 받지 않는다.
        self.assertEqual(build_push(self.db, self._chat(self.owner_id)).tokens, ["user-token"])

    def test_update_and_cancel_notify_members_but_not_the_owner(self):
        _, updated = update_party(
            self.db,
            self.party.id,
            self.owner_id,
            TaxiPartyUpdateRequest(departure_summary="후문"),
            now=self.now,
        )
        push = build_push(self.db, updated, self.owner_id)
        self.assertEqual(push.tokens, ["user-token"])
        self.assertEqual(push.body, "방장이 택시팟 안내를 수정했습니다.")

        cancelled = cancel_party(self.db, self.party.id, self.owner_id, "일정 변경", now=self.now)
        push = build_push(self.db, cancelled, self.owner_id)
        self.assertEqual(push.tokens, ["user-token"])
        self.assertEqual(push.body, "방장이 택시팟을 취소했습니다. 사유: 일정 변경")

    def test_admin_cancel_notifies_everyone(self):
        cancelled = cancel_party(self.db, self.party.id, None, None, admin_id=1, now=self.now)

        push = build_push(self.db, cancelled)

        self.assertCountEqual(push.tokens, ["owner-token", "user-token"])

    def test_no_push_without_recipient_devices(self):
        remove_token(self.db, self.owner_id, "owner-token")

        self.assertIsNone(build_push(self.db, self._chat(self.user_id)))

    def test_delivery_drops_unregistered_tokens(self):
        register_token(self.db, self.owner_id, "owner-old", "android", now=self.now)
        message = self._chat(self.user_id)
        sent: list[TaxiPush] = []

        def fake_send(push):
            sent.append(push)
            return ["owner-old"]

        with (
            patch("services.taxi_push.push_enabled", return_value=True),
            patch("services.taxi_push.send_push", side_effect=fake_send),
            patch("database.SessionLocal", self.Session),
        ):
            deliver_message_push(message.id)

        self.assertCountEqual(sent[0].tokens, ["owner-token", "owner-old"])
        self.db.expire_all()
        self.assertIsNone(self.db.get(TaxiPushToken, "owner-old"))
        self.assertIsNotNone(self.db.get(TaxiPushToken, "owner-token"))

    def test_delivery_is_skipped_without_credentials(self):
        message = self._chat(self.user_id)

        with (
            patch("services.taxi_push.send_push") as send,
            patch("utils.taxi_realtime.publish_user_events", new=AsyncMock(return_value=True)),
        ):
            deliver_message_push(message.id)
            asyncio.run(taxi_realtime.publish_message(self.db, message))

        send.assert_not_called()
        self.assertFalse(taxi_push.push_enabled())

    def test_send_reports_only_unregistered_tokens(self):
        responses = {
            "ok": (200, {"name": "projects/p/messages/1"}),
            "gone": (404, {"error": {"status": "NOT_FOUND", "details": [{"errorCode": "UNREGISTERED"}]}}),
            "bad": (400, {"error": {"status": "INVALID_ARGUMENT", "details": [{"errorCode": "INVALID_ARGUMENT"}]}}),
            "busy": (503, {"error": {"status": "UNAVAILABLE"}}),
        }
        session = MagicMock()

        def post(url, json, timeout):
            status_code, payload = responses[json["message"]["token"]]
            response = MagicMock(status_code=status_code)
            response.json.return_value = payload
            return response

        session.post.side_effect = post
        push = TaxiPush(
            tokens=list(responses),
            title="아산캠퍼스 → 천안아산역",
            body="방장: 곧 도착해요",
            data={"type": "taxi_message", "party_id": "party-1"},
        )

        with patch("services.taxi_push._fcm_client", return_value=(session, "hotong-test")):
            dead = taxi_push.send_push(push)

        self.assertEqual(dead, ["gone"])
        url, body = session.post.call_args_list[0].args[0], session.post.call_args_list[0].kwargs["json"]
        self.assertEqual(url, "https://fcm.googleapis.com/v1/projects/hotong-test/messages:send")
        self.assertEqual(body["message"]["notification"], {"title": push.title, "body": push.body})
        self.assertEqual(body["message"]["data"], push.data)
        self.assertEqual(body["message"]["android"]["notification"]["channel_id"], "taxi_party")
        self.assertEqual(body["message"]["apns"]["payload"]["aps"]["thread-id"], "party-1")


if __name__ == "__main__":
    unittest.main()
