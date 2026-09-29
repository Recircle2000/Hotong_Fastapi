from __future__ import annotations

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
async def publish_message(db: Session, message: TaxiMessage) -> None:
    events = await run_in_threadpool(build_message_events, db, message)
    await publish_user_events(events)


async def publish_party_updated(db: Session, party_id: UUID) -> None:
    events = await run_in_threadpool(build_party_updated_events, db, party_id)
    await publish_user_events(events)
    await publish_parties_changed(party_id)
