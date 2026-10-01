from __future__ import annotations

import base64
import json
import logging
import os
from dataclasses import dataclass
from datetime import datetime
from functools import lru_cache
from uuid import UUID

from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from models import TaxiMessage, TaxiPushToken
from services.taxi import _active_member_query, _load_party, _member_label, _membership, as_utc, utc_now


logger = logging.getLogger(__name__)

FCM_SCOPE = "https://www.googleapis.com/auth/firebase.messaging"
PUSH_CHANNEL_ID = "taxi_party"
PUSH_BODY_LIMIT = 100
PUSH_TIMEOUT_SECONDS = 10


@dataclass(frozen=True)
class TaxiPush:
    tokens: list[str]
    title: str
    body: str
    data: dict[str, str]


def register_token(
    db: Session,
    user_id: UUID,
    token: str,
    platform: str,
    *,
    now: datetime | None = None,
) -> None:
    """기기 토큰을 현재 사용자에게 묶는다. 같은 기기에서 계정을 바꾸면 새 계정으로 옮긴다."""
    current = as_utc(now or utc_now())
    row = db.get(TaxiPushToken, token)
    if row is None:
        db.add(
            TaxiPushToken(
                token=token,
                user_id=user_id,
                platform=platform,
                created_at=current,
                updated_at=current,
            )
        )
        try:
            db.commit()
            return
        except IntegrityError:
            # 같은 토큰을 동시에 등록한 요청이 먼저 들어갔다.
            db.rollback()
            row = db.get(TaxiPushToken, token)
            if row is None:
                raise
    row.user_id = user_id
    row.platform = platform
    row.updated_at = current
    db.commit()


def remove_token(db: Session, user_id: UUID, token: str) -> None:
    db.query(TaxiPushToken).filter(
        TaxiPushToken.token == token,
        TaxiPushToken.user_id == user_id,
    ).delete(synchronize_session=False)
    db.commit()


def build_push(
    db: Session,
    message: TaxiMessage,
    exclude_user_id: UUID | None = None,
) -> TaxiPush | None:
    """메시지를 받을 참여자 기기와 알림 내용. 보낸 사람과 행위자 본인은 뺀다."""
    party = _load_party(db, message.party_id)
    skipped = {user_id for user_id in (message.sender_id, exclude_user_id) if user_id is not None}
    recipients = [
        member.user_id
        for member in _active_member_query(db, party.id).all()
        if member.user_id not in skipped
    ]
    if not recipients:
        return None
    tokens = [
        row.token
        for row in db.query(TaxiPushToken).filter(TaxiPushToken.user_id.in_(recipients)).all()
    ]
    if not tokens:
        return None

    body = message.content
    if message.message_type == "chat":
        if len(body) > PUSH_BODY_LIMIT:
            body = body[:PUSH_BODY_LIMIT] + "…"
        sender = _membership(db, party.id, message.sender_id) if message.sender_id else None
        if sender is not None:
            body = f"{_member_label(party, sender)}: {body}"
    return TaxiPush(
        tokens=tokens,
        # 알림만 봐도 어떤 알림인지 알 수 있게 제목 앞에 서비스 이름을 붙인다.
        title=f"택시팟 · {party.departure_location.name} → {party.destination_location.name}",
        body=body,
        data={"type": "taxi_message", "party_id": str(party.id)},
    )


@lru_cache(maxsize=1)
def _fcm_client():
    """(인증된 HTTP 세션, 프로젝트 ID). 서비스 계정 키가 없으면 None이라 발송을 건너뛴다."""
    encoded = os.getenv("FIREBASE_CREDENTIALS_B64", "").strip()
    if not encoded:
        return None
    try:
        from google.auth.transport.requests import AuthorizedSession
        from google.oauth2 import service_account

        info = json.loads(base64.b64decode(encoded))
        credentials = service_account.Credentials.from_service_account_info(info, scopes=[FCM_SCOPE])
        return AuthorizedSession(credentials), info["project_id"]
    except Exception:
        logger.exception("Failed to load Firebase credentials; taxi push is disabled")
        return None


def push_enabled() -> bool:
    return _fcm_client() is not None


def _is_unregistered(status_code: int, payload: dict) -> bool:
    if status_code == 404:
        return True
    details = payload.get("error", {}).get("details", [])
    return any(detail.get("errorCode") == "UNREGISTERED" for detail in details)


def send_push(push: TaxiPush) -> list[str]:
    """FCM으로 보내고, 더 이상 쓸 수 없는(앱 삭제 등) 토큰을 돌려준다."""
    client = _fcm_client()
    if client is None:
        return []
    session, project_id = client
    url = f"https://fcm.googleapis.com/v1/projects/{project_id}/messages:send"
    party_id = push.data.get("party_id", "")
    dead: list[str] = []
    for token in push.tokens:
        body = {
            "message": {
                "token": token,
                "notification": {"title": push.title, "body": push.body},
                "data": push.data,
                "android": {
                    "priority": "HIGH",
                    "notification": {"channel_id": PUSH_CHANNEL_ID, "tag": party_id},
                },
                "apns": {"payload": {"aps": {"sound": "default", "thread-id": party_id}}},
            }
        }
        try:
            response = session.post(url, json=body, timeout=PUSH_TIMEOUT_SECONDS)
            if response.status_code == 200:
                continue
            try:
                payload = response.json()
            except ValueError:
                payload = {}
            if _is_unregistered(response.status_code, payload):
                dead.append(token)
            else:
                logger.warning("Taxi push rejected: %s %s", response.status_code, payload.get("error", {}).get("status"))
        except Exception:
            logger.exception("Failed to send taxi push")
    return dead


def deliver_message_push(message_id: int, exclude_user_id: UUID | None = None) -> None:
    """응답 뒤에 스레드에서 돈다. 알림 실패가 이미 저장된 채팅에 영향을 주면 안 된다."""
    if not push_enabled():
        return
    from database import SessionLocal

    try:
        with SessionLocal() as db:
            message = db.get(TaxiMessage, message_id)
            if message is None:
                return
            push = build_push(db, message, exclude_user_id)
            if push is None:
                return
            dead = send_push(push)
            if dead:
                db.query(TaxiPushToken).filter(TaxiPushToken.token.in_(dead)).delete(
                    synchronize_session=False
                )
                db.commit()
    except Exception:
        logger.exception("Failed to deliver taxi push")
