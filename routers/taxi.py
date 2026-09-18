from __future__ import annotations

import asyncio
import contextlib
import json
import time
from datetime import date
from uuid import UUID

import jwt
from fastapi import APIRouter, Depends, HTTPException, Query, Response, WebSocket, WebSocketDisconnect, status
from pydantic import ValidationError
from redis.exceptions import RedisError
from sqlalchemy.orm import Session

from auth_config import get_supabase_auth_config
from database import SessionLocal, get_db
from schemas.app_auth import CurrentAppUser
from schemas.taxi import (
    TaxiActionResponse,
    TaxiLocationResponse,
    TaxiMessageListResponse,
    TaxiMessageSendEvent,
    TaxiPartyCancelRequest,
    TaxiPartyCreateRequest,
    TaxiPartyDetailResponse,
    TaxiPartyListResponse,
    TaxiPartySummaryResponse,
    TaxiPartyUpdateRequest,
    TaxiReadRequest,
    TaxiReadResponse,
    TaxiRecruitmentRequest,
)
from services.taxi import (
    TaxiServiceError,
    active_member_ids,
    cancel_party,
    create_chat_message,
    create_party,
    get_party_detail,
    get_party_summary,
    join_party,
    leave_party,
    list_active_locations,
    list_messages,
    list_my_parties,
    list_parties,
    mark_messages_read,
    serialize_location,
    serialize_message,
    serialize_party_detail,
    set_recruitment,
    update_party,
)
from utils.supabase_security import get_current_app_user, get_jwk_resolver, verify_supabase_access_token
from utils.taxi_realtime import (
    get_async_redis,
    publish_message,
    publish_party_updated,
    publish_user_events,
    taxi_user_channel,
)


router = APIRouter(prefix="/api/taxi", tags=["Taxi"])
websocket_router = APIRouter(tags=["Taxi"])


def _raise_service_error(exc: TaxiServiceError) -> None:
    raise HTTPException(
        status_code=exc.status_code,
        detail={"code": exc.code, "message": exc.message},
    ) from exc


def _no_store(response: Response) -> None:
    response.headers["Cache-Control"] = "no-store"


@router.get("/locations", response_model=list[TaxiLocationResponse])
def get_taxi_locations(
    response: Response,
    _: CurrentAppUser = Depends(get_current_app_user),
    db: Session = Depends(get_db),
):
    _no_store(response)
    return [serialize_location(location) for location in list_active_locations(db)]


@router.get("/parties", response_model=TaxiPartyListResponse)
def get_taxi_parties(
    response: Response,
    target_date: date = Query(alias="date"),
    departure_location_id: int | None = None,
    destination_location_id: int | None = None,
    include_unavailable: bool = False,
    cursor: str | None = None,
    limit: int = Query(default=20, ge=1, le=50),
    current_user: CurrentAppUser = Depends(get_current_app_user),
    db: Session = Depends(get_db),
):
    _no_store(response)
    try:
        items, next_cursor = list_parties(
            db,
            current_user.user_id,
            target_date=target_date,
            departure_location_id=departure_location_id,
            destination_location_id=destination_location_id,
            include_unavailable=include_unavailable,
            cursor=cursor,
            limit=limit,
        )
        return TaxiPartyListResponse(items=items, next_cursor=next_cursor)
    except TaxiServiceError as exc:
        _raise_service_error(exc)


@router.get("/my-parties", response_model=list[TaxiPartySummaryResponse])
def get_my_taxi_parties(
    response: Response,
    scope: str = Query(default="active", pattern="^(active|recent_chats|history)$"),
    current_user: CurrentAppUser = Depends(get_current_app_user),
    db: Session = Depends(get_db),
):
    _no_store(response)
    return list_my_parties(db, current_user.user_id, scope=scope)


@router.post("/parties", response_model=TaxiPartyDetailResponse, status_code=status.HTTP_201_CREATED)
async def create_taxi_party(
    payload: TaxiPartyCreateRequest,
    response: Response,
    current_user: CurrentAppUser = Depends(get_current_app_user),
    db: Session = Depends(get_db),
):
    _no_store(response)
    try:
        party = create_party(db, current_user.user_id, payload)
        await publish_party_updated(db, party.id)
        return serialize_party_detail(db, party, current_user.user_id)
    except TaxiServiceError as exc:
        _raise_service_error(exc)


