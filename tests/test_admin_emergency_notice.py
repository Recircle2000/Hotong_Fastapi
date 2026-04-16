import unittest
from datetime import datetime, timezone

from models.emergency_notice import EmergencyNotice, EmergencyNoticeCategory
from services.admin_emergency_notice import (
    create_admin_emergency_notice,
    get_emergency_notice_status,
    serialize_emergency_notice,
)


class _FakeSession:
    def __init__(self) -> None:
        self.added = None

    def add(self, obj) -> None:
        self.added = obj

    def commit(self) -> None:
        pass

    def refresh(self, obj) -> None:
        pass


class AdminEmergencyNoticeServiceTests(unittest.TestCase):
    def test_get_status_accepts_aware_notice_datetime_with_naive_now(self):
        notice = EmergencyNotice(
            category=EmergencyNoticeCategory.SHUTTLE,
            title="Shuttle Delay",
            content="Delayed",
            created_at=datetime(2026, 3, 5, 0, 0, 0, tzinfo=timezone.utc),
            end_at=datetime(2026, 3, 5, 2, 0, 0, tzinfo=timezone.utc),
        )

        status = get_emergency_notice_status(notice, now_kst=datetime(2026, 3, 5, 10, 0, 0))

        self.assertEqual(status, "active")

    def test_serialize_normalizes_aware_datetimes_to_kst_naive(self):
        notice = EmergencyNotice(
            category=EmergencyNoticeCategory.SHUTTLE,
            title="Shuttle Delay",
            content="Delayed",
            created_at=datetime(2026, 3, 5, 0, 0, 0, tzinfo=timezone.utc),
            end_at=datetime(2026, 3, 5, 2, 0, 0, tzinfo=timezone.utc),
        )

        serialized = serialize_emergency_notice(
            notice,
            now_kst=datetime(2026, 3, 5, 10, 0, 0),
        )

        self.assertEqual(serialized["created_at"], datetime(2026, 3, 5, 9, 0, 0))
        self.assertEqual(serialized["end_at"], datetime(2026, 3, 5, 11, 0, 0))
        self.assertIsNone(serialized["created_at"].tzinfo)
        self.assertIsNone(serialized["end_at"].tzinfo)
        self.assertEqual(serialized["status"], "active")

    def test_create_normalizes_aware_payload_datetimes_before_storing(self):
        session = _FakeSession()

        notice = create_admin_emergency_notice(
            session,
            category="shuttle",
            title=" Shuttle Delay ",
            content=" Delayed ",
            created_at=datetime(2026, 3, 5, 0, 0, 0, tzinfo=timezone.utc),
            end_at=datetime(2026, 3, 5, 2, 0, 0, tzinfo=timezone.utc),
        )

        self.assertIs(session.added, notice)
        self.assertEqual(notice.created_at, datetime(2026, 3, 5, 9, 0, 0))
        self.assertEqual(notice.end_at, datetime(2026, 3, 5, 11, 0, 0))
        self.assertIsNone(notice.created_at.tzinfo)
        self.assertIsNone(notice.end_at.tzinfo)
        self.assertEqual(notice.title, "Shuttle Delay")
        self.assertEqual(notice.content, "Delayed")


if __name__ == "__main__":
    unittest.main()
