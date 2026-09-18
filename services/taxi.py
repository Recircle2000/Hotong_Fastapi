from __future__ import annotations

import base64
import json
import secrets
from datetime import date, datetime, time, timedelta, timezone
from uuid import UUID
from zoneinfo import ZoneInfo

from sqlalchemy import and_, func, or_, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, joinedload

from models import TaxiLocation, TaxiMessage, TaxiParty, TaxiPartyMember
from schemas.taxi import (
    TaxiLocationResponse,
    TaxiMemberResponse,
    TaxiMessageResponse,
    TaxiPartyCreateRequest,
    TaxiPartyDetailResponse,
    TaxiPartySummaryResponse,
    TaxiPartyUpdateRequest,
)


KST = ZoneInfo("Asia/Seoul")
BOOKING_MIN_LEAD = timedelta(minutes=10)
OVERLAP_WINDOW = timedelta(hours=2)
CHAT_WRITE_WINDOW = timedelta(hours=3)
CHAT_RETENTION_WINDOW = timedelta(hours=48)
MEETING_CODE_RETENTION = timedelta(days=30)
MEETING_CODE_ALPHABET = "23456789ABCDEFGHJKLMNPQRSTUVWXYZ"
MEETING_CODE_MAX_ATTEMPTS = 10


class TaxiServiceError(RuntimeError):
    def __init__(self, status_code: int, code: str, message: str) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.code = code
        self.message = message


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def as_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def normalize_optional(value: str | None) -> str | None:
    if value is None:
        return None
    normalized = value.strip()
    return normalized or None


def generate_meeting_code() -> str:
    return "".join(secrets.choice(MEETING_CODE_ALPHABET) for _ in range(4))


def visible_meeting_code(
    party: TaxiParty,
    *,
    now: datetime | None = None,
) -> str | None:
    current = as_utc(now or utc_now())
    expires_at = as_utc(party.departure_at) + MEETING_CODE_RETENTION
    return party.meeting_code if current < expires_at else None


def list_active_locations(db: Session) -> list[TaxiLocation]:
    return (
        db.query(TaxiLocation)
        .filter(TaxiLocation.is_active.is_(True))
        .order_by(TaxiLocation.sort_order.asc(), TaxiLocation.name.asc())
        .all()
    )


def serialize_location(location: TaxiLocation) -> TaxiLocationResponse:
    return TaxiLocationResponse(
        id=location.id,
        name=location.name,
        category=location.category,
        sort_order=location.sort_order,
        is_active=bool(location.is_active),
    )


def party_display_status(
    party: TaxiParty,
    current_members: int,
    *,
    now: datetime | None = None,
) -> str:
    current = as_utc(now or utc_now())
    departure_at = as_utc(party.departure_at)
    if party.status == "cancelled":
        return "cancelled"
    if current >= departure_at + CHAT_WRITE_WINDOW:
        return "completed"
    if current >= departure_at:
        return "in_progress"
    if not party.recruitment_open:
        return "closed"
    if current_members >= party.max_members:
        return "full"
    return "recruiting"


def recruitment_status(party: TaxiParty, current_members: int, *, now: datetime | None = None) -> str:
    current = as_utc(now or utc_now())
    if party.status == "cancelled":
        return "cancelled"
    if current >= as_utc(party.departure_at):
        return "ended"
    if not party.recruitment_open:
        return "closed"
    if current_members >= party.max_members:
        return "full"
    return "recruiting"


def chat_deadlines(party: TaxiParty) -> tuple[datetime, datetime]:
    departure = as_utc(party.departure_at)
    if party.status == "cancelled" and party.cancelled_at is not None:
        cancelled = as_utc(party.cancelled_at)
        return cancelled, cancelled + CHAT_RETENTION_WINDOW
    return departure + CHAT_WRITE_WINDOW, departure + CHAT_RETENTION_WINDOW


def chat_status(party: TaxiParty, *, now: datetime | None = None) -> str:
    current = as_utc(now or utc_now())
    writable_until, visible_until = chat_deadlines(party)
    if current >= visible_until:
        return "expired"
    if party.status == "cancelled" or current >= writable_until:
        return "read_only"
    return "writable"


