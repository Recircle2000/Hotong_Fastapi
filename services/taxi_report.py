from __future__ import annotations

import re
from datetime import datetime, timedelta
from uuid import UUID

from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from models import TaxiMessage, TaxiParty, TaxiPartyMember, TaxiReport
from schemas.taxi import TaxiReportCreateRequest
from services.taxi import (
    TaxiServiceError,
    _load_party,
    _membership,
    as_utc,
    serialize_messages,
    utc_now,
)


# 노쇼나 정산 문제는 며칠 뒤에 알게 되는 경우가 있어 출발 후 7일까지 받는다.
REPORT_WINDOW = timedelta(days=7)
DAILY_REPORT_LIMIT = 10
EVIDENCE_MESSAGE_LIMIT = 200
OWNER_LABEL = "방장"
_MEMBER_LABEL = re.compile(r"^참여자 (\d+)$")


def report_window_closes_at(party: TaxiParty) -> datetime:
    if party.status == "cancelled" and party.cancelled_at is not None:
        return as_utc(party.cancelled_at) + REPORT_WINDOW
    return as_utc(party.departure_at) + REPORT_WINDOW


def _resolve_target(db: Session, party: TaxiParty, label: str) -> UUID:
    """앱에 보이는 익명 라벨로 신고 대상을 찾는다. 이미 나간 참여자도 포함한다."""
    if label == OWNER_LABEL:
        return party.owner_id
    match = _MEMBER_LABEL.match(label)
    member = None
    if match is not None:
        member = (
            db.query(TaxiPartyMember)
            .filter(
                TaxiPartyMember.party_id == party.id,
                TaxiPartyMember.anonymous_number == int(match.group(1)),
            )
            .first()
        )
    if member is None:
        raise TaxiServiceError(404, "REPORT_TARGET_NOT_FOUND", "신고할 참여자를 찾을 수 없어요.")
    return member.user_id


def _build_evidence(
    db: Session,
    party: TaxiParty,
    target_id: UUID,
    target_label: str,
    reported_message: TaxiMessage | None,
) -> dict:
    """채팅은 보관 기한이 지나면 지워지므로 신고 시점의 최근 채팅을 라벨로 바꿔 저장한다."""
    messages = (
        db.query(TaxiMessage)
        .filter(TaxiMessage.party_id == party.id)
        .order_by(TaxiMessage.id.desc())
        .limit(EVIDENCE_MESSAGE_LIMIT)
        .all()
    )
    messages.reverse()
    if reported_message is not None and all(m.id != reported_message.id for m in messages):
        messages.insert(0, reported_message)
    serialized = serialize_messages(db, party, messages, None)
    return {
        "party": {
            "departure_location": party.departure_location.name,
            "destination_location": party.destination_location.name,
            "departure_summary": party.departure_summary,
            "departure_at": as_utc(party.departure_at).isoformat(),
            "status": party.status,
        },
        "target_label": target_label,
        "reported_message_id": reported_message.id if reported_message is not None else None,
        "messages": [
            {
                "id": item.id,
                "type": item.message_type,
                "label": item.sender_label,
                "content": item.content,
                "created_at": item.created_at.isoformat(),
                "is_target": message.sender_id == target_id,
            }
            for message, item in zip(messages, serialized)
        ],
    }


def create_report(
    db: Session,
    party_id: UUID,
    reporter_id: UUID,
    payload: TaxiReportCreateRequest,
    *,
    now: datetime | None = None,
) -> TaxiReport:
    current = as_utc(now or utc_now())
    party = _load_party(db, party_id)
    if _membership(db, party.id, reporter_id) is None:
        raise TaxiServiceError(403, "NOT_PARTY_MEMBER", "이 택시팟에 참여한 사람만 신고할 수 있어요.")
    if current > report_window_closes_at(party):
        raise TaxiServiceError(400, "REPORT_WINDOW_CLOSED", "출발 후 7일이 지나 신고할 수 없어요.")
    if payload.reason == "other" and not payload.detail:
        raise TaxiServiceError(400, "REPORT_DETAIL_REQUIRED", "기타 사유는 내용을 적어주세요.")

    target_id = _resolve_target(db, party, payload.target_label)
    if target_id == reporter_id:
        raise TaxiServiceError(400, "CANNOT_REPORT_SELF", "자기 자신은 신고할 수 없어요.")

    reported_message = None
    if payload.message_id is not None:
        reported_message = (
            db.query(TaxiMessage)
            .filter(TaxiMessage.id == payload.message_id, TaxiMessage.party_id == party.id)
            .first()
        )
        if (
            reported_message is None
            or reported_message.message_type != "chat"
            or reported_message.sender_id != target_id
        ):
            raise TaxiServiceError(400, "INVALID_REPORT_MESSAGE", "신고할 메시지를 찾을 수 없어요.")

    already = (
        db.query(TaxiReport.id)
        .filter(
            TaxiReport.party_id == party.id,
            TaxiReport.reporter_id == reporter_id,
            TaxiReport.target_id == target_id,
        )
        .first()
    )
    if already is not None:
        raise TaxiServiceError(409, "ALREADY_REPORTED", "이미 신고한 참여자예요.")

    recent = (
        db.query(TaxiReport.id)
        .filter(
            TaxiReport.reporter_id == reporter_id,
            TaxiReport.created_at >= current - timedelta(days=1),
        )
        .count()
    )
    if recent >= DAILY_REPORT_LIMIT:
        raise TaxiServiceError(429, "REPORT_LIMIT", "신고가 너무 많아요. 잠시 후 다시 시도해주세요.")

    report = TaxiReport(
        party_id=party.id,
        reporter_id=reporter_id,
        target_id=target_id,
        target_label=payload.target_label,
        reason=payload.reason,
        detail=payload.detail,
        message_id=reported_message.id if reported_message is not None else None,
        evidence=_build_evidence(db, party, target_id, payload.target_label, reported_message),
        created_at=current,
    )
    db.add(report)
    try:
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise TaxiServiceError(409, "ALREADY_REPORTED", "이미 신고한 참여자예요.") from exc
    db.refresh(report)
    return report
