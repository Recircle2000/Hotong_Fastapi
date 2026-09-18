import asyncio
import os
import unittest
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, patch
from uuid import uuid4

os.environ.setdefault("SUPABASE_URL", "sqlite://")

from sqlalchemy import create_engine
from sqlalchemy.dialects import postgresql
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from models import Base, TaxiLocation, TaxiMessage, TaxiParty, TaxiPartyMember
from schemas.taxi import TaxiPartyCreateRequest, TaxiPartyUpdateRequest
from services.taxi import (
    TaxiServiceError,
    _party_query,
    as_utc,
    cancel_party,
    create_chat_message,
    create_party,
    get_party_detail,
    join_party,
    leave_party,
    list_messages,
    list_my_parties,
    party_display_status,
    recruitment_status,
    chat_status,
    serialize_party_summary,
    update_party,
)
from utils.taxi_realtime import publish_message, publish_party_updated


class TaxiServiceTests(unittest.TestCase):
    def setUp(self):
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
        self.other_user_id = uuid4()
        self.departure = TaxiLocation(name="아산캠퍼스", category="campus", sort_order=1)
        self.destination = TaxiLocation(name="천안아산역", category="station", sort_order=2)
        self.db.add_all([self.departure, self.destination])
        self.db.commit()

    def tearDown(self):
        self.db.close()

    def _create(self, *, owner_id=None, departure_at=None, max_members=4):
        payload = TaxiPartyCreateRequest(
            client_request_id=uuid4(),
            departure_location_id=self.departure.id,
            destination_location_id=self.destination.id,
            departure_summary="정문 택시승강장",
            destination_summary="3번 출구",
            member_note="검은 우산을 찾아주세요.",
            departure_at=departure_at or self.now + timedelta(hours=3),
            max_members=max_members,
        )
        return create_party(self.db, owner_id or self.owner_id, payload, now=self.now)

    def test_locked_party_query_only_locks_the_party_table(self):
        query = _party_query(self.db, uuid4(), lock=True)
        sql = str(query.statement.compile(dialect=postgresql.dialect()))

        self.assertIn("FOR UPDATE OF taxi_parties", sql)

    def test_departure_time_is_limited_to_today_and_tomorrow_in_ten_minute_steps(self):
        tomorrow_last_slot = datetime(2026, 9, 14, 14, 50, tzinfo=timezone.utc)
        party = self._create(departure_at=tomorrow_last_slot)
        self.assertEqual(as_utc(party.departure_at), tomorrow_last_slot)

        with self.assertRaises(TaxiServiceError) as too_far:
            self._create(
                owner_id=uuid4(),
                departure_at=datetime(2026, 9, 14, 15, 0, tzinfo=timezone.utc),
            )
        self.assertEqual(too_far.exception.code, "DEPARTURE_TOO_FAR")

        with self.assertRaises(TaxiServiceError) as invalid_interval:
            self._create(
                owner_id=uuid4(),
                departure_at=self.now + timedelta(hours=3, minutes=5),
            )
        self.assertEqual(
            invalid_interval.exception.code,
            "DEPARTURE_INTERVAL_INVALID",
        )

    def test_private_note_is_only_returned_to_members(self):
        party = self._create()

        member_detail = get_party_detail(self.db, party.id, self.owner_id)
        outsider_detail = get_party_detail(self.db, party.id, self.other_user_id)

        self.assertEqual(member_detail.member_note, "검은 우산을 찾아주세요.")
        self.assertIsNone(outsider_detail.member_note)

    def test_meeting_code_collision_retries_and_codes_stay_unique(self):
        with patch("services.taxi.generate_meeting_code", return_value="A234"):
            first = self._create()
        with patch(
            "services.taxi.generate_meeting_code",
            side_effect=["A234", "B234"],
        ):
            second = self._create(owner_id=self.other_user_id)

        self.assertEqual(first.meeting_code, "A234")
        self.assertEqual(second.meeting_code, "B234")

    def test_meeting_code_generation_stops_after_ten_collisions(self):
        with patch("services.taxi.generate_meeting_code", return_value="A234"):
            self._create()
        with patch("services.taxi.generate_meeting_code", return_value="A234") as generate:
            with self.assertRaises(TaxiServiceError) as raised:
                self._create(owner_id=self.other_user_id)

        self.assertEqual(raised.exception.code, "MEETING_CODE_UNAVAILABLE")
        self.assertEqual(generate.call_count, 10)

    def test_repeated_create_request_returns_the_original_meeting_code(self):
        payload = TaxiPartyCreateRequest(
            client_request_id=uuid4(),
            departure_location_id=self.departure.id,
            destination_location_id=self.destination.id,
            departure_summary="정문 택시승강장",
            departure_at=self.now + timedelta(hours=3),
            max_members=4,
        )
        with patch("services.taxi.generate_meeting_code", return_value="C234"):
            first = create_party(self.db, self.owner_id, payload, now=self.now)
        with patch(
            "services.taxi.generate_meeting_code",
            side_effect=AssertionError("a code must not be regenerated"),
        ):
            repeated = create_party(self.db, self.owner_id, payload, now=self.now)

        self.assertEqual(repeated.id, first.id)
        self.assertEqual(repeated.meeting_code, "C234")

    def test_expired_meeting_code_is_hidden_until_cleanup_releases_it(self):
        with patch("services.taxi.generate_meeting_code", return_value="D234"):
            party = self._create()
        party.departure_at = self.now - timedelta(days=31)
        self.db.commit()

        summary = serialize_party_summary(
            self.db,
            party,
            self.owner_id,
            now=self.now,
        )

        self.assertEqual(party.meeting_code, "D234")
        self.assertIsNone(summary.meeting_code)

    def test_departure_update_keeps_the_meeting_code(self):
        with patch("services.taxi.generate_meeting_code", return_value="E234"):
            party = self._create()

        updated, _ = update_party(
            self.db,
            party.id,
            self.owner_id,
            TaxiPartyUpdateRequest(departure_at=self.now + timedelta(hours=4)),
            now=self.now,
        )

        self.assertEqual(updated.meeting_code, "E234")

    def test_join_is_idempotent_and_capacity_is_transactional(self):
        party = self._create(max_members=2)
        joined_party, first_message = join_party(
            self.db, party.id, self.user_id, now=self.now
        )
        _, duplicate_message = join_party(
            self.db, party.id, self.user_id, now=self.now
        )

        self.assertIsNotNone(first_message)
        self.assertIsNone(duplicate_message)
        self.assertEqual(
            self.db.query(TaxiPartyMember)
            .filter(TaxiPartyMember.party_id == joined_party.id, TaxiPartyMember.left_at.is_(None))
            .count(),
            2,
        )
        with self.assertRaises(TaxiServiceError) as raised:
            join_party(self.db, party.id, self.other_user_id, now=self.now)
        self.assertEqual(raised.exception.code, "PARTY_NOT_JOINABLE")

    def test_rejoin_keeps_anonymous_number(self):
        party = self._create()
        join_party(self.db, party.id, self.user_id, now=self.now)
        original = (
            self.db.query(TaxiPartyMember)
            .filter(TaxiPartyMember.party_id == party.id, TaxiPartyMember.user_id == self.user_id)
            .one()
        )
        number = original.anonymous_number

        leave_party(self.db, party.id, self.user_id, now=self.now)
        join_party(self.db, party.id, self.user_id, now=self.now)

        self.assertEqual(original.anonymous_number, number)
        self.assertIsNone(original.left_at)

    def test_overlapping_party_is_rejected(self):
        self._create(owner_id=self.user_id, departure_at=self.now + timedelta(hours=3))
        with self.assertRaises(TaxiServiceError) as raised:
            self._create(owner_id=self.user_id, departure_at=self.now + timedelta(hours=4))
        self.assertEqual(raised.exception.code, "ACTIVE_PARTY_EXISTS")

    def test_active_party_blocks_create_and_join_even_when_times_do_not_overlap(self):
        first = self._create(owner_id=self.user_id)
        other = self._create(owner_id=self.other_user_id, departure_at=self.now + timedelta(hours=8))
        with self.assertRaises(TaxiServiceError) as raised:
            self._create(owner_id=self.user_id, departure_at=self.now + timedelta(hours=10))
        self.assertEqual(raised.exception.code, "ACTIVE_PARTY_EXISTS")
        with self.assertRaises(TaxiServiceError) as raised:
            join_party(self.db, other.id, self.user_id, now=self.now)
        self.assertEqual(raised.exception.code, "ACTIVE_PARTY_EXISTS")
        cancel_party(self.db, first.id, self.user_id, None, now=self.now)
        join_party(self.db, other.id, self.user_id, now=self.now)
        with self.assertRaises(TaxiServiceError) as raised:
            self._create(owner_id=self.user_id)
        self.assertEqual(raised.exception.code, "ACTIVE_PARTY_EXISTS")

    def test_joined_party_blocks_another_join_until_leave(self):
        first = self._create()
        second = self._create(owner_id=self.other_user_id, departure_at=self.now + timedelta(hours=8))
        join_party(self.db, first.id, self.user_id, now=self.now)
        with self.assertRaises(TaxiServiceError) as raised:
            join_party(self.db, second.id, self.user_id, now=self.now)
        self.assertEqual(raised.exception.code, "ACTIVE_PARTY_EXISTS")
        leave_party(self.db, first.id, self.user_id, now=self.now)
        join_party(self.db, second.id, self.user_id, now=self.now)

    def test_active_limit_expires_exactly_at_departure(self):
        first = self._create(owner_id=self.user_id)
        first.departure_at = self.now + timedelta(microseconds=1)
        self.db.commit()
        with self.assertRaises(TaxiServiceError) as raised:
            self._create(owner_id=self.user_id)
        self.assertEqual(raised.exception.code, "ACTIVE_PARTY_EXISTS")
        first.departure_at = self.now
        self.db.commit()
        self._create(owner_id=self.user_id)

    def test_only_members_can_chat_and_history_is_ordered(self):
        party = self._create()
        with self.assertRaises(TaxiServiceError) as raised:
            create_chat_message(
                self.db,
                party.id,
                self.user_id,
                uuid4(),
                "안녕하세요",
                now=self.now,
            )
        self.assertEqual(raised.exception.code, "MEMBERSHIP_REQUIRED")

        join_party(self.db, party.id, self.user_id, now=self.now)
        message = create_chat_message(
            self.db,
            party.id,
            self.user_id,
            uuid4(),
            "안녕하세요",
            now=self.now,
        )
        items, _ = list_messages(
            self.db, party.id, self.user_id, before_id=None, limit=50, now=self.now
        )
        self.assertEqual(items[-1].id, message.id)
        self.assertEqual(items[-1].sender_label, "참여자 1")
        self.assertTrue(items[-1].is_mine)

    def test_status_changes_without_background_job(self):
        party = self._create(departure_at=self.now + timedelta(hours=1))
        self.assertEqual(party_display_status(party, 1, now=self.now), "recruiting")
        self.assertEqual(
            party_display_status(party, 1, now=self.now + timedelta(hours=1)),
            "in_progress",
        )
        self.assertEqual(
            party_display_status(party, 1, now=self.now + timedelta(hours=4)),
            "completed",
        )

    def test_recruitment_and_chat_lifecycles_are_independent(self):
        party = self._create(departure_at=self.now + timedelta(hours=1))
        self.assertEqual(recruitment_status(party, 1, now=self.now), "recruiting")
        self.assertEqual(chat_status(party, now=self.now), "writable")
        at_departure = self.now + timedelta(hours=1)
        self.assertEqual(recruitment_status(party, 1, now=at_departure), "ended")
        self.assertEqual(chat_status(party, now=at_departure), "writable")
        self.assertEqual(chat_status(party, now=at_departure + timedelta(hours=3)), "read_only")
        self.assertEqual(chat_status(party, now=at_departure + timedelta(hours=48)), "expired")

    def test_cancelled_chat_is_immediately_read_only_and_expires_after_48_hours(self):
        party = self._create()
        cancel_party(self.db, party.id, self.owner_id, None, now=self.now)
        self.assertEqual(chat_status(party, now=self.now), "read_only")
        self.assertEqual(chat_status(party, now=self.now + timedelta(hours=48)), "expired")

    def test_departed_party_moves_to_recent_chat_and_allows_new_party(self):
        old = self._create(owner_id=self.user_id)
        old.departure_at = self.now
        self.db.commit()

        self.assertEqual(list_my_parties(self.db, self.user_id, scope="active", now=self.now), [])
        recent = list_my_parties(self.db, self.user_id, scope="recent_chats", now=self.now)
        self.assertEqual([item.id for item in recent], [old.id])
        self.assertEqual(recent[0].recruitment_status, "ended")
        self._create(owner_id=self.user_id, departure_at=self.now + timedelta(hours=4))

    def test_chat_write_and_visibility_boundaries_are_enforced(self):
        party = self._create()
        departure = as_utc(party.departure_at)
        create_chat_message(
            self.db,
            party.id,
            self.owner_id,
            uuid4(),
            "마지막 연락",
            now=departure + timedelta(hours=3) - timedelta(microseconds=1),
        )
        with self.assertRaises(TaxiServiceError) as read_only:
            create_chat_message(
                self.db,
                party.id,
                self.owner_id,
                uuid4(),
                "늦은 연락",
                now=departure + timedelta(hours=3),
            )
        self.assertEqual(read_only.exception.code, "CHAT_READ_ONLY")
        list_messages(
            self.db,
            party.id,
            self.owner_id,
            before_id=None,
            limit=50,
            now=departure + timedelta(hours=48) - timedelta(microseconds=1),
        )
        with self.assertRaises(TaxiServiceError) as expired:
            list_messages(
                self.db,
                party.id,
                self.owner_id,
                before_id=None,
                limit=50,
                now=departure + timedelta(hours=48),
            )
        self.assertEqual(expired.exception.code, "CHAT_EXPIRED")

    def test_realtime_events_include_party_summary_for_lightweight_sync(self):
        party = self._create()
        message = create_chat_message(
            self.db,
            party.id,
            self.owner_id,
            uuid4(),
            "곧 도착해요",
            now=self.now,
        )

        with patch(
            "utils.taxi_realtime.publish_user_events",
            new=AsyncMock(return_value=True),
        ) as publish:
            asyncio.run(publish_message(self.db, message))
            message_events = list(publish.await_args.args[0])
            asyncio.run(publish_party_updated(self.db, party.id))
            party_events = list(publish.await_args.args[0])

        self.assertEqual(message_events[0][1]["party"]["id"], str(party.id))
        self.assertIn("unread_count", message_events[0][1]["party"])
        self.assertEqual(party_events[0][1]["party"]["id"], str(party.id))

    def test_core_fields_lock_after_another_member_joins(self):
        party = self._create()
        join_party(self.db, party.id, self.user_id, now=self.now)

        with self.assertRaises(TaxiServiceError) as raised:
            update_party(
                self.db,
                party.id,
                self.owner_id,
                TaxiPartyUpdateRequest(max_members=3),
                now=self.now,
            )
        self.assertEqual(raised.exception.code, "PARTY_CORE_FIELDS_LOCKED")

        updated, message = update_party(
            self.db,
            party.id,
            self.owner_id,
            TaxiPartyUpdateRequest(member_note="새로운 안내"),
            now=self.now,
        )
        self.assertEqual(updated.member_note, "새로운 안내")
        self.assertIsNotNone(message)

    def test_repeated_cancel_does_not_create_duplicate_system_message(self):
        party = self._create()
        first = cancel_party(
            self.db, party.id, self.owner_id, "일정 변경", now=self.now
        )
        before = (
            self.db.query(TaxiMessage)
            .filter(TaxiMessage.party_id == party.id)
            .count()
        )
        second = cancel_party(
            self.db, party.id, self.owner_id, "일정 변경", now=self.now
        )
        after = (
            self.db.query(TaxiMessage)
            .filter(TaxiMessage.party_id == party.id)
            .count()
        )

        self.assertIsNotNone(first)
        self.assertIsNone(second)
        self.assertEqual(before, after)


if __name__ == "__main__":
    unittest.main()
