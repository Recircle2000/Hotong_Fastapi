import os
import unittest
from datetime import datetime, timedelta, timezone
from unittest.mock import patch
from uuid import uuid4

os.environ.setdefault("SUPABASE_URL", "sqlite://")
os.environ.setdefault("SECRET_KEY", "test-secret")

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from models import Base, TaxiLocation, TaxiSanction, TaxiSanctionHold
from schemas.taxi import TaxiPartyCreateRequest
from services.account import delete_account
from services.app_settings import clear_app_settings_cache
from services.taxi import TaxiServiceError, create_party, join_party
from services.taxi_sanction import (
    active_suspension,
    claim_sanction_hold,
    email_hold_key,
    ensure_not_suspended,
)


class AccountDeletionTests(unittest.TestCase):
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
        self.user_id = uuid4()
        self.emails = {self.user_id: "20261234@vision.hoseo.edu"}
        self.deleted = []
        self.departure = TaxiLocation(name="아산캠퍼스", category="campus", sort_order=1)
        self.destination = TaxiLocation(name="천안아산역", category="station", sort_order=2)
        self.db.add_all([self.departure, self.destination])
        self.db.commit()
        # auth.users는 PostgreSQL에만 있어 조회·삭제를 흉내낸다.
        patches = [
            patch("services.auth_users.fetch_user_email", side_effect=lambda db, uid: self.emails.get(uid)),
            patch("services.auth_users.delete_auth_user", side_effect=lambda db, uid: self.deleted.append(uid)),
        ]
        for item in patches:
            item.start()
            self.addCleanup(item.stop)

    def tearDown(self):
        self.db.close()

    def _party(self, owner_id, *, now=None):
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

    def _suspend(self, level, *, days=None, user_id=None):
        sanction = TaxiSanction(
            user_id=user_id or self.user_id,
            level=level,
            reason="약속 장소에 나오지 않았어요.",
            starts_at=self.now,
            ends_at=self.now + timedelta(days=days) if days else None,
            created_at=self.now,
        )
        self.db.add(sanction)
        self.db.commit()
        return sanction

    def test_active_party_blocks_deletion(self):
        party = self._party(uuid4())
        join_party(self.db, party.id, self.user_id, now=self.now)

        with self.assertRaises(TaxiServiceError) as ctx:
            delete_account(self.db, self.user_id, now=self.now)

        self.assertEqual(ctx.exception.status_code, 409)
        self.assertEqual(ctx.exception.code, "ACTIVE_PARTY_EXISTS")
        self.assertEqual(self.deleted, [])

    def test_finished_party_does_not_block_deletion(self):
        party = self._party(uuid4())
        join_party(self.db, party.id, self.user_id, now=self.now)

        delete_account(self.db, self.user_id, now=self.now + timedelta(hours=4))

        self.assertEqual(self.deleted, [self.user_id])
        self.assertEqual(self.db.query(TaxiSanctionHold).count(), 0)

    def test_warning_or_finished_suspension_leaves_no_hold(self):
        self._suspend("warning")
        self._suspend("suspend_3d", days=3)

        delete_account(self.db, self.user_id, now=self.now + timedelta(days=4))

        self.assertEqual(self.db.query(TaxiSanctionHold).count(), 0)

    def test_suspension_is_carried_to_new_account_with_same_email(self):
        self._suspend("suspend_7d", days=7)
        delete_account(self.db, self.user_id, now=self.now + timedelta(days=1))

        hold = self.db.query(TaxiSanctionHold).one()
        self.assertEqual(hold.email_hash, email_hold_key("20261234@vision.hoseo.edu"))
        self.assertNotIn("20261234", hold.email_hash)

        new_id, other_id = uuid4(), uuid4()
        self.emails[new_id] = " 20261234@Vision.Hoseo.edu "
        self.emails[other_id] = "20269999@vision.hoseo.edu"
        later = self.now + timedelta(days=2)

        ensure_not_suspended(self.db, other_id, later)
        with self.assertRaises(TaxiServiceError) as ctx:
            ensure_not_suspended(self.db, new_id, later)
        self.assertEqual(ctx.exception.code, "TAXI_SUSPENDED")

        carried = active_suspension(self.db, new_id, later)
        self.assertEqual(carried.level, "suspend_7d")
        self.assertEqual(carried.ends_at.replace(tzinfo=timezone.utc), self.now + timedelta(days=7))
        self.assertIsNone(carried.acknowledged_at)
        self.assertEqual(self.db.query(TaxiSanctionHold).count(), 0)

    def test_permanent_hold_has_no_end_and_wins(self):
        self._suspend("suspend_3d", days=3)
        self._suspend("permanent")

        delete_account(self.db, self.user_id, now=self.now)

        hold = self.db.query(TaxiSanctionHold).one()
        self.assertEqual(hold.level, "permanent")
        self.assertIsNone(hold.ends_at)

    def test_expired_hold_is_dropped_on_claim(self):
        self._suspend("suspend_3d", days=3)
        delete_account(self.db, self.user_id, now=self.now)
        new_id = uuid4()
        self.emails[new_id] = "20261234@vision.hoseo.edu"

        self.assertIsNone(claim_sanction_hold(self.db, new_id, self.now + timedelta(days=4)))
        self.assertEqual(self.db.query(TaxiSanctionHold).count(), 0)
        self.assertIsNone(active_suspension(self.db, new_id, self.now + timedelta(days=4)))


if __name__ == "__main__":
    unittest.main()
