import os
import unittest
from datetime import datetime, timedelta, timezone
from uuid import uuid4

os.environ.setdefault("SUPABASE_URL", "sqlite://")

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from models import Base, TaxiLocation, TaxiReport, TaxiSanction
from schemas.taxi import TaxiPartyCreateRequest, TaxiReportCreateRequest
from services.app_settings import clear_app_settings_cache
from services.taxi import (
    TaxiServiceError,
    create_chat_message,
    create_party,
    join_party,
    leave_party,
)
from services.taxi_report import create_report
from services.taxi_sanction import (
    acknowledge_sanction,
    active_suspension,
    issue_sanction,
    pending_notice,
    revoke_sanction,
    suggested_level,
)


class TaxiSanctionTests(unittest.TestCase):
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
        self.member_id = uuid4()
        self.departure = TaxiLocation(name="아산캠퍼스", category="campus", sort_order=1)
        self.destination = TaxiLocation(name="천안아산역", category="station", sort_order=2)
        self.db.add_all([self.departure, self.destination])
        self.db.commit()
        self.party = self._create(self.owner_id)
        join_party(self.db, self.party.id, self.member_id, now=self.now)
        self.report = create_report(
            self.db,
            self.party.id,
            self.owner_id,
            TaxiReportCreateRequest(target_label="참여자 1", reason="no_show"),
            now=self.now,
        )

    def tearDown(self):
        self.db.close()

    def _create(self, owner_id, *, now=None):
        now = now or self.now
        return create_party(
            self.db,
            owner_id,
            TaxiPartyCreateRequest(
                client_request_id=uuid4(),
                departure_location_id=self.departure.id,
                destination_location_id=self.destination.id,
                departure_summary="정문",
                departure_at=now + timedelta(hours=3),
                max_members=4,
            ),
            now=now,
        )

    def _sanction(self, level, *, now=None, resolve=True):
        return issue_sanction(
            self.db,
            self.report.id,
            level=level,
            reason="약속 장소에 나오지 않았어요.",
            admin_note=None,
            resolve_pending_reports=resolve,
            admin_id=None,
            now=now or self.now,
        )

    def assertSuspended(self, func, *args, **kwargs):
        with self.assertRaises(TaxiServiceError) as ctx:
            func(*args, **kwargs)
        self.assertEqual(ctx.exception.code, "TAXI_SUSPENDED")
        self.assertEqual(ctx.exception.status_code, 403)
        return ctx.exception

    def test_warning_does_not_restrict(self):
        self._sanction("warning")

        self.assertIsNone(active_suspension(self.db, self.member_id, self.now))
        leave_party(self.db, self.party.id, self.member_id, now=self.now)
        other = self._create(uuid4())
        join_party(self.db, other.id, self.member_id, now=self.now)

    def test_suspension_blocks_create_and_join_until_it_ends(self):
        sanction = self._sanction("suspend_3d")
        other = self._create(uuid4())

        error = self.assertSuspended(join_party, self.db, other.id, self.member_id, now=self.now)
        self.assertIn("9월 16일 12:00까지", error.message)
        self.assertSuspended(self._create, self.member_id)

        after = self.now + timedelta(days=3, minutes=5)
        self.assertIsNone(active_suspension(self.db, self.member_id, after))
        self._create(self.member_id, now=after)
        self.assertEqual(sanction.ends_at.replace(tzinfo=timezone.utc), self.now + timedelta(days=3))

    def test_suspended_member_keeps_existing_party(self):
        self._sanction("suspend_7d")

        # 이미 참여한 팟은 다시 참여를 눌러도 그대로이고, 채팅·신고·나가기가 된다.
        join_party(self.db, self.party.id, self.member_id, now=self.now)
        create_chat_message(self.db, self.party.id, self.member_id, uuid4(), "늦어요", now=self.now)
        create_report(
            self.db,
            self.party.id,
            self.member_id,
            TaxiReportCreateRequest(target_label="방장", reason="abuse", detail="욕설"),
            now=self.now,
        )
        leave_party(self.db, self.party.id, self.member_id, now=self.now)

    def test_permanent_wins_over_timed_suspension(self):
        self._sanction("suspend_7d")
        self._sanction("permanent")

        suspension = active_suspension(self.db, self.member_id, self.now + timedelta(days=30))
        self.assertEqual(suspension.level, "permanent")
        error = self.assertSuspended(self._create, self.member_id, now=self.now + timedelta(days=30))
        self.assertEqual(error.message, "택시팟 이용이 영구 제한됐어요.")

    def test_revoke_lifts_suspension_and_leaves_ladder(self):
        sanction = self._sanction("suspend_3d")
        self.assertEqual(suggested_level(self.db, self.member_id, self.now), "suspend_3d")

        revoke_sanction(self.db, sanction.id, reason="이의제기 인정", admin_id=None, now=self.now)

        self.assertIsNone(active_suspension(self.db, self.member_id, self.now))
        self.assertEqual(suggested_level(self.db, self.member_id, self.now), "warning")
        with self.assertRaises(TaxiServiceError) as ctx:
            revoke_sanction(self.db, sanction.id, reason="다시", admin_id=None, now=self.now)
        self.assertEqual(ctx.exception.code, "SANCTION_ALREADY_REVOKED")

    def test_ladder_counts_only_last_year(self):
        self.assertEqual(suggested_level(self.db, self.member_id, self.now), "warning")
        self._sanction("warning")
        self._sanction("suspend_3d")
        self.assertEqual(suggested_level(self.db, self.member_id, self.now), "suspend_7d")
        self._sanction("suspend_7d")
        self._sanction("permanent")
        self.assertEqual(suggested_level(self.db, self.member_id, self.now), "permanent")

        next_year = self.now + timedelta(days=366)
        self.assertEqual(suggested_level(self.db, self.member_id, next_year), "warning")

    def test_sanction_resolves_linked_and_pending_reports(self):
        other_reporter = uuid4()
        join_party(self.db, self.party.id, other_reporter, now=self.now)
        pending = create_report(
            self.db,
            self.party.id,
            other_reporter,
            TaxiReportCreateRequest(target_label="참여자 1", reason="abuse", detail="욕설"),
            now=self.now,
        )

        sanction = self._sanction("warning")

        for report in (self.report, pending):
            self.db.refresh(report)
            self.assertEqual(report.status, "resolved")
            self.assertEqual(report.sanction_id, sanction.id)
        self.assertEqual(sanction.user_id, self.member_id)

    def test_sanction_can_leave_other_pending_reports(self):
        other_reporter = uuid4()
        join_party(self.db, self.party.id, other_reporter, now=self.now)
        pending = create_report(
            self.db,
            self.party.id,
            other_reporter,
            TaxiReportCreateRequest(target_label="참여자 1", reason="abuse", detail="욕설"),
            now=self.now,
        )

        self._sanction("warning", resolve=False)

        self.db.refresh(pending)
        self.assertEqual(pending.status, "pending")

    def test_notice_until_acknowledged_by_owner_only(self):
        warning = self._sanction("warning")

        self.assertEqual(pending_notice(self.db, self.member_id, self.now).id, warning.id)
        with self.assertRaises(TaxiServiceError) as ctx:
            acknowledge_sanction(self.db, self.owner_id, warning.id, now=self.now)
        self.assertEqual(ctx.exception.status_code, 404)

        acknowledge_sanction(self.db, self.member_id, warning.id, now=self.now)
        self.assertIsNone(pending_notice(self.db, self.member_id, self.now))

    def test_finished_suspension_is_not_announced(self):
        self._sanction("suspend_3d")

        self.assertIsNotNone(pending_notice(self.db, self.member_id, self.now))
        self.assertIsNone(pending_notice(self.db, self.member_id, self.now + timedelta(days=4)))

    def test_invalid_level_and_missing_report(self):
        with self.assertRaises(TaxiServiceError) as ctx:
            self._sanction("ban")
        self.assertEqual(ctx.exception.code, "INVALID_SANCTION_LEVEL")
        with self.assertRaises(TaxiServiceError) as ctx:
            issue_sanction(
                self.db,
                999,
                level="warning",
                reason="x",
                admin_note=None,
                resolve_pending_reports=False,
                admin_id=None,
            )
        self.assertEqual(ctx.exception.code, "REPORT_NOT_FOUND")
        self.assertEqual(self.db.query(TaxiSanction).count(), 0)
        self.assertEqual(self.db.query(TaxiReport).filter(TaxiReport.status == "pending").count(), 1)


if __name__ == "__main__":
    unittest.main()