def _active_member_query(db: Session, party_id: UUID):
    return db.query(TaxiPartyMember).filter(
        TaxiPartyMember.party_id == party_id,
        TaxiPartyMember.left_at.is_(None),
    )


def _active_member_count(db: Session, party_id: UUID) -> int:
    return _active_member_query(db, party_id).count()


def _membership(db: Session, party_id: UUID, user_id: UUID) -> TaxiPartyMember | None:
    return (
        db.query(TaxiPartyMember)
        .filter(
            TaxiPartyMember.party_id == party_id,
            TaxiPartyMember.user_id == user_id,
        )
        .first()
    )


def _active_membership(db: Session, party_id: UUID, user_id: UUID) -> TaxiPartyMember | None:
    membership = _membership(db, party_id, user_id)
    return membership if membership is not None and membership.left_at is None else None


def _unread_count(db: Session, membership: TaxiPartyMember | None, party: TaxiParty, *, now: datetime) -> int:
    if membership is None or membership.left_at is not None:
        return 0
    if chat_status(party, now=now) == "expired":
        return 0
    query = db.query(TaxiMessage).filter(TaxiMessage.party_id == membership.party_id)
    if membership.last_read_message_id is not None:
        query = query.filter(TaxiMessage.id > membership.last_read_message_id)
    return query.count()


def _member_label(party: TaxiParty, member: TaxiPartyMember) -> str:
    if member.user_id == party.owner_id:
        return "방장"
    return f"참여자 {member.anonymous_number}"


def serialize_party_summary(
    db: Session,
    party: TaxiParty,
    user_id: UUID,
    *,
    now: datetime | None = None,
) -> TaxiPartySummaryResponse:
    current = as_utc(now or utc_now())
    count = _active_member_count(db, party.id)
    membership = _active_membership(db, party.id, user_id)
    writable_until, visible_until = chat_deadlines(party)
    return TaxiPartySummaryResponse(
        id=party.id,
        meeting_code=visible_meeting_code(party, now=current),
        departure_location=serialize_location(party.departure_location),
        destination_location=serialize_location(party.destination_location),
        departure_summary=party.departure_summary,
        destination_summary=party.destination_summary,
        departure_at=as_utc(party.departure_at),
        max_members=party.max_members,
        current_members=count,
        remaining_seats=max(0, party.max_members - count),
        status=party_display_status(party, count, now=current),
        recruitment_status=recruitment_status(party, count, now=current),
        chat_status=chat_status(party, now=current),
        chat_writable_until=writable_until,
        chat_visible_until=visible_until,
        is_owner=party.owner_id == user_id,
        is_member=membership is not None,
        unread_count=_unread_count(db, membership, party, now=current),
    )


def get_party_summary(
    db: Session,
    party_id: UUID,
    user_id: UUID,
) -> TaxiPartySummaryResponse:
    return serialize_party_summary(db, _load_party(db, party_id), user_id)


def serialize_party_detail(
    db: Session,
    party: TaxiParty,
    user_id: UUID,
    *,
    now: datetime | None = None,
) -> TaxiPartyDetailResponse:
    summary = serialize_party_summary(db, party, user_id, now=now)
    membership = _active_membership(db, party.id, user_id)
    members = _active_member_query(db, party.id).order_by(TaxiPartyMember.joined_at.asc()).all()
    return TaxiPartyDetailResponse(
        **summary.model_dump(),
        member_note=party.member_note if membership is not None else None,
        members=[
            TaxiMemberResponse(
                label=_member_label(party, member),
                is_owner=member.user_id == party.owner_id,
                is_me=member.user_id == user_id,
                joined_at=as_utc(member.joined_at),
            )
            for member in members
        ],
        cancellation_reason=party.cancellation_reason,
        created_at=as_utc(party.created_at),
    )


def _party_query(db: Session, party_id: UUID, *, lock: bool = False):
    query = (
        db.query(TaxiParty)
        .options(joinedload(TaxiParty.departure_location), joinedload(TaxiParty.destination_location))
        .filter(TaxiParty.id == party_id)
    )
    if lock:
        # The location relationships are eager-loaded with LEFT OUTER JOINs.
        # PostgreSQL rejects a bare FOR UPDATE in that shape because it would
        # also try to lock the nullable side of each join. Only the party row
        # participates in the state transition, so scope the row lock to it.
        query = query.with_for_update(of=TaxiParty)
    return query


