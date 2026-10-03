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
from starlette.concurrency import run_in_threadpool

from auth_config import get_supabase_auth_config
from database import SessionLocal, get_db
from schemas.app_auth import CurrentAppUser
from schemas.taxi import (
    TaxiActionResponse,
    TaxiBlockCreateRequest,
    TaxiBlockResponse,
    TaxiHomeResponse,
    TaxiLocationResponse,
    TaxiMessageListResponse,
    TaxiMessageSendEvent,
    TaxiPartyCancelRequest,
    TaxiPartyCreateRequest,
    TaxiPartyDetailResponse,
    TaxiPartyListResponse,
    TaxiPartySummaryResponse,
    TaxiPartyUpdateRequest,
    TaxiPushTokenDeleteRequest,
    TaxiPushTokenRequest,
    TaxiReadRequest,
    TaxiReadResponse,
    TaxiRecruitmentRequest,
    TaxiReportCreateRequest,
    TaxiReportResponse,
    TaxiRestrictionResponse,
    TaxiSanctionResponse,
    TaxiTermsAgreeRequest,
)
from services.taxi import (
    TaxiServiceError,
    as_utc,
    cancel_party,
    create_chat_message,
    find_chat_message_by_client_id,
    create_party,
    get_party_detail,
    join_party,
    leave_party,
    list_active_locations,
    list_messages,
    list_my_active_party_details,
    list_my_parties,
    list_parties,
    mark_messages_read,
    serialize_location,
    serialize_party_detail,
    set_recruitment,
    update_party,
)
from services.taxi_block import block_member, list_blocks, unblock
from services.taxi_push import register_token, remove_token
from services.taxi_report import create_report
from services.taxi_sanction import (
    acknowledge_sanction,
    active_suspension,
    anonymous_user_key,
    claim_sanction_hold,
    pending_notice,
)
from services.taxi_terms import agree_terms, ensure_terms_agreed, terms_required
from utils.supabase_security import get_current_app_user, get_jwk_resolver, verify_supabase_access_token
from utils.taxi_realtime import (
    TAXI_PARTIES_CHANNEL,
    build_message_events,
    get_async_redis,
    publish_message,
    publish_party_updated,
    publish_user_events,
    schedule_message_push,
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


@router.get("/home", response_model=TaxiHomeResponse)
def get_taxi_home(
    response: Response,
    target_date: date = Query(alias="date"),
    departure_location_id: int | None = None,
    destination_location_id: int | None = None,
    include_unavailable: bool = False,
    include: str = Query(default="", pattern="^[a-z,]*$"),
    limit: int = Query(default=20, ge=1, le=50),
    current_user: CurrentAppUser = Depends(get_current_app_user),
    db: Session = Depends(get_db),
):
    """화면 진입·복귀용 묶음 조회. 개별 API 여러 개를 요청 하나로 대신한다."""
    _no_store(response)
    wanted = {part for part in include.split(",") if part}
    user_id = current_user.user_id
    try:
        items, next_cursor = list_parties(
            db,
            user_id,
            target_date=target_date,
            departure_location_id=departure_location_id,
            destination_location_id=destination_location_id,
            include_unavailable=include_unavailable,
            cursor=None,
            limit=limit,
        )
        return TaxiHomeResponse(
            locations=(
                [serialize_location(location) for location in list_active_locations(db)]
                if "locations" in wanted
                else None
            ),
            parties=TaxiPartyListResponse(items=items, next_cursor=next_cursor),
            my_parties=list_my_active_party_details(db, user_id),
            recent_chats=list_my_parties(db, user_id, scope="recent_chats"),
            history=list_my_parties(db, user_id, scope="history") if "history" in wanted else None,
            restriction=_restriction(db, user_id),
        )
    except TaxiServiceError as exc:
        _raise_service_error(exc)


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
        await run_in_threadpool(ensure_terms_agreed, db, current_user.user_id)
        party = await run_in_threadpool(create_party, db, current_user.user_id, payload)
        await publish_party_updated(db, party.id)
        return await run_in_threadpool(serialize_party_detail, db, party, current_user.user_id)
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
        party, message = await run_in_threadpool(
            update_party, db, party_id, current_user.user_id, payload
        )
        if message is not None:
            await publish_message(db, message, push_exclude=current_user.user_id)
        await publish_party_updated(db, party.id)
        return await run_in_threadpool(serialize_party_detail, db, party, current_user.user_id)
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
        await run_in_threadpool(ensure_terms_agreed, db, current_user.user_id)
        party, message = await run_in_threadpool(join_party, db, party_id, current_user.user_id)
        if message is not None:
            await publish_message(db, message, push_exclude=current_user.user_id)
        await publish_party_updated(db, party.id)
        return await run_in_threadpool(serialize_party_detail, db, party, current_user.user_id)
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
        message = await run_in_threadpool(leave_party, db, party_id, current_user.user_id)
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
        message = await run_in_threadpool(
            cancel_party, db, party_id, current_user.user_id, payload.reason
        )
        if message is not None:
            await publish_message(db, message, push_exclude=current_user.user_id)
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
        message = await run_in_threadpool(
            set_recruitment, db, party_id, current_user.user_id, payload.is_open
        )
        if message is not None:
            # 모집 마감·재개는 채팅방 안내로 충분해 푸시는 보내지 않는다.
            await publish_message(db, message, push=False)
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


def _sanction_response(sanction) -> TaxiSanctionResponse | None:
    if sanction is None:
        return None
    return TaxiSanctionResponse(
        id=sanction.id,
        level=sanction.level,
        reason=sanction.reason,
        starts_at=as_utc(sanction.starts_at),
        ends_at=as_utc(sanction.ends_at) if sanction.ends_at else None,
    )


def _restriction(db: Session, user_id: UUID) -> TaxiRestrictionResponse:
    claim_sanction_hold(db, user_id)
    return TaxiRestrictionResponse(
        user_key=anonymous_user_key(user_id),
        suspension=_sanction_response(active_suspension(db, user_id)),
        notice=_sanction_response(pending_notice(db, user_id)),
        terms_required=terms_required(db, user_id),
    )


@router.get("/me/restriction", response_model=TaxiRestrictionResponse)
def get_my_taxi_restriction(
    response: Response,
    current_user: CurrentAppUser = Depends(get_current_app_user),
    db: Session = Depends(get_db),
):
    _no_store(response)
    return _restriction(db, current_user.user_id)


@router.post("/me/sanctions/{sanction_id}/ack", status_code=status.HTTP_204_NO_CONTENT)
def acknowledge_my_taxi_sanction(
    sanction_id: int,
    current_user: CurrentAppUser = Depends(get_current_app_user),
    db: Session = Depends(get_db),
):
    try:
        acknowledge_sanction(db, current_user.user_id, sanction_id)
        return Response(status_code=status.HTTP_204_NO_CONTENT)
    except TaxiServiceError as exc:
        _raise_service_error(exc)


@router.put("/me/terms", status_code=status.HTTP_204_NO_CONTENT)
def agree_my_taxi_terms(
    payload: TaxiTermsAgreeRequest,
    current_user: CurrentAppUser = Depends(get_current_app_user),
    db: Session = Depends(get_db),
):
    try:
        agree_terms(db, current_user.user_id, payload.version)
        return Response(status_code=status.HTTP_204_NO_CONTENT, headers={"Cache-Control": "no-store"})
    except TaxiServiceError as exc:
        _raise_service_error(exc)


def _block_response(block) -> TaxiBlockResponse:
    return TaxiBlockResponse(
        id=block.id,
        target_label=block.target_label,
        departure_location=block.departure_name,
        destination_location=block.destination_name,
        departure_at=as_utc(block.departure_at),
        created_at=as_utc(block.created_at),
    )


@router.get("/me/blocks", response_model=list[TaxiBlockResponse])
def list_my_taxi_blocks(
    response: Response,
    current_user: CurrentAppUser = Depends(get_current_app_user),
    db: Session = Depends(get_db),
):
    _no_store(response)
    return [_block_response(block) for block in list_blocks(db, current_user.user_id)]


@router.delete("/me/blocks/{block_id}", status_code=status.HTTP_204_NO_CONTENT)
def remove_my_taxi_block(
    block_id: int,
    current_user: CurrentAppUser = Depends(get_current_app_user),
    db: Session = Depends(get_db),
):
    try:
        unblock(db, current_user.user_id, block_id)
        return Response(status_code=status.HTTP_204_NO_CONTENT, headers={"Cache-Control": "no-store"})
    except TaxiServiceError as exc:
        _raise_service_error(exc)


@router.post(
    "/parties/{party_id}/blocks",
    response_model=TaxiBlockResponse,
    status_code=status.HTTP_201_CREATED,
)
def block_taxi_member(
    party_id: UUID,
    payload: TaxiBlockCreateRequest,
    response: Response,
    current_user: CurrentAppUser = Depends(get_current_app_user),
    db: Session = Depends(get_db),
):
    # 보복을 막기 위해 차단당한 사람에게는 알리지 않는다.
    _no_store(response)
    try:
        return _block_response(block_member(db, party_id, current_user.user_id, payload.target_label))
    except TaxiServiceError as exc:
        _raise_service_error(exc)


@router.put("/me/push-token", status_code=status.HTTP_204_NO_CONTENT)
def register_my_taxi_push_token(
    payload: TaxiPushTokenRequest,
    current_user: CurrentAppUser = Depends(get_current_app_user),
    db: Session = Depends(get_db),
):
    register_token(db, current_user.user_id, payload.token, payload.platform)
    return Response(status_code=status.HTTP_204_NO_CONTENT, headers={"Cache-Control": "no-store"})


@router.delete("/me/push-token", status_code=status.HTTP_204_NO_CONTENT)
def remove_my_taxi_push_token(
    payload: TaxiPushTokenDeleteRequest,
    current_user: CurrentAppUser = Depends(get_current_app_user),
    db: Session = Depends(get_db),
):
    remove_token(db, current_user.user_id, payload.token)
    return Response(status_code=status.HTTP_204_NO_CONTENT, headers={"Cache-Control": "no-store"})


@router.post(
    "/parties/{party_id}/reports",
    response_model=TaxiReportResponse,
    status_code=status.HTTP_201_CREATED,
)
def report_taxi_member(
    party_id: UUID,
    payload: TaxiReportCreateRequest,
    response: Response,
    current_user: CurrentAppUser = Depends(get_current_app_user),
    db: Session = Depends(get_db),
):
    # 보복을 막기 위해 신고당한 사람에게는 알리지 않는다.
    _no_store(response)
    try:
        report = create_report(db, party_id, current_user.user_id, payload)
        return TaxiReportResponse(id=report.id, created_at=report.created_at)
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
    """메시지를 저장하고 (보낼 이벤트 목록, 메시지 id, 새로 만들었는지)를 돌려준다."""
    with SessionLocal() as db:
        existing = find_chat_message_by_client_id(db, user_id, event.client_message_id)
        if existing is not None:
            # 앱이 응답을 못 받아 다시 보낸 경우. 다른 참여자에게는 이미 전달됐으므로
            # 보낸 사람에게만 확인을 돌려주고 알림도 다시 보내지 않는다.
            own_events = [
                (member_id, payload)
                for member_id, payload in build_message_events(db, existing)
                if member_id == user_id
            ]
            return own_events, existing.id, False
        ensure_terms_agreed(db, user_id)
        message = create_chat_message(
            db,
            event.party_id,
            user_id,
            event.client_message_id,
            event.content,
        )
        return build_message_events(db, message), message.id, True


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
        await pubsub.subscribe(
            taxi_user_channel(current_user.user_id),
            TAXI_PARTIES_CHANNEL,
        )
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
            # 어떤 메시지가 실패했는지 앱이 알 수 있게 오류에도 요청의 식별자를 돌려준다.
            error_context = {
                key: raw[key]
                for key in ("party_id", "client_message_id")
                if isinstance(raw.get(key), str)
            }
            try:
                event = TaxiMessageSendEvent.model_validate(raw)
                fanout, message_id, created = await asyncio.to_thread(
                    _save_socket_message, current_user.user_id, event
                )
                published = await publish_user_events(fanout)
                if created:
                    schedule_message_push(message_id)
                if not published:
                    own_event = next(
                        (payload for user_id, payload in fanout if user_id == current_user.user_id),
                        None,
                    )
                    if own_event is not None:
                        await send_json(own_event)
            except ValidationError:
                await send_json(
                    {
                        "type": "error",
                        "code": "INVALID_EVENT",
                        "message": "채팅 요청이 올바르지 않습니다.",
                        **error_context,
                    }
                )
            except TaxiServiceError as exc:
                await send_json(
                    {"type": "error", "code": exc.code, "message": exc.message, **error_context}
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
