from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Iterable
from uuid import UUID

from sqlalchemy.orm import Session

from models import PushDevice, TaxiMessage
from services.taxi import _load_party, active_member_ids, serialize_messages, utc_now


# 알림 미리보기는 잠금화면 한두 줄이면 충분하다.
PUSH_BODY_MAX_LENGTH = 100


@dataclass(frozen=True)
class PushNotification:
    token: str
    title: str
    body: str
    data: dict[str, str]
    # 같은 팟 알림은 하나로 묶어 최신 메시지만 보이게 한다.
    collapse_key: str


def register_device(
    db: Session,
    user_id: UUID,
    token: str,
    platform: str,
    *,
    now: datetime | None = None,
) -> None:
    current = now or utc_now()
    device = db.query(PushDevice).filter(PushDevice.token == token).first()
    if device is None:
        db.add(PushDevice(user_id=user_id, token=token, platform=platform, created_at=current, updated_at=current))
    else:
        device.user_id = user_id
        device.platform = platform
        device.updated_at = current
    db.commit()


def unregister_device(db: Session, user_id: UUID, token: str) -> None:
    # 다른 계정이 이미 가져간 토큰은 지우지 않는다.
    db.query(PushDevice).filter(
        PushDevice.token == token,
        PushDevice.user_id == user_id,
    ).delete(synchronize_session=False)
    db.commit()


def remove_tokens(db: Session, tokens: Iterable[str]) -> None:
    tokens = list(tokens)
    if not tokens:
        return
    db.query(PushDevice).filter(PushDevice.token.in_(tokens)).delete(synchronize_session=False)
    db.commit()


def _truncate(text: str) -> str:
    text = " ".join(text.split())
    if len(text) <= PUSH_BODY_MAX_LENGTH:
        return text
    return text[: PUSH_BODY_MAX_LENGTH - 1] + "…"


def build_taxi_message_notifications(
    db: Session,
    message_id: int,
    *,
    actor_id: UUID | None = None,
) -> list[PushNotification]:
    """새 채팅·시스템 메시지를 받을 팟 참여자 기기마다 알림을 만든다.

    보낸 사람과 이 일을 일으킨 사람(참여·취소한 본인)은 빼고, 남아 있는 참여자에게만 보낸다.
    """
    message = db.get(TaxiMessage, message_id)
    if message is None:
        return []
    party = _load_party(db, message.party_id)
    excluded = {user_id for user_id in (message.sender_id, actor_id) if user_id is not None}
    recipients = [user_id for user_id in active_member_ids(db, party.id) if user_id not in excluded]
    if not recipients:
        return []
    tokens = [
        token
        for (token,) in db.query(PushDevice.token).filter(PushDevice.user_id.in_(recipients)).all()
    ]
    if not tokens:
        return []

    serialized = serialize_messages(db, party, [message], None)[0]
    if serialized.sender_label:
        body = f"{serialized.sender_label}: {serialized.content}"
    else:
        body = serialized.content
    title = f"{party.departure_location.name} → {party.destination_location.name}"
    data = {
        "type": "taxi_message",
        "party_id": str(party.id),
        "message_id": str(message.id),
    }
    return [
        PushNotification(
            token=token,
            title=title,
            body=_truncate(body),
            data=data,
            collapse_key=str(party.id),
        )
        for token in tokens
    ]
