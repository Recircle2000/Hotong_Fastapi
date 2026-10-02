import os
from dataclasses import dataclass
from functools import lru_cache


class SupabaseAuthConfigurationError(RuntimeError):
    pass


@dataclass(frozen=True)
class SupabaseAuthConfig:
    project_url: str
    issuer: str
    jwks_url: str
    audience: str = "authenticated"
    allowed_algorithm: str = "ES256"
    allowed_email_domain: str = "vision.hoseo.edu"
    allowed_test_emails: frozenset[str] = frozenset()
    # 앱 심사용 계정. 메일함을 열 수 없는 심사자가 고정 코드로 인증번호를 받는다.
    # 세 값이 모두 설정돼야 켜진다.
    review_emails: frozenset[str] = frozenset()
    review_code: str = ""
    service_role_key: str = ""

    @property
    def review_login_enabled(self) -> bool:
        return bool(self.review_emails and self.review_code and self.service_role_key)


@lru_cache(maxsize=1)
def get_supabase_auth_config() -> SupabaseAuthConfig:
    raw_project_url = os.getenv("SUPABASE_PROJECT_URL", "").strip().rstrip("/")
    if not raw_project_url:
        raise SupabaseAuthConfigurationError("SUPABASE_PROJECT_URL is not set.")
    if not raw_project_url.startswith("https://"):
        raise SupabaseAuthConfigurationError(
            "SUPABASE_PROJECT_URL must use HTTPS."
        )

    issuer = f"{raw_project_url}/auth/v1"
    review_emails = _email_set("APP_AUTH_REVIEW_EMAILS")
    return SupabaseAuthConfig(
        project_url=raw_project_url,
        issuer=issuer,
        jwks_url=f"{issuer}/.well-known/jwks.json",
        # 심사용 계정도 학교 도메인이 아니므로 테스트 이메일과 같이 허용한다.
        allowed_test_emails=_email_set("APP_AUTH_TEST_EMAILS") | review_emails,
        review_emails=review_emails,
        review_code=os.getenv("APP_AUTH_REVIEW_CODE", "").strip(),
        service_role_key=os.getenv("SUPABASE_SERVICE_ROLE_KEY", "").strip(),
    )


def _email_set(env_name: str) -> frozenset[str]:
    return frozenset(
        email.strip().lower()
        for email in os.getenv(env_name, "").split(",")
        if email.strip()
    )
