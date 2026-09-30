import os
import unittest
from datetime import datetime, timedelta, timezone
from uuid import uuid4

os.environ.setdefault("SUPABASE_URL", "sqlite://")

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from models import Base, TaxiLocation, TaxiReport
from schemas.taxi import TaxiPartyCreateRequest, TaxiReportCreateRequest
from services.app_settings import clear_app_settings_cache
from services.taxi import (
    TaxiServiceError,
    cancel_party,
    create_chat_message,
    create_party,
    join_party,
    leave_party,
)
from services.taxi_report import DAILY_REPORT_LIMIT, create_report


class TaxiReportTests(unittest.TestCase):
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
        join_party(self.db, self.party.id, self.other_id, now=self.now)

    def tearDown(self):
        self.db.close()

    def _report(self, reporter_id, label="참여자 1", *, reason="no_show", detail=None, message_id=None, now=None):
        return create_report(
            self.db,
            self.party.id,
            reporter_id,
            TaxiReportCreateRequest(
                target_label=label,
                reason=reason,
                detail=detail,
                message_id=message_id,
            ),
            now=now or self.now,
        )

    def assertServiceError(self, code, func, *args, **kwargs):
        with self.assertRaises(TaxiServiceError) as ctx:
            func(*args, **kwargs)
        self.assertEqual(ctx.exception.code, code)
        return ctx.exception

    def test_member_reports_another_member_by_anonymous_label(self):
        report = self._report(self.owner_id, "참여자 1", reason="abuse", detail="욕설")

        self.assertEqual(report.target_id, self.user_id)
        self.assertEqual(report.target_label, "참여자 1")
        self.assertEqual(report.status, "pending")
        self.assertEqual(report.detail, "욕설")

    def test_owner_label_resolves_to_party_owner(self):
        report = self._report(self.user_id, "방장")

        self.assertEqual(report.target_id, self.owner_id)

    def test_member_who_left_can_report_and_be_reported(self):
        leave_party(self.db, self.party.id, self.user_id, now=self.now)

        by_left = self._report(self.user_id, "참여자 2")
        against_left = self._report(self.owner_id, "참여자 1")

        self.assertEqual(by_left.target_id, self.other_id)
        self.assertEqual(against_left.target_id, self.user_id)

    def test_non_member_cannot_report(self):
        error = self.assertServiceError("NOT_PARTY_MEMBER", self._report, uuid4())
        self.assertEqual(error.status_code, 403)

    def test_cannot_report_self_or_unknown_label(self):
        self.assertServiceError("CANNOT_REPORT_SELF", self._report, self.user_id, "참여자 1")
        self.assertServiceError("REPORT_TARGET_NOT_FOUND", self._report, self.user_id, "참여자 9")
        self.assertServiceError("REPORT_TARGET_NOT_FOUND", self._report, self.user_id, "누군가")

    def test_same_target_is_reported_once_per_reporter(self):
        self._report(self.owner_id)

        error = self.assertServiceError("ALREADY_REPORTED", self._report, self.owner_id, reason="abuse")
        self.assertEqual(error.status_code, 409)
        # 다른 사람은 같은 대상을 따로 신고할 수 있다.
        self._report(self.other_id)

    def test_other_reason_requires_detail(self):
        self.assertServiceError("REPORT_DETAIL_REQUIRED", self._report, self.owner_id, reason="other")

        report = self._report(self.owner_id, reason="other", detail="  약속 장소 변경 안내 없음 ")
        self.assertEqual(report.detail, "약속 장소 변경 안내 없음")

    def test_report_window_closes_seven_days_after_departure(self):
        departure = self.now + timedelta(hours=3)

        self._report(self.owner_id, now=departure + timedelta(days=7))
        self.assertServiceError(
            "REPORT_WINDOW_CLOSED",
            self._report,
            self.other_id,
            now=departure + timedelta(days=7, seconds=1),
        )

    def test_report_window_starts_from_cancellation(self):
        cancel_party(self.db, self.party.id, self.owner_id, None, now=self.now)

        self.assertServiceError(
            "REPORT_WINDOW_CLOSED",
            self._report,
            self.owner_id,
            now=self.now + timedelta(days=7, minutes=1),
        )

    def test_reported_message_must_belong_to_target(self):
        target_message = create_chat_message(self.db, self.party.id, self.user_id, uuid4(), "늦을 것 같아요", now=self.now)
        other_message = create_chat_message(self.db, self.party.id, self.other_id, uuid4(), "네", now=self.now)

        self.assertServiceError(
            "INVALID_REPORT_MESSAGE",
            self._report,
            self.owner_id,
            message_id=other_message.id,
        )
        report = self._report(self.owner_id, message_id=target_message.id)
        self.assertEqual(report.message_id, target_message.id)

    def test_daily_report_limit(self):
        for _ in range(DAILY_REPORT_LIMIT):
            self.db.add(
                TaxiReport(
                    party_id=None,
                    reporter_id=self.owner_id,
                    target_id=uuid4(),
                    target_label="참여자 1",
                    reason="no_show",
                    created_at=self.now - timedelta(hours=1),
                )
            )
        self.db.commit()

        error = self.assertServiceError("REPORT_LIMIT", self._report, self.owner_id)
        self.assertEqual(error.status_code, 429)

    def test_evidence_keeps_labelled_chat_snapshot(self):
        create_chat_message(self.db, self.party.id, self.owner_id, uuid4(), "정문 앞이에요", now=self.now)
        target_message = create_chat_message(self.db, self.party.id, self.user_id, uuid4(), "안 가요", now=self.now)

        report = self._report(self.owner_id, message_id=target_message.id)
        evidence = report.evidence

        self.assertEqual(evidence["party"]["departure_location"], "아산캠퍼스")
        self.assertEqual(evidence["target_label"], "참여자 1")
        self.assertEqual(evidence["reported_message_id"], target_message.id)
        chats = [m for m in evidence["messages"] if m["type"] == "chat"]
        self.assertEqual(
            [(m["label"], m["content"], m["is_target"]) for m in chats],
            [("방장", "정문 앞이에요", False), ("참여자 1", "안 가요", True)],
        )
        # 저장된 증거에는 사용자 ID가 들어가지 않는다.
        self.assertNotIn(str(self.user_id), str(evidence))


if __name__ == "__main__":
    unittest.main()
