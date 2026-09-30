from __future__ import annotations

import hashlib
import hmac
import os
from datetime import datetime, timedelta
from uuid import UUID

from sqlalchemy import or_
from sqlalchemy.orm import Session

from models import TaxiReport, TaxiSanction, TaxiSanctionHold
from services import auth_users
from services.taxi import KST, TaxiServiceError, as_utc, utc_now


# 경고 → 3일 → 7일 → 영구 순서로 올라간다.
SANCTION_LADDER = ("warning", "suspend_3d", "suspend_7d", "permanent")
SUSPENSION_LEVELS = ("suspend_3d", "suspend_7d", "permanent")
SUSPENSION_DURATIONS = {
    "suspend_3d": timedelta(days=3),
    "suspend_7d": timedelta(days=7),
}
# 1년이 지난 제재는 다음 단계 계산에서 뺀다.
LADDER_WINDOW = timedelta(days=365)


def anonymous_user_key(user_id: UUID) -> str:
    """사용자를 알아보는 6자리 고유번호. 앱 내정보와 관리자 화면이 같은 값을 보여줘
    이의제기 때 대상을 찾을 수 있고, 원래 user_id는 알 수 없다."""
    return hashlib.sha256(str(user_id).encode()).hexdigest()[:6]


def email_hold_key(email: str) -> str:
    """탈퇴자 정지 보류에 쓰는 이메일 키. 서버 비밀키 HMAC이라 학번 대입으로 되돌릴 수 없다."""
    secret = os.getenv("SECRET_KEY")
    if not secret:
        raise RuntimeError("SECRET_KEY environment variable must be set")
    normalized = email.strip().lower().encode()
    return hmac.new(secret.encode(), normalized, hashlib.sha256).hexdigest()


def claim_sanction_hold(db: Session, user_id: UUID, now: datetime | None = None) -> TaxiSanction | None:
    """정지 중 탈퇴했던 이메일로 다시 가입했다면 남은 정지를 새 계정에 이어 붙인다."""
    # 보류가 하나도 없으면 이메일 조회 없이 끝낸다.
    if db.query(TaxiSanctionHold.email_hash).first() is None:
        return None
    email = auth_users.fetch_user_email(db, user_id)
    if not email:
        return None
    hold = db.get(TaxiSanctionHold, email_hold_key(email))
    if hold is None:
        return None
    current = as_utc(now or utc_now())
    db.delete(hold)
    if hold.ends_at is not None and as_utc(hold.ends_at) <= current:
        db.commit()
        return None
    sanction = TaxiSanction(
        user_id=user_id,
        level=hold.level,
        reason=hold.reason,
        admin_note="탈퇴 전 제재 이어받음",
        starts_at=current,
        ends_at=hold.ends_at,
        created_at=current,
    )
    db.add(sanction)
    db.commit()
    return sanction


def _active_suspension_filter(query, now: datetime):
    return query.filter(
        TaxiSanction.level.in_(SUSPENSION_LEVELS),
        TaxiSanction.revoked_at.is_(None),
        TaxiSanction.starts_at <= now,
        or_(TaxiSanction.ends_at.is_(None), TaxiSanction.ends_at > now),
    )


def active_suspension(db: Session, user_id: UUID, now: datetime | None = None) -> TaxiSanction | None:
    """지금 적용 중인 정지. 여러 건이면 영구 정지, 그다음 가장 늦게 끝나는 정지를 고른다."""
    current = as_utc(now or utc_now())
    suspensions = _active_suspension_filter(
        db.query(TaxiSanction).filter(TaxiSanction.user_id == user_id),
        current,
    ).all()
    if not suspensions:
        return None
    return max(
        suspensions,
        key=lambda sanction: (sanction.ends_at is None, as_utc(sanction.ends_at) if sanction.ends_at else current),
    )


def suggested_level(db: Session, user_id: UUID, now: datetime | None = None) -> str:
    current = as_utc(now or utc_now())
    recent = (
        db.query(TaxiSanction.id)
        .filter(
            TaxiSanction.user_id == user_id,
            TaxiSanction.revoked_at.is_(None),
            TaxiSanction.created_at >= current - LADDER_WINDOW,
        )
        .count()
    )
    return SANCTION_LADDER[min(recent, len(SANCTION_LADDER) - 1)]