@router.get("/parties/{party_id}", response_model=TaxiPartyDetailResponse)
def get_taxi_party(
    party_id: UUID,
    response: Response,
    current_user: CurrentAppUser = Depends(get_current_app_user),
    db: Session = Depends(get_db),
):
    _no_store(response)
    try:
        return get_party_detail(db, party_id, current_user.user_id)
    except TaxiServiceError as exc:
        _raise_service_error(exc)


@router.patch("/parties/{party_id}", response_model=TaxiPartyDetailResponse)
async def patch_taxi_party(
    party_id: UUID,
    payload: TaxiPartyUpdateRequest,
    response: Response,
    current_user: CurrentAppUser = Depends(get_current_app_user),
    db: Session = Depends(get_db),
):
    _no_store(response)
    try:
        party, message = update_party(db, party_id, current_user.user_id, payload)
        if message is not None:
            await publish_message(db, message)
        await publish_party_updated(db, party.id)
        return serialize_party_detail(db, party, current_user.user_id)
    except TaxiServiceError as exc:
        _raise_service_error(exc)


@router.post("/parties/{party_id}/join", response_model=TaxiPartyDetailResponse)
async def join_taxi_party(
    party_id: UUID,
    response: Response,
    current_user: CurrentAppUser = Depends(get_current_app_user),
    db: Session = Depends(get_db),
):
    _no_store(response)
    try:
        party, message = join_party(db, party_id, current_user.user_id)
        if message is not None:
            await publish_message(db, message)
        await publish_party_updated(db, party.id)
        return serialize_party_detail(db, party, current_user.user_id)
    except TaxiServiceError as exc:
        _raise_service_error(exc)


@router.delete("/parties/{party_id}/members/me", response_model=TaxiActionResponse)
async def leave_taxi_party(
    party_id: UUID,
    response: Response,
    current_user: CurrentAppUser = Depends(get_current_app_user),
    db: Session = Depends(get_db),
):
    _no_store(response)
    try:
        message = leave_party(db, party_id, current_user.user_id)
        await publish_message(db, message)
        await publish_party_updated(db, party_id)
        return TaxiActionResponse()
    except TaxiServiceError as exc:
        _raise_service_error(exc)


@router.post("/parties/{party_id}/cancel", response_model=TaxiActionResponse)
async def cancel_taxi_party(
    party_id: UUID,
    payload: TaxiPartyCancelRequest,
    response: Response,
    current_user: CurrentAppUser = Depends(get_current_app_user),
    db: Session = Depends(get_db),
):
    _no_store(response)
    try:
        message = cancel_party(db, party_id, current_user.user_id, payload.reason)
        if message is not None:
            await publish_message(db, message)
        await publish_party_updated(db, party_id)
        return TaxiActionResponse()
    except TaxiServiceError as exc:
        _raise_service_error(exc)


@router.put("/parties/{party_id}/recruitment", response_model=TaxiActionResponse)
async def update_taxi_recruitment(
    party_id: UUID,
    payload: TaxiRecruitmentRequest,
    response: Response,
    current_user: CurrentAppUser = Depends(get_current_app_user),
    db: Session = Depends(get_db),
):
    _no_store(response)
    try:
        message = set_recruitment(db, party_id, current_user.user_id, payload.is_open)
        if message is not None:
            await publish_message(db, message)
        await publish_party_updated(db, party_id)
        return TaxiActionResponse()
    except TaxiServiceError as exc:
        _raise_service_error(exc)


@router.get("/parties/{party_id}/messages", response_model=TaxiMessageListResponse)
def get_taxi_messages(
    party_id: UUID,
    response: Response,
    before_id: int | None = None,
    limit: int = Query(default=50, ge=1, le=100),
    current_user: CurrentAppUser = Depends(get_current_app_user),
    db: Session = Depends(get_db),
):
    _no_store(response)
    try:
        items, next_before_id = list_messages(
            db,
            party_id,
            current_user.user_id,
            before_id=before_id,
            limit=limit,
        )
        return TaxiMessageListResponse(items=items, next_before_id=next_before_id)
    except TaxiServiceError as exc:
        _raise_service_error(exc)