def _load_party(db: Session, party_id: UUID, *, lock: bool = False) -> TaxiParty:
    query = _party_query(db, party_id, lock=lock)
    party = query.first()
    if party is None:
        raise TaxiServiceError(404, "PARTY_NOT_FOUND", "택시팟을 찾을 수 없습니다.")
    return party


def _validate_locations(db: Session, departure_id: int, destination_id: int) -> tuple[TaxiLocation, TaxiLocation]:
    if departure_id == destination_id:
        raise TaxiServiceError(400, "SAME_LOCATION", "출발지와 도착지는 달라야 합니다.")
    locations = (
        db.query(TaxiLocation)
        .filter(TaxiLocation.id.in_([departure_id, destination_id]))
        .all()
    )
    by_id = {location.id: location for location in locations}
    departure = by_id.get(departure_id)
    destination = by_id.get(destination_id)
    if departure is None or destination is None:
        raise TaxiServiceError(404, "LOCATION_NOT_FOUND", "택시 거점을 찾을 수 없습니다.")
    if not departure.is_active or not destination.is_active:
        raise TaxiServiceError(409, "LOCATION_INACTIVE", "현재 사용할 수 없는 택시 거점입니다.")
    return departure, destination


def _validate_departure_time(value: datetime, *, now: datetime | None = None) -> datetime:
    current = as_utc(now or utc_now())
    departure_at = as_utc(value)
    if departure_at < current + BOOKING_MIN_LEAD:
        raise TaxiServiceError(400, "DEPARTURE_TOO_SOON", "출발 시각은 현재보다 10분 이후여야 합니다.")
    current_kst = current.astimezone(KST)
    day_after_tomorrow = current_kst.date() + timedelta(days=2)
    booking_deadline = datetime.combine(day_after_tomorrow, time.min, tzinfo=KST).astimezone(
        timezone.utc
    )
    if departure_at >= booking_deadline:
        raise TaxiServiceError(
            400,
            "DEPARTURE_TOO_FAR",
            "출발 시각은 오늘 또는 내일만 선택할 수 있습니다.",
        )
    if departure_at.minute % 10 != 0 or departure_at.second != 0 or departure_at.microsecond != 0:
        raise TaxiServiceError(
            400,
            "DEPARTURE_INTERVAL_INVALID",
            "출발 시각은 10분 단위로 선택해야 합니다.",
        )
    return departure_at


def _lock_user(db: Session, user_id: UUID) -> None:
    if db.bind is not None and db.bind.dialect.name == "postgresql":
        db.execute(
            text("select pg_advisory_xact_lock(hashtextextended(:user_key, 0))"),
            {"user_key": str(user_id)},
        )


def _ensure_no_overlap(
    db: Session,
    user_id: UUID,
    departure_at: datetime,
    *,
    excluding_party_id: UUID | None = None,
) -> None:
    lower = departure_at - OVERLAP_WINDOW
    upper = departure_at + OVERLAP_WINDOW
    query = (
        db.query(TaxiPartyMember)
        .join(TaxiParty, TaxiParty.id == TaxiPartyMember.party_id)
        .filter(
            TaxiPartyMember.user_id == user_id,
            TaxiPartyMember.left_at.is_(None),
            TaxiParty.status == "active",
            TaxiParty.departure_at > lower,
            TaxiParty.departure_at < upper,
        )
    )
    if excluding_party_id is not None:
        query = query.filter(TaxiParty.id != excluding_party_id)
    if query.first() is not None:
        raise TaxiServiceError(
            409,
            "OVERLAPPING_PARTY",
            "출발 시각이 2시간 이내인 다른 택시팟에 이미 참여 중입니다.",
        )


def _ensure_no_active_party(db: Session, user_id: UUID, *, now: datetime | None = None) -> None:
    current = as_utc(now or utc_now())
    exists = (
        db.query(TaxiPartyMember)
        .join(TaxiParty, TaxiParty.id == TaxiPartyMember.party_id)
        .filter(
            TaxiPartyMember.user_id == user_id,
            TaxiPartyMember.left_at.is_(None),
            TaxiParty.status == "active",
            TaxiParty.departure_at > current,
        )
        .first()
    )
    if exists is not None:
        raise TaxiServiceError(
            409, "ACTIVE_PARTY_EXISTS",
            "이미 모집 중인 택시팟이 있습니다. 모집 종료 후 다시 시도해주세요.",
        )


