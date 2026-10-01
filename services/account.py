from __future__ import annotations

from datetime import datetime
from uuid import UUID

from sqlalchemy.orm import Session

from models import TaxiSanctionHold
from services import auth_users
from services.taxi import TaxiServiceError, as_utc, list_my_parties, utc_now
from services.taxi_sanction import active_suspension, email_hold_key


def _keep_longer_hold(hold: TaxiSanctionHold, level: str, reason: str, ends_at: datetime | None) -> None:
    # 영구 정지(ends_at 없음)가 가장 길고, 그다음은 늦게 끝나는 쪽을 남긴다.
    if hold.ends_at is None:
        return
    if ends_at is None or as_utc(ends_at) > as_utc(hold.ends_at):
        hold.level = level
        hold.reason = reason
        hold.ends_at = ends_at


def delete_account(db: Session, user_id: UUID, *, now: datetime | None = None) -> None:
    """회원 탈퇴. 진행 중인 팟이 있으면 막고, 정지 중이면 재가입 시 이어받도록 남은 정지만 남긴다.

    신고·제재 기록은 계정과 FK로 묶여 있지 않아 기존 보관 기간(1년)을 따른다.
    """
    current = as_utc(now or utc_now())
    if list_my_parties(db, user_id, scope="active", now=current):
        raise TaxiServiceError(
            409,
            "ACTIVE_PARTY_EXISTS",
            "진행 중인 택시팟을 먼저 나가거나 취소해주세요.",
        )

    suspension = active_suspension(db, user_id, current)
    if suspension is not None:
        email = auth_users.fetch_user_email(db, user_id)
        if email:
            key = email_hold_key(email)
            hold = db.get(TaxiSanctionHold, key)
            if hold is None:
                db.add(
                    TaxiSanctionHold(
                        email_hash=key,
                        level=suspension.level,
                        reason=suspension.reason,
                        ends_at=suspension.ends_at,
                        created_at=current,
                    )
                )
            else:
                _keep_longer_hold(hold, suspension.level, suspension.reason, suspension.ends_at)

    auth_users.delete_auth_user(db, user_id)
    db.commit()
