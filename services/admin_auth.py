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


@dataclass
class AdminAuthError(Exception):
    message: str
    status_code: int


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