def _create_system_message(db: Session, party_id: UUID, content: str) -> TaxiMessage:
    message = TaxiMessage(
        party_id=party_id,
        sender_id=None,
        message_type="system",
        content=content,
    )
    db.add(message)
    db.flush()
    return message


def create_party(
    db: Session,
    user_id: UUID,
    payload: TaxiPartyCreateRequest,
    *,
    now: datetime | None = None,
) -> TaxiParty:
    existing = (
        db.query(TaxiParty)
        .filter(
            TaxiParty.owner_id == user_id,
            TaxiParty.client_request_id == payload.client_request_id,
        )
        .first()
    )
    if existing is not None:
        return _load_party(db, existing.id)

    departure_at = _validate_departure_time(payload.departure_at, now=now)
    _validate_locations(db, payload.departure_location_id, payload.destination_location_id)
    _lock_user(db, user_id)
    existing = (
        db.query(TaxiParty)
        .filter(
            TaxiParty.owner_id == user_id,
            TaxiParty.client_request_id == payload.client_request_id,
        )
        .first()
    )
    if existing is not None:
        return _load_party(db, existing.id)
    _ensure_no_active_party(db, user_id, now=now)

    party: TaxiParty | None = None
    for _ in range(MEETING_CODE_MAX_ATTEMPTS):
        meeting_code = generate_meeting_code()
        candidate = TaxiParty(
            client_request_id=payload.client_request_id,
            meeting_code=meeting_code,
            owner_id=user_id,
            departure_location_id=payload.departure_location_id,
            destination_location_id=payload.destination_location_id,
            departure_summary=payload.departure_summary.strip(),
            destination_summary=normalize_optional(payload.destination_summary),
            member_note=normalize_optional(payload.member_note),
            departure_at=departure_at,
            max_members=payload.max_members,
        )
        try:
            with db.begin_nested():
                db.add(candidate)
                db.flush()
            party = candidate
            break
        except IntegrityError as exc:
            collision = (
                db.query(TaxiParty.id)
                .filter(TaxiParty.meeting_code == meeting_code)
                .first()
            )
            if collision is None:
                raise TaxiServiceError(
                    409,
                    "PARTY_CREATE_CONFLICT",
                    "택시팟 생성 요청이 충돌했습니다.",
                ) from exc
    if party is None:
        raise TaxiServiceError(
            503,
            "MEETING_CODE_UNAVAILABLE",
            "택시팟 코드를 발급하지 못했습니다. 잠시 후 다시 시도해주세요.",
        )
    db.add(TaxiPartyMember(party_id=party.id, user_id=user_id, anonymous_number=None))
    _create_system_message(db, party.id, "택시팟이 만들어졌습니다.")
    try:
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        retry = (
            db.query(TaxiParty)
            .filter(
                TaxiParty.owner_id == user_id,
                TaxiParty.client_request_id == payload.client_request_id,
            )
            .first()
        )
        if retry is not None:
            return _load_party(db, retry.id)
        raise TaxiServiceError(409, "PARTY_CREATE_CONFLICT", "택시팟 생성 요청이 충돌했습니다.") from exc
    return _load_party(db, party.id)


def _encode_cursor(party: TaxiParty) -> str:
    raw = json.dumps(
        {"departure_at": as_utc(party.departure_at).isoformat(), "id": str(party.id)},
        separators=(",", ":"),
    ).encode()
    return base64.urlsafe_b64encode(raw).decode().rstrip("=")


def _decode_cursor(cursor: str) -> tuple[datetime, UUID]:
    try:
        padding = "=" * (-len(cursor) % 4)
        data = json.loads(base64.urlsafe_b64decode(cursor + padding))
        return as_utc(datetime.fromisoformat(data["departure_at"])), UUID(data["id"])
    except (ValueError, TypeError, KeyError, json.JSONDecodeError) as exc:
        raise TaxiServiceError(400, "INVALID_CURSOR", "목록 커서가 올바르지 않습니다.") from exc