def suspension_message(sanction: TaxiSanction) -> str:
    if sanction.ends_at is None:
        return "택시팟 이용이 영구 제한됐어요."
    ends = as_utc(sanction.ends_at).astimezone(KST)
    return f"{ends.month}월 {ends.day}일 {ends:%H:%M}까지 택시팟을 만들거나 참여할 수 없어요."


def ensure_not_suspended(db: Session, user_id: UUID, now: datetime | None = None) -> None:
    # 이미 참여한 팟의 조회·채팅·나가기와 신고는 막지 않고 새 생성·참여만 막는다.
    claim_sanction_hold(db, user_id, now)
    suspension = active_suspension(db, user_id, now)
    if suspension is not None:
        raise TaxiServiceError(403, "TAXI_SUSPENDED", suspension_message(suspension))


def pending_notice(db: Session, user_id: UUID, now: datetime | None = None) -> TaxiSanction | None:
    """아직 확인하지 않은 가장 최근 제재. 이미 끝난 기간 정지는 알리지 않는다."""
    current = as_utc(now or utc_now())
    return (
        db.query(TaxiSanction)
        .filter(
            TaxiSanction.user_id == user_id,
            TaxiSanction.revoked_at.is_(None),
            TaxiSanction.acknowledged_at.is_(None),
            or_(TaxiSanction.ends_at.is_(None), TaxiSanction.ends_at > current),
        )
        .order_by(TaxiSanction.id.desc())
        .first()
    )


def acknowledge_sanction(db: Session, user_id: UUID, sanction_id: int, now: datetime | None = None) -> None:
    sanction = (
        db.query(TaxiSanction)
        .filter(TaxiSanction.id == sanction_id, TaxiSanction.user_id == user_id)
        .first()
    )
    if sanction is None:
        raise TaxiServiceError(404, "SANCTION_NOT_FOUND", "제재 내역을 찾을 수 없어요.")
    if sanction.acknowledged_at is None:
        sanction.acknowledged_at = as_utc(now or utc_now())
        db.commit()


def issue_sanction(
    db: Session,
    report_id: int,
    *,
    level: str,
    reason: str,
    admin_note: str | None,
    resolve_pending_reports: bool,
    admin_id: int,
    now: datetime | None = None,
) -> TaxiSanction:
    """신고 대상에게 제재를 부과하고 근거가 된 신고를 처리 완료로 바꾼다."""
    if level not in SANCTION_LADDER:
        raise TaxiServiceError(400, "INVALID_SANCTION_LEVEL", "제재 단계가 올바르지 않습니다.")
    current = as_utc(now or utc_now())
    report = db.query(TaxiReport).filter(TaxiReport.id == report_id).first()
    if report is None:
        raise TaxiServiceError(404, "REPORT_NOT_FOUND", "신고를 찾을 수 없습니다.")
    duration = SUSPENSION_DURATIONS.get(level)
    sanction = TaxiSanction(
        user_id=report.target_id,
        level=level,
        reason=reason,
        admin_note=admin_note,
        starts_at=current,
        ends_at=current + duration if duration else None,
        created_by_admin_id=admin_id,
        created_at=current,
    )
    db.add(sanction)
    db.flush()
    reports = [report]
    if resolve_pending_reports:
        reports += (
            db.query(TaxiReport)
            .filter(
                TaxiReport.target_id == report.target_id,
                TaxiReport.status == "pending",
                TaxiReport.id != report.id,
            )
            .all()
        )
    for linked in reports:
        linked.sanction_id = sanction.id
        linked.status = "resolved"
        linked.reviewed_at = current
        linked.reviewed_by_admin_id = admin_id
    db.commit()
    db.refresh(sanction)
    return sanction


def revoke_sanction(
    db: Session,
    sanction_id: int,
    *,
    reason: str,
    admin_id: int,
    now: datetime | None = None,
) -> TaxiSanction:
    sanction = db.query(TaxiSanction).filter(TaxiSanction.id == sanction_id).first()
    if sanction is None:
        raise TaxiServiceError(404, "SANCTION_NOT_FOUND", "제재 내역을 찾을 수 없습니다.")
    if sanction.revoked_at is not None:
        raise TaxiServiceError(409, "SANCTION_ALREADY_REVOKED", "이미 철회된 제재입니다.")
    sanction.revoked_at = as_utc(now or utc_now())
    sanction.revoked_by_admin_id = admin_id
    sanction.revoke_reason = reason
    db.commit()
    db.refresh(sanction)
    return sanction
