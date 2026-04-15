import unittest
from datetime import datetime, timezone

from fastapi import HTTPException

from services.dashboard_utils import (
    get_now_kst_naive,
    parse_datetime_local,
    sanitize_redirect_path,
    to_kst_naive,
)


class DashboardUtilsTests(unittest.TestCase):
    def test_sanitize_redirect_path_allows_internal_path(self):
        self.assertEqual(sanitize_redirect_path("/admin/notices"), "/admin/notices")

    def test_sanitize_redirect_path_rejects_external_url(self):
        self.assertEqual(sanitize_redirect_path("https://evil.example"), "/admin")

    def test_sanitize_redirect_path_rejects_protocol_relative_path(self):
        self.assertEqual(sanitize_redirect_path("//evil"), "/admin")

    def test_parse_datetime_local_accepts_minute_format(self):
        parsed = parse_datetime_local("2026-03-05T09:30")
        self.assertEqual(parsed, datetime(2026, 3, 5, 9, 30, 0))

    def test_parse_datetime_local_accepts_second_format(self):
        parsed = parse_datetime_local("2026-03-05T09:30:45")
        self.assertEqual(parsed, datetime(2026, 3, 5, 9, 30, 45))

    def test_parse_datetime_local_raises_http_exception_for_invalid_value(self):
        with self.assertRaises(HTTPException) as exc:
            parse_datetime_local("2026/03/05 09:30")
        self.assertEqual(exc.exception.status_code, 400)

    def test_get_now_kst_naive_returns_naive_datetime(self):
        now = get_now_kst_naive()
        self.assertIsNone(now.tzinfo)

    def test_to_kst_naive_keeps_naive_datetime_unchanged(self):
        value = datetime(2026, 3, 5, 9, 30, 0)
        self.assertEqual(to_kst_naive(value), value)

    def test_to_kst_naive_converts_aware_datetime_to_kst_naive(self):
        utc = timezone.utc
        value = datetime(2026, 3, 5, 0, 30, 0, tzinfo=utc)
        converted = to_kst_naive(value)

        self.assertEqual(converted, datetime(2026, 3, 5, 9, 30, 0))
        self.assertIsNone(converted.tzinfo)


if __name__ == "__main__":
    unittest.main()