def list_parties(
    db: Session,
    user_id: UUID,
    *,
    target_date: date,
    departure_location_id: int | None,
    destination_location_id: int | None,
    include_unavailable: bool,
    cursor: str | None,
    limit: int,
    now: datetime | None = None,
) -> tuple[list[TaxiPartySummaryResponse], str | None]:
    current = as_utc(now or utc_now())
    start = datetime.combine(target_date, time.min, KST).astimezone(timezone.utc)
    end = start + timedelta(days=1)
    query = (
        db.query(TaxiParty)
        .options(joinedload(TaxiParty.departure_location), joinedload(TaxiParty.destination_location))
        .filter(
            TaxiParty.status == "active",
            TaxiParty.departure_at >= max(start, current),
            TaxiParty.departure_at < end,
        )
    )
    if departure_location_id is not None:
        query = query.filter(TaxiParty.departure_location_id == departure_location_id)
    if destination_location_id is not None:
        query = query.filter(TaxiParty.destination_location_id == destination_location_id)
    items: list[TaxiPartySummaryResponse] = []
    scan_cursor = _decode_cursor(cursor) if cursor else None
    batch_size = max(limit * 2, 50)
    while len(items) < limit:
        batch_query = query
        if scan_cursor is not None:
            cursor_time, cursor_id = scan_cursor
            batch_query = batch_query.filter(
                or_(
                    TaxiParty.departure_at > cursor_time,
                    and_(TaxiParty.departure_at == cursor_time, TaxiParty.id > cursor_id),
                )
            )
        parties = (
            batch_query.order_by(TaxiParty.departure_at.asc(), TaxiParty.id.asc())
            .limit(batch_size)
            .all()
        )
        if not parties:
            return items, None
        for index, party in enumerate(parties):
            summary = serialize_party_summary(db, party, user_id, now=current)
            if include_unavailable or summary.status == "recruiting" or summary.is_member:
                items.append(summary)
            if len(items) == limit:
                has_more = index < len(parties) - 1 or len(parties) == batch_size
                return items, _encode_cursor(party) if has_more else None
        if len(parties) < batch_size:
            return items, None
        last = parties[-1]
        scan_cursor = (as_utc(last.departure_at), last.id)
    return items, None


def list_my_parties(
    db: Session,
    user_id: UUID,
    *,
    scope: str,
    now: datetime | None = None,
) -> list[TaxiPartySummaryResponse]:
    current = as_utc(now or utc_now())
    query = (
        db.query(TaxiParty)
        .join(TaxiPartyMember, TaxiPartyMember.party_id == TaxiParty.id)
        .options(joinedload(TaxiParty.departure_location), joinedload(TaxiParty.destination_location))
        .filter(TaxiPartyMember.user_id == user_id, TaxiPartyMember.left_at.is_(None))
    )
    cutoff = current - timedelta(days=30)
    if scope == "history":
        query = query.filter(
            or_(
                TaxiParty.status == "cancelled",
                TaxiParty.departure_at <= current,
            ),
            TaxiParty.departure_at >= cutoff,
        ).order_by(TaxiParty.departure_at.desc())
    elif scope == "recent_chats":
        query = query.filter(
            or_(
                and_(
                    TaxiParty.status == "active",
                    TaxiParty.departure_at <= current,
                    TaxiParty.departure_at > current - CHAT_RETENTION_WINDOW,
                ),
                and_(
                    TaxiParty.status == "cancelled",
                    func.coalesce(TaxiParty.cancelled_at, TaxiParty.departure_at)
                    > current - CHAT_RETENTION_WINDOW,
                ),
            )
        ).order_by(TaxiParty.departure_at.desc())
    else:
        query = query.filter(
            TaxiParty.status == "active",
            TaxiParty.departure_at > current,
        ).order_by(TaxiParty.departure_at.asc())
    items = [serialize_party_summary(db, party, user_id, now=current) for party in query.all()]
    if scope == "recent_chats":
        items.sort(
            key=lambda item: (
                item.chat_status != "writable",
                -item.departure_at.timestamp(),
            )
        )
    return items


def get_party_detail(db: Session, party_id: UUID, user_id: UUID) -> TaxiPartyDetailResponse:
    return serialize_party_detail(db, _load_party(db, party_id), user_id)