@router.put("/parties/{party_id}/messages/read", response_model=TaxiReadResponse)
def read_taxi_messages(
    party_id: UUID,
    payload: TaxiReadRequest,
    response: Response,
    current_user: CurrentAppUser = Depends(get_current_app_user),
    db: Session = Depends(get_db),
):
    _no_store(response)
    try:
        mark_messages_read(db, party_id, current_user.user_id, payload.last_message_id)
        return TaxiReadResponse()
    except TaxiServiceError as exc:
        _raise_service_error(exc)


def _authenticate_websocket(token: str) -> tuple[CurrentAppUser, int]:
    config = get_supabase_auth_config()
    current_user = verify_supabase_access_token(
        token,
        config=config,
        resolver=get_jwk_resolver(),
    )
    claims = jwt.decode(token, options={"verify_signature": False})
    return current_user, int(claims["exp"])


def _save_socket_message(user_id: UUID, event: TaxiMessageSendEvent):
    with SessionLocal() as db:
        message = create_chat_message(
            db,
            event.party_id,
            user_id,
            event.client_message_id,
            event.content,
        )
        fanout = [
            (
                member_id,
                {
                    "type": "message.created",
                    "party_id": str(message.party_id),
                    "message": serialize_message(db, message, member_id).model_dump(mode="json"),
                    "party": get_party_summary(db, message.party_id, member_id).model_dump(
                        mode="json"
                    ),
                },
            )
            for member_id in active_member_ids(db, message.party_id)
        ]
        return fanout


@websocket_router.websocket("/ws/taxi")
async def taxi_websocket(websocket: WebSocket):
    authorization = websocket.headers.get("authorization", "")
    scheme, _, token = authorization.partition(" ")
    if scheme.lower() != "bearer" or not token:
        await websocket.close(code=4401, reason="Authentication required")
        return
    try:
        current_user, expires_at = await asyncio.to_thread(_authenticate_websocket, token)
    except Exception:
        await websocket.close(code=4401, reason="Invalid access token")
        return

    await websocket.accept()
    redis_client = get_async_redis()
    pubsub = redis_client.pubsub()
    send_lock = asyncio.Lock()

    async def send_json(payload):
        async with send_lock:
            await websocket.send_json(payload)

    async def redis_sender():
        await pubsub.subscribe(taxi_user_channel(current_user.user_id))
        async for item in pubsub.listen():
            if item.get("type") != "message":
                continue
            data = item.get("data")
            await send_json(json.loads(data) if isinstance(data, str) else data)

    async def socket_receiver():
        while True:
            raw = await websocket.receive_json()
            if raw.get("type") == "ping":
                await send_json({"type": "pong"})
                continue
            try:
                event = TaxiMessageSendEvent.model_validate(raw)
                fanout = await asyncio.to_thread(_save_socket_message, current_user.user_id, event)
                published = await publish_user_events(fanout)
                if not published:
                    own_event = next(
                        (payload for user_id, payload in fanout if user_id == current_user.user_id),
                        None,
                    )
                    if own_event is not None:
                        await send_json(own_event)
            except ValidationError:
                await send_json(
                    {"type": "error", "code": "INVALID_EVENT", "message": "채팅 요청이 올바르지 않습니다."}
                )
            except TaxiServiceError as exc:
                await send_json(
                    {"type": "error", "code": exc.code, "message": exc.message}
                )

    async def expire_connection():
        await asyncio.sleep(max(0, expires_at - int(time.time())))
        await websocket.close(code=4401, reason="Access token expired")

    tasks = [
        asyncio.create_task(redis_sender()),
        asyncio.create_task(socket_receiver()),
        asyncio.create_task(expire_connection()),
    ]
    try:
        done, pending = await asyncio.wait(tasks, return_when=asyncio.FIRST_COMPLETED)
        for task in done:
            with contextlib.suppress(WebSocketDisconnect, RedisError, asyncio.CancelledError):
                task.result()
        for task in pending:
            task.cancel()
    finally:
        for task in tasks:
            task.cancel()
        with contextlib.suppress(Exception):
            await pubsub.unsubscribe(taxi_user_channel(current_user.user_id))
        with contextlib.suppress(Exception):
            await pubsub.close()
