import asyncio
import unittest
from unittest.mock import patch

from auth_config import SupabaseAuthConfig
from services import review_login
from services.review_login import ReviewLoginError, issue_review_otp


def _config(**overrides) -> SupabaseAuthConfig:
    values = {
        "project_url": "https://project.supabase.co",
        "issuer": "https://project.supabase.co/auth/v1",
        "jwks_url": "https://project.supabase.co/auth/v1/.well-known/jwks.json",
        "review_emails": frozenset({"review@example.com"}),
        "review_code": "246810",
        "service_role_key": "service-key",
    }
    values.update(overrides)
    return SupabaseAuthConfig(**values)


class ReviewLoginTest(unittest.TestCase):
    def setUp(self):
        review_login._failures.clear()
        self.requested = []

        async def fake_request(config, email):
            self.requested.append(email)
            return "135790"

        patcher = patch.object(review_login, "_request_email_otp", fake_request)
        patcher.start()
        self.addCleanup(patcher.stop)

    def _issue(self, email="review@example.com", code="246810", config=None):
        return asyncio.run(issue_review_otp(config or _config(), email, code))

    def test_returns_one_time_code_for_review_account(self):
        self.assertEqual(self._issue(" Review@Example.com "), "135790")
        self.assertEqual(self.requested, ["review@example.com"])

    def test_rejects_wrong_code_and_other_emails_the_same_way(self):
        for email, code in (
            ("review@example.com", "000000"),
            ("student@vision.hoseo.edu", "246810"),
        ):
            with self.assertRaises(ReviewLoginError) as raised:
                self._issue(email, code)
            self.assertEqual(raised.exception.status_code, 403)
            self.assertEqual(raised.exception.code, "INVALID_REVIEW_CODE")
        self.assertEqual(self.requested, [])

    def test_locks_after_repeated_wrong_codes(self):
        for _ in range(review_login.MAX_FAILURES):
            with self.assertRaises(ReviewLoginError):
                self._issue(code="000000")
        # 잠긴 동안에는 맞는 코드도 받지 않는다.
        with self.assertRaises(ReviewLoginError) as raised:
            self._issue()
        self.assertEqual(raised.exception.status_code, 429)
        self.assertEqual(self.requested, [])

    def test_disabled_unless_fully_configured(self):
        for overrides in (
            {"review_emails": frozenset()},
            {"review_code": ""},
            {"service_role_key": ""},
        ):
            with self.assertRaises(ReviewLoginError) as raised:
                self._issue(config=_config(**overrides))
            self.assertEqual(raised.exception.status_code, 404)


if __name__ == "__main__":
    unittest.main()