def update_party(
    db: Session,
    party_id: UUID,
    user_id: UUID,
    payload: TaxiPartyUpdateRequest,
    *,
    now: datetime | None = None,
) -> tuple[TaxiParty, TaxiMessage | None]:
    current = as_utc(now or utc_now())
    party = _load_party(db, party_id, lock=True)
    if party.owner_id != user_id:
        raise TaxiServiceError(403, "OWNER_REQUIRED", "방장만 택시팟을 수정할 수 있습니다.")
    if party.status == "cancelled" or current >= as_utc(party.departure_at):
        raise TaxiServiceError(409, "PARTY_NOT_EDITABLE", "더 이상 수정할 수 없는 택시팟입니다.")

    has_other_members = _active_member_count(db, party.id) > 1
    protected_changes = (
        payload.departure_location_id is not None
        and payload.departure_location_id != party.departure_location_id
    ) or (
        payload.destination_location_id is not None
        and payload.destination_location_id != party.destination_location_id
    ) or (
        payload.departure_at is not None
        and as_utc(payload.departure_at) != as_utc(party.departure_at)
    ) or (
        payload.max_members is not None
        and payload.max_members != party.max_members
    )
    if has_other_members and protected_changes:
        raise TaxiServiceError(
            409,
            "PARTY_CORE_FIELDS_LOCKED",
            "참여자가 있는 방은 경로, 시간, 정원을 변경할 수 없습니다.",
        )

    departure_id = payload.departure_location_id or party.departure_location_id
    destination_id = payload.destination_location_id or party.destination_location_id
    if protected_changes:
        _validate_locations(db, departure_id, destination_id)
    changed = protected_changes
    if payload.departure_at is not None and as_utc(payload.departure_at) != as_utc(party.departure_at):
        new_departure = _validate_departure_time(payload.departure_at, now=current)
        _lock_user(db, user_id)
        _ensure_no_overlap(db, user_id, new_departure, excluding_party_id=party.id)
        party.departure_at = new_departure
    if payload.max_members is not None and payload.max_members != party.max_members:
        party.max_members = payload.max_members
    if payload.departure_location_id is not None and payload.departure_location_id != party.departure_location_id:
        party.departure_location_id = payload.departure_location_id
    if payload.destination_location_id is not None and payload.destination_location_id != party.destination_location_id:
        party.destination_location_id = payload.destination_location_id
    if payload.departure_summary is not None and payload.departure_summary != party.departure_summary:
        party.departure_summary = payload.departure_summary.strip()
        changed = True
    if "destination_summary" in payload.model_fields_set:
        destination_summary = normalize_optional(payload.destination_summary)
        if destination_summary != party.destination_summary:
            party.destination_summary = destination_summary
            changed = True
    if "member_note" in payload.model_fields_set:
        member_note = normalize_optional(payload.member_note)
        if member_note != party.member_note:
            party.member_note = member_note
            changed = True
    if not changed:
        return party, None
    party.updated_at = current
    message = _create_system_message(db, party.id, "방장이 택시팟 안내를 수정했습니다.")
    db.commit()
    return _load_party(db, party.id), message


def join_party(
    db: Session,
    party_id: UUID,
    user_id: UUID,
    *,
    now: datetime | None = None,
) -> tuple[TaxiParty, TaxiMessage | None]:
    current = as_utc(now or utc_now())
    party = _load_party(db, party_id, lock=True)
    membership = _membership(db, party.id, user_id)
    if membership is not None and membership.left_at is None:
        return party, None
    count = _active_member_count(db, party.id)
    if party_display_status(party, count, now=current) != "recruiting":
        raise TaxiServiceError(409, "PARTY_NOT_JOINABLE", "현재 참여할 수 없는 택시팟입니다.")
    _lock_user(db, user_id)
    _ensure_no_active_party(db, user_id, now=current)
    if count >= party.max_members:
        raise TaxiServiceError(409, "PARTY_FULL", "택시팟 정원이 마감되었습니다.")

    if membership is None:
        highest = (
            db.query(func.max(TaxiPartyMember.anonymous_number))
            .filter(TaxiPartyMember.party_id == party.id)
            .scalar()
        ) or 0
        membership = TaxiPartyMember(
            party_id=party.id,
            user_id=user_id,
            anonymous_number=highest + 1,
        )
        db.add(membership)
    else:
        membership.left_at = None
        membership.joined_at = current
    db.flush()
    message = _create_system_message(db, party.id, f"{_member_label(party, membership)}님이 참여했습니다.")
    db.commit()
    return _load_party(db, party.id), message


