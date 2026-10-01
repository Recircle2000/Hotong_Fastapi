from __future__ import annotations

import asyncio
import json
import logging
import os
from functools import lru_cache
from typing import Any, Iterable
from uuid import UUID

from redis.asyncio import Redis
from sqlalchemy.orm import Session
from starlette.concurrency import run_in_threadpool

from models import TaxiMessage
from services.taxi import message_fanout, party_member_summaries
from services.taxi_push import deliver_message_push, push_enabled


logger = logging.getLogger(__name__)


# 팟 검색 목록을 보는 모든 접속자가 구독하는 공용 채널이다.
TAXI_PARTIES_CHANNEL = "taxi:parties"


def taxi_user_channel(user_id: UUID) -> str:
    return f"taxi:user:{user_id}"


@lru_cache(maxsize=1)
def get_async_redis() -> Redis:
    return Redis(
        host=os.getenv("REDIS_HOST", "redis"),
        port=int(os.getenv("REDIS_PORT", "6379")),
        password=os.getenv("REDIS_PASSWORD"),
        db=int(os.getenv("REDIS_DB", "0")),
        decode_responses=True,
    )


async def publish_user_events(events: Iterable[tuple[UUID, dict[str, Any]]]) -> bool:
    """Publish best-effort realtime events without rolling back committed work."""
    try:
        client = get_async_redis()
        async with client.pipeline(transaction=False) as pipeline:
            has_event = False
            for user_id, event in events:
                has_event = True
                pipeline.publish(
                    taxi_user_channel(user_id),
                    json.dumps(event, ensure_ascii=False, default=str),
                )
            if has_event:
                await pipeline.execute()
        return True
    except Exception:
        logger.exception("Failed to publish taxi realtime event")
        return False


async def publish_parties_changed(party_id: UUID) -> bool:
    """Tell every connected client that the search list changed.

    The payload carries only the party id; clients refetch the list with their
    own filters, so no member-only data is broadcast.
    """
    try:
        await get_async_redis().publish(
            TAXI_PARTIES_CHANNEL,
            json.dumps({"type": "parties.changed", "party_id": str(party_id)}),
        )
        return True
    except Exception:
        logger.exception("Failed to publish taxi parties change")
        return False


def build_message_events(db: Session, message: TaxiMessage) -> list[tuple[UUID, dict[str, Any]]]:
    return [
        (
            member_id,
            {
                "type": "message.created",
                "party_id": str(message.party_id),
                "message": serialized.model_dump(mode="json"),
                "party": summary.model_dump(mode="json"),
            },
        )
        for member_id, serialized, summary in message_fanout(db, message)
    ]


def build_party_updated_events(db: Session, party_id: UUID) -> list[tuple[UUID, dict[str, Any]]]:
    return [
        (
            user_id,
            {
                "type": "party.updated",
                "party_id": str(party_id),
                "party": summary.model_dump(mode="json"),
            },
        )
        for user_id, summary in party_member_summaries(db, party_id)
    ]


# DB 조회는 동기 SQLAlchemy라서 스레드풀에서 돌리고, 이벤트 루프에서는 발행만 한다.
# 이벤트 루프가 막히면 워커 하나를 쓰는 서버에서 모든 채팅 연결이 함께 멈춘다.
async def publish_message(
    db: Session,
    message: TaxiMessage,
    *,
    push: bool = True,
    push_exclude: UUID | None = None,
) -> None:
    events = await run_in_threadpool(build_message_events, db, message)
    await publish_user_events(events)
    if push:
        schedule_message_push(message.id, push_exclude)


# 완료 전에 가비지 컬렉션되지 않도록 진행 중인 발송 작업을 붙잡아 둔다.
_push_tasks: set[asyncio.Task] = set()


async def _claim_message_push(message_id: int) -> bool:
    """같은 메시지를 두 번 알리지 않는다(채팅 재전송, 여러 워커). Redis가 없으면 그냥 보낸다."""
    try:
        return bool(await get_async_redis().set(f"taxi:push:message:{message_id}", "1", nx=True, ex=3600))
    except Exception:
        return True


async def _push_message(message_id: int, exclude_user_id: UUID | None) -> None:
    try:
        if not await _claim_message_push(message_id):
            return
        await run_in_threadpool(deliver_message_push, message_id, exclude_user_id)
    except Exception:
        logger.exception("Failed to push taxi message")


def schedule_message_push(message_id: int, exclude_user_id: UUID | None = None) -> None:
    """앱을 닫은 참여자에게 푸시 알림을 보낸다. 요청을 붙잡지 않도록 응답과 별개로 돈다."""
    if not push_enabled():
        return
    task = asyncio.create_task(_push_message(message_id, exclude_user_id))
    _push_tasks.add(task)
    task.add_done_callback(_push_tasks.discard)


async def publish_party_updated(db: Session, party_id: UUID) -> None:
    events = await run_in_threadpool(build_party_updated_events, db, party_id)
    await publish_user_events(events)
    await publish_parties_changed(party_id)
