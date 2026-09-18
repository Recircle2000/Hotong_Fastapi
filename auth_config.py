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
    allowed_test_emails = frozenset(
        email.strip().lower()
        for email in os.getenv("APP_AUTH_TEST_EMAILS", "").split(",")
        if email.strip()
    )
    return SupabaseAuthConfig(
        project_url=raw_project_url,
        issuer=issuer,
        jwks_url=f"{issuer}/.well-known/jwks.json",
        allowed_test_emails=allowed_test_emails,
    )
