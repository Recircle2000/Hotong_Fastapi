from __future__ import annotations

import asyncio
import logging
from uuid import UUID

from starlette.concurrency import run_in_threadpool

from database import SessionLocal
from services.push import PushNotification, build_taxi_message_notifications, remove_tokens
from utils.fcm import get_fcm_client


logger = logging.getLogger(__name__)

# 응답을 늦추지 않도록 푸시는 백그라운드 태스크로 보낸다. 끝나기 전에 GC되지 않게 참조를 잡아 둔다.
_pending_tasks: set[asyncio.Task] = set()


def _build_notifications(message_id: int, actor_id: UUID | None) -> list[PushNotification]:
    with SessionLocal() as db:
        return build_taxi_message_notifications(db, message_id, actor_id=actor_id)


def _remove_stale_tokens(tokens: list[str]) -> None:
    with SessionLocal() as db:
        remove_tokens(db, tokens)


async def send_taxi_message_push(message_id: int, actor_id: UUID | None = None) -> None:
    client = get_fcm_client()
    if client is None:
        return
    try:
        notifications = await run_in_threadpool(_build_notifications, message_id, actor_id)
        stale_tokens = await client.send_all(notifications)
        if stale_tokens:
            await run_in_threadpool(_remove_stale_tokens, stale_tokens)
    except Exception:
        logger.exception("Failed to send taxi push notification")


def schedule_taxi_message_push(message_id: int, actor_id: UUID | None = None) -> None:
    """Send push notifications for a committed message without blocking the caller."""
    task = asyncio.create_task(send_taxi_message_push(message_id, actor_id))
    _pending_tasks.add(task)
    task.add_done_callback(_pending_tasks.discard)
