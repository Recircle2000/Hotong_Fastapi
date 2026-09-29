from __future__ import annotations

import json
import logging
import os
from functools import lru_cache
from typing import Any, Iterable
from uuid import UUID

from redis.asyncio import Redis
from sqlalchemy.orm import Session

from models import TaxiMessage
from services.taxi import active_member_ids, get_party_summary, serialize_message


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


async def publish_message(db: Session, message: TaxiMessage) -> None:
    events = []
    for user_id in active_member_ids(db, message.party_id):
        serialized = serialize_message(db, message, user_id).model_dump(mode="json")
        party = get_party_summary(db, message.party_id, user_id).model_dump(mode="json")
        events.append(
            (
                user_id,
                {
                    "type": "message.created",
                    "party_id": str(message.party_id),
                    "message": serialized,
                    "party": party,
                },
            )
        )
    await publish_user_events(events)


async def publish_party_updated(db: Session, party_id: UUID) -> None:
    await publish_user_events(
        (
            user_id,
            {
                "type": "party.updated",
                "party_id": str(party_id),
                "party": get_party_summary(db, party_id, user_id).model_dump(mode="json"),
            },
        )
        for user_id in active_member_ids(db, party_id)
    )
    await publish_parties_changed(party_id)
