import time
from collections import deque
from dataclasses import dataclass
from typing import Optional

import jwt
from fastapi import Request, status
from sqlalchemy.orm import Session

from models import User
from utils.security import ALGORITHM, SECRET_KEY, verify_password


INVALID_LOGIN_MESSAGE = "로그인 실패: 아이디 또는 비밀번호가 올바르지 않습니다."
NOT_ADMIN_MESSAGE = "관리자 권한이 없습니다."
AUTH_REQUIRED_MESSAGE = "인증이 필요합니다."
LOGIN_RATE_LIMITED_MESSAGE = "로그인 시도가 너무 많습니다. 10분 뒤 다시 시도해주세요."

# 비밀번호를 무작위로 맞혀 보는 시도를 막는다. 같은 IP에서 10분 안에 5번 틀리면 잠근다.
MAX_LOGIN_FAILURES = 5
LOGIN_FAILURE_WINDOW_SECONDS = 600
_MAX_TRACKED_IPS = 10000

_login_failures: dict[str, deque[float]] = {}


@dataclass
class AdminAuthError(Exception):
    message: str
    status_code: int


def _client_ip(request: Request) -> str:
    # nginx가 X-Real-IP를 실제 접속 주소로 덮어쓴다.
    return request.headers.get("x-real-ip") or (request.client.host if request.client else "unknown")


def _recent_login_failures(ip: str, now: float) -> deque[float]:
    attempts = _login_failures.get(ip)
    if attempts is None:
        return deque()
    while attempts and now - attempts[0] > LOGIN_FAILURE_WINDOW_SECONDS:
        attempts.popleft()
    if not attempts:
        _login_failures.pop(ip, None)
    return attempts


def ensure_login_allowed(request: Request) -> None:
    if len(_recent_login_failures(_client_ip(request), time.monotonic())) >= MAX_LOGIN_FAILURES:
        raise AdminAuthError(LOGIN_RATE_LIMITED_MESSAGE, status.HTTP_429_TOO_MANY_REQUESTS)


def record_login_failure(request: Request) -> None:
    now = time.monotonic()
    if len(_login_failures) >= _MAX_TRACKED_IPS:
        # 주소를 바꿔 가며 기록을 무한히 쌓지 못하게, 기한이 지난 것부터 비운다.
        for ip in list(_login_failures):
            _recent_login_failures(ip, now)
        if len(_login_failures) >= _MAX_TRACKED_IPS:
            _login_failures.clear()
    _login_failures.setdefault(_client_ip(request), deque()).append(now)


def clear_login_failures(request: Request | None = None) -> None:
    if request is None:
        _login_failures.clear()
    else:
        _login_failures.pop(_client_ip(request), None)


def authenticate_admin_credentials(db: Session, email: str, password: str) -> User:
    user = db.query(User).filter(User.email == email).first()
    if not user or not verify_password(password, user.hashed_password):
        raise AdminAuthError(INVALID_LOGIN_MESSAGE, status.HTTP_401_UNAUTHORIZED)
    if not getattr(user, "is_admin", False):
        raise AdminAuthError(NOT_ADMIN_MESSAGE, status.HTTP_403_FORBIDDEN)
    return user


def login_admin_session(request: Request, user: User) -> None:
    request.session["user_id"] = user.id


def clear_admin_session(request: Request) -> None:
    request.session.clear()


def get_admin_user_from_session(request: Request, db: Session) -> Optional[User]:
    user_id = request.session.get("user_id")
    if not user_id:
        return None

    user = db.query(User).filter(User.id == user_id).first()
    if user and getattr(user, "is_admin", False):
        return user
    return None


def get_admin_user_from_token(token: Optional[str], db: Session) -> Optional[User]:
    if not token or not SECRET_KEY:
        return None

    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
    except jwt.PyJWTError:
        return None

    email = payload.get("sub")
    if not email:
        return None

    user = db.query(User).filter(User.email == email).first()
    if user and getattr(user, "is_admin", False):
        return user
    return None


def resolve_admin_user(request: Request, db: Session, token: Optional[str] = None) -> Optional[User]:
    return get_admin_user_from_session(request, db) or get_admin_user_from_token(token, db)