def leave_party(db: Session, party_id: UUID, user_id: UUID, *, now: datetime | None = None) -> TaxiMessage:
    current = as_utc(now or utc_now())
    party = _load_party(db, party_id, lock=True)
    if party.owner_id == user_id:
        raise TaxiServiceError(409, "OWNER_CANNOT_LEAVE", "방장은 택시팟을 취소해야 합니다.")
    membership = _active_membership(db, party.id, user_id)
    if membership is None:
        raise TaxiServiceError(404, "MEMBERSHIP_NOT_FOUND", "참여 중인 택시팟이 아닙니다.")
    if current >= as_utc(party.departure_at):
        raise TaxiServiceError(409, "PARTY_ALREADY_DEPARTED", "출발 후에는 택시팟에서 나갈 수 없습니다.")
    label = _member_label(party, membership)
    membership.left_at = current
    message = _create_system_message(db, party.id, f"{label}님이 나갔습니다.")
    db.commit()
    return message


def cancel_party(
    db: Session,
    party_id: UUID,
    user_id: UUID | None,
    reason: str | None,
    *,
    admin_id: int | None = None,
    now: datetime | None = None,
) -> TaxiMessage | None:
    current = as_utc(now or utc_now())
    party = _load_party(db, party_id, lock=True)
    if admin_id is None and (user_id is None or party.owner_id != user_id):
        raise TaxiServiceError(403, "OWNER_REQUIRED", "방장만 택시팟을 취소할 수 있습니다.")
    if party.status == "cancelled":
        return None
    if admin_id is None and current >= as_utc(party.departure_at):
        raise TaxiServiceError(409, "PARTY_ALREADY_DEPARTED", "출발 후에는 택시팟을 취소할 수 없습니다.")
    party.status = "cancelled"
    party.recruitment_open = False
    party.cancellation_reason = normalize_optional(reason)
    party.cancelled_by_admin_id = admin_id
    party.cancelled_at = current
    prefix = "관리자가" if admin_id is not None else "방장이"
    content = f"{prefix} 택시팟을 취소했습니다."
    if party.cancellation_reason:
        content += f" 사유: {party.cancellation_reason}"
    message = _create_system_message(db, party.id, content)
    db.commit()
    return message


def set_recruitment(
    db: Session,
    party_id: UUID,
    user_id: UUID,
    is_open: bool,
    *,
    now: datetime | None = None,
) -> TaxiMessage | None:
    current = as_utc(now or utc_now())
    party = _load_party(db, party_id, lock=True)
    if party.owner_id != user_id:
        raise TaxiServiceError(403, "OWNER_REQUIRED", "방장만 모집 상태를 변경할 수 있습니다.")
    if party.status == "cancelled" or current >= as_utc(party.departure_at):
        raise TaxiServiceError(409, "PARTY_NOT_EDITABLE", "모집 상태를 변경할 수 없습니다.")
    if party.recruitment_open == is_open:
        return None
    if is_open and _active_member_count(db, party.id) >= party.max_members:
        raise TaxiServiceError(409, "PARTY_FULL", "정원이 가득 차 모집을 다시 열 수 없습니다.")
    party.recruitment_open = is_open
    content = "방장이 모집을 다시 시작했습니다." if is_open else "방장이 모집을 마감했습니다."
    message = _create_system_message(db, party.id, content)
    db.commit()
    return message


def active_member_ids(db: Session, party_id: UUID) -> list[UUID]:
    return [member.user_id for member in _active_member_query(db, party_id).all()]


def serialize_message(db: Session, message: TaxiMessage, viewer_id: UUID) -> TaxiMessageResponse:
    party = _load_party(db, message.party_id)
    sender_label = None
    if message.sender_id is not None:
        sender = _membership(db, party.id, message.sender_id)
        sender_label = _member_label(party, sender) if sender is not None else "참여자"
    return TaxiMessageResponse(
        id=message.id,
        party_id=message.party_id,
        message_type=message.message_type,
        sender_label=sender_label,
        is_mine=message.sender_id == viewer_id,
        content=message.content,
        created_at=as_utc(message.created_at),
    )


