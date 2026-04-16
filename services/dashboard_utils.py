from datetime import datetime, timedelta, timezone
from typing import Optional
from urllib.parse import urlsplit

from fastapi import HTTPException

KST = timezone(timedelta(hours=9))


def sanitize_redirect_path(redirect: Optional[str], default_path: str = "/admin") -> str:
    if not redirect:
        return default_path

    candidate = redirect.strip()
    if not candidate or candidate == "None":
        return default_path
    if any(ord(ch) < 32 for ch in candidate):
        return default_path

    parsed = urlsplit(candidate)
    if parsed.scheme or parsed.netloc:
        return default_path
    if not candidate.startswith("/") or candidate.startswith("//"):
        return default_path
    return candidate


def get_now_kst_naive() -> datetime:
    return datetime.now(KST).replace(tzinfo=None)


def to_kst_naive(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value
    return value.astimezone(KST).replace(tzinfo=None)


def parse_datetime_local(value: str) -> datetime:
    for fmt in ("%Y-%m-%dT%H:%M", "%Y-%m-%dT%H:%M:%S"):
        try:
            return datetime.strptime(value, fmt)
        except ValueError:
            continue
    raise HTTPException(status_code=400, detail="종료시간 형식이 올바르지 않습니다.")
