"""앱 심사용 계정 로그인.

택시팟 로그인은 이메일 인증번호(OTP)만 허용한다. 심사자는 메일함을 열 수 없으므로,
미리 정한 고정 코드를 내면 서버가 Supabase 관리자 API로 진짜 일회용 인증번호를 받아
돌려준다. 앱은 그 번호로 평소와 같은 OTP 인증을 하므로 OTP 전용 규칙은 그대로 지켜진다.
"""

import hmac
import time
from collections import defaultdict, deque

import httpx

from auth_config import SupabaseAuthConfig


# 고정 코드를 무작위로 맞혀 보는 시도를 막는다.
MAX_FAILURES = 5
FAILURE_WINDOW_SECONDS = 600

_failures: dict[str, deque[float]] = defaultdict(deque)


class ReviewLoginError(Exception):
    def __init__(self, status_code: int, code: str, message: str):
        super().__init__(message)
        self.status_code = status_code
        self.code = code
        self.message = message


def _recent_failures(email: str, now: float) -> deque[float]:
    attempts = _failures[email]
    while attempts and now - attempts[0] > FAILURE_WINDOW_SECONDS:
        attempts.popleft()
    return attempts


async def _request_email_otp(config: SupabaseAuthConfig, email: str) -> str | None:
    async with httpx.AsyncClient(timeout=10) as client:
        response = await client.post(
            f"{config.project_url}/auth/v1/admin/generate_link",
            headers={
                "apikey": config.service_role_key,
                "Authorization": f"Bearer {config.service_role_key}",
            },
            json={"type": "magiclink", "email": email},
        )
    response.raise_for_status()
    return response.json().get("email_otp")


async def issue_review_otp(config: SupabaseAuthConfig, raw_email: str, code: str) -> str:
    if not config.review_login_enabled:
        raise ReviewLoginError(404, "REVIEW_LOGIN_DISABLED", "사용할 수 없는 기능입니다.")

    email = raw_email.strip().lower()
    now = time.monotonic()
    # 등록되지 않은 주소로 기록이 무한히 쌓이지 않도록 심사용 주소만 센다.
    is_review_email = email in config.review_emails
    attempts = _recent_failures(email, now) if is_review_email else deque()
    if len(attempts) >= MAX_FAILURES:
        raise ReviewLoginError(429, "REVIEW_LOGIN_RATE_LIMITED", "잠시 후 다시 시도해주세요.")

    code_matches = hmac.compare_digest(code.strip().encode(), config.review_code.encode())
    if not is_review_email or not code_matches:
        if is_review_email:
            attempts.append(now)
        # 주소가 틀렸는지 코드가 틀렸는지 구분해 주지 않는다.
        raise ReviewLoginError(403, "INVALID_REVIEW_CODE", "인증번호가 올바르지 않습니다.")

    try:
        otp = await _request_email_otp(config, email)
    except (httpx.HTTPError, ValueError) as exc:
        raise ReviewLoginError(
            502, "REVIEW_LOGIN_UNAVAILABLE", "인증 서버를 일시적으로 사용할 수 없습니다."
        ) from exc
    if not isinstance(otp, str) or not otp:
        raise ReviewLoginError(
            502, "REVIEW_LOGIN_UNAVAILABLE", "인증 서버를 일시적으로 사용할 수 없습니다."
        )
    attempts.clear()
    return otp