def list_messages(
    db: Session,
    party_id: UUID,
    user_id: UUID,
    *,
    before_id: int | None,
    limit: int,
    now: datetime | None = None,
) -> tuple[list[TaxiMessageResponse], int | None]:
    party = _load_party(db, party_id)
    if _active_membership(db, party_id, user_id) is None:
        raise TaxiServiceError(403, "MEMBERSHIP_REQUIRED", "참여자만 채팅을 볼 수 있습니다.")
    if chat_status(party, now=now) == "expired":
        raise TaxiServiceError(410, "CHAT_EXPIRED", "보관 기간이 지나 삭제된 채팅입니다.")
    query = db.query(TaxiMessage).filter(TaxiMessage.party_id == party_id)
    if before_id is not None:
        query = query.filter(TaxiMessage.id < before_id)
    rows = query.order_by(TaxiMessage.id.desc()).limit(limit + 1).all()
    has_more = len(rows) > limit
    rows = rows[:limit]
    rows.reverse()
    next_before = rows[0].id if has_more and rows else None
    return [serialize_message(db, row, user_id) for row in rows], next_before


def create_chat_message(
    db: Session,
    party_id: UUID,
    user_id: UUID,
    client_message_id: UUID,
    content: str,
    *,
    now: datetime | None = None,
) -> TaxiMessage:
    current = as_utc(now or utc_now())
    existing = (
        db.query(TaxiMessage)
        .filter(
            TaxiMessage.sender_id == user_id,
            TaxiMessage.client_message_id == client_message_id,
        )
        .first()
    )
    if existing is not None:
        return existing
    party = _load_party(db, party_id)
    if _active_membership(db, party.id, user_id) is None:
        raise TaxiServiceError(403, "MEMBERSHIP_REQUIRED", "참여자만 채팅을 보낼 수 있습니다.")
    if chat_status(party, now=current) != "writable":
        raise TaxiServiceError(409, "CHAT_READ_ONLY", "종료된 택시팟의 채팅은 읽기 전용입니다.")
    recent_count = (
        db.query(TaxiMessage)
        .filter(
            TaxiMessage.party_id == party.id,
            TaxiMessage.sender_id == user_id,
            TaxiMessage.created_at >= current - timedelta(seconds=10),
        )
        .count()
    )
    if recent_count >= 5:
        raise TaxiServiceError(429, "MESSAGE_RATE_LIMITED", "메시지를 너무 빠르게 보내고 있습니다.")
    normalized = content.strip()
    if not normalized or len(normalized) > 500:
        raise TaxiServiceError(400, "INVALID_MESSAGE", "메시지는 1자 이상 500자 이하여야 합니다.")
    message = TaxiMessage(
        party_id=party.id,
        sender_id=user_id,
        message_type="chat",
        content=normalized,
        client_message_id=client_message_id,
        created_at=current,
    )
    db.add(message)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        duplicate = (
            db.query(TaxiMessage)
            .filter(
                TaxiMessage.sender_id == user_id,
                TaxiMessage.client_message_id == client_message_id,
            )
            .first()
        )
        if duplicate is None:
            raise
        return duplicate
    db.refresh(message)
    return message


def mark_messages_read(
    db: Session,
    party_id: UUID,
    user_id: UUID,
    last_message_id: int,
    *,
    now: datetime | None = None,
) -> None:
    party = _load_party(db, party_id)
    membership = _active_membership(db, party_id, user_id)
    if membership is None:
        raise TaxiServiceError(403, "MEMBERSHIP_REQUIRED", "참여자만 읽음 상태를 변경할 수 있습니다.")
    if chat_status(party, now=now) == "expired":
        raise TaxiServiceError(410, "CHAT_EXPIRED", "보관 기간이 지나 삭제된 채팅입니다.")
    message = (
        db.query(TaxiMessage)
        .filter(TaxiMessage.party_id == party_id, TaxiMessage.id == last_message_id)
        .first()
    )
    if message is None:
        raise TaxiServiceError(404, "MESSAGE_NOT_FOUND", "메시지를 찾을 수 없습니다.")
    membership.last_read_message_id = max(membership.last_read_message_id or 0, last_message_id)
    db.commit()
