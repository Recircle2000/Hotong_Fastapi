import os
import unittest
from datetime import date, datetime, timedelta, timezone
from unittest.mock import patch
from uuid import uuid4

os.environ.setdefault("SUPABASE_URL", "sqlite://")
# 로컬 .env에 실제 서비스 계정 키가 있어도 테스트에서는 FCM에 보내지 않는다.
os.environ["FIREBASE_CREDENTIALS_B64"] = ""

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from models import Base, TaxiBlock, TaxiLocation
from schemas.taxi import TaxiPartyCreateRequest
from services import taxi_block
from services.app_settings import clear_app_settings_cache
from services.taxi import (
    TaxiServiceError,
    create_chat_message,
    create_party,
    get_party_detail,
    join_party,
    leave_party,
    list_messages,
    list_my_active_party_details,
    list_parties,
    message_fanout,
    party_member_details,
)
from services.taxi_block import block_member, list_blocks, related_user_ids, unblock
from services.taxi_push import build_push, register_token


class TaxiBlockTests(unittest.TestCase):
    def setUp(self):
        clear_app_settings_cache()
        engine = create_engine(
            "sqlite://",
            connect_args={"check_same_thread": False},
            poolclass=StaticPool,
        )
        Base.metadata.create_all(engine)
        self.db = sessionmaker(bind=engine)()
        self.now = datetime(2026, 9, 13, 3, 0, tzinfo=timezone.utc)
        self.owner_id = uuid4()
        self.user_id = uuid4()
        self.other_id = uuid4()
        self.departure = TaxiLocation(name="아산캠퍼스", category="campus", sort_order=1)
        self.destination = TaxiLocation(name="천안아산역", category="station", sort_order=2)
        self.db.add_all([self.departure, self.destination])
        self.db.commit()
        self.party = self._create(self.owner_id)
        # 참여자 1 = user, 참여자 2 = other
        join_party(self.db, self.party.id, self.user_id, now=self.now)
        join_party(self.db, self.party.id, self.other_id, now=self.now)

    def tearDown(self):
        self.db.close()

    def _create(self, owner_id, hours=3):
        return create_party(
            self.db,
            owner_id,
            TaxiPartyCreateRequest(
                client_request_id=uuid4(),
                departure_location_id=self.departure.id,
                destination_location_id=self.destination.id,
                departure_summary="정문 택시승강장",
                departure_at=self.now + timedelta(hours=hours),
                max_members=4,
            ),
            now=self.now,
        )

    def _block(self, blocker_id, label):
        return block_member(self.db, self.party.id, blocker_id, label, now=self.now)

    def _search(self, user_id):
        items, _ = list_parties(
            self.db,
            user_id,
            target_date=date(2026, 9, 13),
            departure_location_id=None,
            destination_location_id=None,
            include_unavailable=True,
            cursor=None,
            limit=20,
            now=self.now,
        )
        return [item.id for item in items]

    def assertServiceError(self, code, callable_, *args, **kwargs):
        with self.assertRaises(TaxiServiceError) as raised:
            callable_(*args, **kwargs)
        self.assertEqual(raised.exception.code, code)
        return raised.exception

    def test_block_by_label_keeps_a_snapshot_and_is_idempotent(self):
        block = self._block(self.owner_id, "참여자 1")

        self.assertEqual(block.blocked_id, self.user_id)
        self.assertEqual(block.target_label, "참여자 1")
        self.assertEqual(block.departure_name, "아산캠퍼스")
        self.assertEqual(block.destination_name, "천안아산역")

        again = self._block(self.owner_id, "참여자 1")
        self.assertEqual(again.id, block.id)
        self.assertEqual(self.db.query(TaxiBlock).count(), 1)

        # 참여자도 방장을 차단할 수 있다.
        self.assertEqual(self._block(self.user_id, "방장").blocked_id, self.owner_id)

    def test_block_requires_membership_and_a_valid_target(self):
        self.assertServiceError("NOT_PARTY_MEMBER", self._block, uuid4(), "방장")
        self.assertServiceError("CANNOT_BLOCK_SELF", self._block, self.owner_id, "방장")
        self.assertServiceError("CANNOT_BLOCK_SELF", self._block, self.user_id, "참여자 1")
        self.assertServiceError("BLOCK_TARGET_NOT_FOUND", self._block, self.owner_id, "참여자 9")

    def test_member_who_left_can_still_block_and_be_blocked(self):
        leave_party(self.db, self.party.id, self.user_id, now=self.now)

        self.assertEqual(self._block(self.user_id, "방장").blocked_id, self.owner_id)
        self.assertEqual(self._block(self.other_id, "참여자 1").blocked_id, self.user_id)

    def test_block_limit(self):
        with patch.object(taxi_block, "BLOCK_LIMIT", 1):
            self._block(self.owner_id, "참여자 1")
            self.assertServiceError("BLOCK_LIMIT", self._block, self.owner_id, "참여자 2")
            # 이미 차단한 사람은 한도와 상관없이 그대로 돌려준다.
            self._block(self.owner_id, "참여자 1")

    def test_list_and_unblock_only_my_blocks(self):
        mine = self._block(self.owner_id, "참여자 1")
        theirs = self._block(self.user_id, "참여자 2")

        self.assertEqual([block.id for block in list_blocks(self.db, self.owner_id)], [mine.id])
        self.assertServiceError("BLOCK_NOT_FOUND", unblock, self.db, self.owner_id, theirs.id)
        self.assertServiceError("BLOCK_NOT_FOUND", unblock, self.db, self.owner_id, 9999)

        unblock(self.db, self.owner_id, mine.id)
        self.assertEqual(list_blocks(self.db, self.owner_id), [])
        self.assertEqual(related_user_ids(self.db, self.owner_id), set())

    def test_blocked_people_do_not_meet_again(self):
        leave_party(self.db, self.party.id, self.user_id, now=self.now)
        self.assertIn(self.party.id, self._search(self.user_id))
        block = self._block(self.owner_id, "참여자 1")

        # 차단당한 쪽: 방장의 팟이 검색에 안 보이고 다시 참여할 수도 없다.
        self.assertNotIn(self.party.id, self._search(self.user_id))
        error = self.assertServiceError(
            "PARTY_NOT_JOINABLE", join_party, self.db, self.party.id, self.user_id, now=self.now
        )
        self.assertEqual(error.message, "현재 참여할 수 없는 택시팟입니다.")

        # 차단한 쪽: 상대가 만든 팟이 검색에 안 보인다.
        leave_party(self.db, self.party.id, self.other_id, now=self.now)
        theirs = self._create(self.user_id, hours=6)
        self.assertNotIn(theirs.id, self._search(self.owner_id))
        # 관계없는 사람에게는 두 팟 모두 보인다.
        self.assertCountEqual(self._search(self.other_id), [self.party.id, theirs.id])
        # 내가 참여 중인 팟은 차단한 사람이 있어도 검색에 남는다.
        self.assertIn(self.party.id, self._search(self.owner_id))
        self.assertIn(theirs.id, self._search(self.user_id))

        unblock(self.db, self.owner_id, block.id)
        self.assertIn(self.party.id, self._search(self.user_id))
        self.assertIn(theirs.id, self._search(self.owner_id))

    def test_blocker_cannot_join_a_party_with_the_blocked_member(self):
        leave_party(self.db, self.party.id, self.other_id, now=self.now)
        self._block(self.other_id, "방장")

        self.assertNotIn(self.party.id, self._search(self.other_id))
        self.assertServiceError(
            "PARTY_NOT_JOINABLE", join_party, self.db, self.party.id, self.other_id, now=self.now
        )

    def test_my_party_stays_in_search_when_i_block_a_member(self):
        self._block(self.owner_id, "참여자 1")

        self.assertIn(self.party.id, self._search(self.owner_id))
        self.assertIn(self.party.id, self._search(self.user_id))

    def test_messages_are_flagged_only_for_the_blocker(self):
        self._block(self.owner_id, "참여자 1")
        message = create_chat_message(self.db, self.party.id, self.user_id, uuid4(), "늦어요", now=self.now)
        own = create_chat_message(self.db, self.party.id, self.owner_id, uuid4(), "네", now=self.now)

        def flags(viewer_id):
            items, _ = list_messages(self.db, self.party.id, viewer_id, before_id=None, limit=50, now=self.now)
            return {item.id: item.sender_blocked for item in items if item.message_type == "chat"}

        self.assertEqual(flags(self.owner_id), {message.id: True, own.id: False})
        self.assertEqual(flags(self.other_id), {message.id: False, own.id: False})
        self.assertEqual(flags(self.user_id), {message.id: False, own.id: False})

        fanout = {member_id: response for member_id, response, _ in message_fanout(self.db, message)}
        self.assertTrue(fanout[self.owner_id].sender_blocked)
        self.assertFalse(fanout[self.other_id].sender_blocked)
        self.assertFalse(fanout[self.user_id].sender_blocked)
        self.assertTrue(fanout[self.user_id].is_mine)

    def test_members_are_flagged_only_for_the_blocker(self):
        self._block(self.owner_id, "참여자 1")

        def blocked_labels(detail):
            return [member.label for member in detail.members if member.is_blocked]

        self.assertEqual(blocked_labels(get_party_detail(self.db, self.party.id, self.owner_id)), ["참여자 1"])
        self.assertEqual(blocked_labels(get_party_detail(self.db, self.party.id, self.user_id)), [])
        mine = list_my_active_party_details(self.db, self.owner_id, now=self.now)
        self.assertEqual(blocked_labels(mine[0]), ["참여자 1"])
        per_member = dict(party_member_details(self.db, self.party.id))
        self.assertEqual(blocked_labels(per_member[self.owner_id]), ["참여자 1"])
        self.assertEqual(blocked_labels(per_member[self.other_id]), [])

    def test_blocker_gets_no_chat_push_from_the_blocked_member(self):
        for user_id, token in (
            (self.owner_id, "owner-token"),
            (self.user_id, "user-token"),
            (self.other_id, "other-token"),
        ):
            register_token(self.db, user_id, token, "android", now=self.now)
        self._block(self.owner_id, "참여자 1")

        from_blocked = create_chat_message(self.db, self.party.id, self.user_id, uuid4(), "늦어요", now=self.now)
        self.assertEqual(build_push(self.db, from_blocked).tokens, ["other-token"])

        # 차단한 사람이 보낸 메시지는 차단당한 사람에게도 그대로 간다.
        from_blocker = create_chat_message(self.db, self.party.id, self.owner_id, uuid4(), "네", now=self.now)
        self.assertCountEqual(build_push(self.db, from_blocker).tokens, ["user-token", "other-token"])

        # 참여·나가기 같은 안내는 차단과 상관없이 간다.
        leave_message = leave_party(self.db, self.party.id, self.user_id, now=self.now)
        self.assertCountEqual(
            build_push(self.db, leave_message, self.user_id).tokens, ["owner-token", "other-token"]
        )


if __name__ == "__main__":
    unittest.main()
