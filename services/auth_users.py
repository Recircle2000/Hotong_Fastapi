from __future__ import annotations

from uuid import UUID

from sqlalchemy import text
from sqlalchemy.orm import Session


# Supabase Auth의 사용자 테이블(auth.users)은 PostgreSQL에만 있다.
# 테스트용 SQLite에서는 조회 결과가 없는 것으로 다룬다.


def _is_postgres(db: Session) -> bool:
    return db.bind is not None and db.bind.dialect.name == "postgresql"


def fetch_user_email(db: Session, user_id: UUID) -> str | None:
    if not _is_postgres(db):
        return None
    return db.execute(
        text("select email from auth.users where id = :user_id"),
        {"user_id": user_id},
    ).scalar()


def delete_auth_user(db: Session, user_id: UUID) -> None:
    """Supabase 계정을 지운다. 택시팟·참여 기록은 FK로 함께 삭제된다(메시지 발신자는 비워짐)."""
    if not _is_postgres(db):
        return
    db.execute(text("delete from auth.users where id = :user_id"), {"user_id": user_id})
