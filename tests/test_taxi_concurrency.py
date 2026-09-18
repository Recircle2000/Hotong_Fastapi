"""Run with TAXI_TEST_DATABASE_URL pointing to an isolated PostgreSQL database."""
import os
import unittest
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from threading import Barrier
from uuid import uuid4

os.environ.setdefault("SUPABASE_URL", "sqlite://")

from sqlalchemy import create_engine
from sqlalchemy.schema import CreateSchema, DropSchema
from sqlalchemy.orm import sessionmaker
from models import Base, TaxiLocation
from schemas.taxi import TaxiPartyCreateRequest
from services.taxi import create_party, join_party, list_my_parties, TaxiServiceError


@unittest.skipUnless(os.environ.get("TAXI_TEST_DATABASE_URL"), "isolated PostgreSQL required")
class TaxiConcurrencyTests(unittest.TestCase):
    def setUp(self):
        self.schema = "taxi_test_" + uuid4().hex
        self.root = create_engine(os.environ["TAXI_TEST_DATABASE_URL"])
        self.assertEqual(self.root.dialect.name, "postgresql")
        with self.root.begin() as conn:
            conn.execute(CreateSchema(self.schema))
        self.engine = self.root.execution_options(schema_translate_map={None: self.schema})
        Base.metadata.create_all(self.engine)
        self.sessions = sessionmaker(bind=self.engine)
        self.now = datetime(2026, 9, 18, 0, 0, tzinfo=timezone.utc)
        self.user = uuid4()
        with self.sessions() as db:
            a = TaxiLocation(name="출발", category="campus", sort_order=1)
            b = TaxiLocation(name="도착", category="station", sort_order=2)
            db.add_all([a, b])
            db.commit()
            self.a, self.b = a.id, b.id

    def tearDown(self):
        with self.root.begin() as conn:
            conn.execute(DropSchema(self.schema, cascade=True))
        self.root.dispose()

    def payload(self, hours=3):
        return TaxiPartyCreateRequest(
            client_request_id=uuid4(), departure_location_id=self.a,
            destination_location_id=self.b, departure_summary="정문",
            departure_at=self.now + timedelta(hours=hours), max_members=4,
        )

    def other_party(self, hours):
        with self.sessions() as db:
            return create_party(db, uuid4(), self.payload(hours), now=self.now).id

    def race(self, actions):
        barrier = Barrier(2)
        def run(action):
            with self.sessions() as db:
                barrier.wait(timeout=10)
                try:
                    action(db)
                    return "ok"
                except TaxiServiceError as error:
                    db.rollback()
                    return error.code
        with ThreadPoolExecutor(max_workers=2) as pool:
            jobs = [pool.submit(run, action) for action in actions]
            results = [job.result(timeout=20) for job in jobs]
        self.assertCountEqual(results, ["ok", "ACTIVE_PARTY_EXISTS"])
        with self.sessions() as db:
            self.assertEqual(len(list_my_parties(db, self.user, scope="active", now=self.now)), 1)

    def test_concurrent_creates(self):
        self.race([
            lambda db: create_party(db, self.user, self.payload(3), now=self.now),
            lambda db: create_party(db, self.user, self.payload(8), now=self.now),
        ])

    def test_concurrent_create_and_join(self):
        party = self.other_party(8)
        self.race([
            lambda db: create_party(db, self.user, self.payload(3), now=self.now),
            lambda db: join_party(db, party, self.user, now=self.now),
        ])

    def test_concurrent_joins(self):
        a, b = self.other_party(3), self.other_party(8)
        self.race([
            lambda db: join_party(db, a, self.user, now=self.now),
            lambda db: join_party(db, b, self.user, now=self.now),
        ])
