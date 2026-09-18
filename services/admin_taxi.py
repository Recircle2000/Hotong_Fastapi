from __future__ import annotations

import base64
import json
from datetime import datetime, timezone
from uuid import UUID

from sqlalchemy import and_, func, or_
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, joinedload

from models import TaxiLocation, TaxiParty, TaxiPartyMember
from schemas.admin_v2 import (
    AdminTaxiLocationResponse,
    AdminTaxiPartySummaryResponse,
)
from services.taxi import TaxiServiceError, as_utc, recruitment_status


def serialize_admin_location(location: TaxiLocation) -> AdminTaxiLocationResponse:
    return AdminTaxiLocationResponse(
        id=location.id,
        name=location.name,
        category=location.category,
        sort_order=location.sort_order,
        is_active=bool(location.is_active),
    )


def list_admin_taxi_locations(db: Session) -> list[AdminTaxiLocationResponse]:
    rows = db.query(TaxiLocation).order_by(TaxiLocation.sort_order.asc(), TaxiLocation.name.asc()).all()
    return [serialize_admin_location(row) for row in rows]


def create_admin_taxi_location(
    db: Session,
    *,
    name: str,
    category: str,
    sort_order: int,
    is_active: bool,
) -> AdminTaxiLocationResponse:
    normalized = name.strip()
    existing = db.query(TaxiLocation).filter(func.lower(TaxiLocation.name) == normalized.lower()).first()
    if existing is not None:
        raise TaxiServiceError(409, "LOCATION_NAME_EXISTS", "같은 이름의 택시 거점이 이미 있습니다.")
    location = TaxiLocation(
        name=normalized,
        category=category,
        sort_order=sort_order,
        is_active=is_active,
    )
    db.add(location)
    try:
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise TaxiServiceError(409, "LOCATION_NAME_EXISTS", "같은 이름의 택시 거점이 이미 있습니다.") from exc
    db.refresh(location)
    return serialize_admin_location(location)


def update_admin_taxi_location(
    db: Session,
    location_id: int,
    *,
    name: str,
    category: str,
    sort_order: int,
    is_active: bool,
) -> AdminTaxiLocationResponse:
    location = db.query(TaxiLocation).filter(TaxiLocation.id == location_id).first()
    if location is None:
        raise TaxiServiceError(404, "LOCATION_NOT_FOUND", "택시 거점을 찾을 수 없습니다.")
    normalized = name.strip()
    duplicate = (
        db.query(TaxiLocation)
        .filter(func.lower(TaxiLocation.name) == normalized.lower(), TaxiLocation.id != location_id)
        .first()
    )
    if duplicate is not None:
        raise TaxiServiceError(409, "LOCATION_NAME_EXISTS", "같은 이름의 택시 거점이 이미 있습니다.")
    location.name = normalized
    location.category = category
    location.sort_order = sort_order
    location.is_active = is_active
    db.commit()
    db.refresh(location)
    return serialize_admin_location(location)


def delete_admin_taxi_location(db: Session, location_id: int) -> None:
    location = db.query(TaxiLocation).filter(TaxiLocation.id == location_id).first()
    if location is None:
        raise TaxiServiceError(404, "LOCATION_NOT_FOUND", "택시 거점을 찾을 수 없습니다.")
    referenced = (
        db.query(TaxiParty.id)
        .filter(
            or_(
                TaxiParty.departure_location_id == location_id,
                TaxiParty.destination_location_id == location_id,
            )
        )
        .first()
    )
    if referenced is not None:
        raise TaxiServiceError(
            409,
            "LOCATION_IN_USE",
            "사용 기록이 있는 거점은 삭제할 수 없습니다. 비활성화해주세요.",
        )
    db.delete(location)
    db.commit()


def _encode_cursor(party: TaxiParty) -> str:
    data = json.dumps(
        {"departure_at": as_utc(party.departure_at).isoformat(), "id": str(party.id)},
        separators=(",", ":"),
    ).encode()
    return base64.urlsafe_b64encode(data).decode().rstrip("=")


def _decode_cursor(cursor: str) -> tuple[datetime, UUID]:
    try:
        padding = "=" * (-len(cursor) % 4)
        data = json.loads(base64.urlsafe_b64decode(cursor + padding))
        value = datetime.fromisoformat(data["departure_at"])
        if value.tzinfo is None:
            value = value.replace(tzinfo=timezone.utc)
        return value.astimezone(timezone.utc), UUID(data["id"])
    except (ValueError, TypeError, KeyError, json.JSONDecodeError) as exc:
        raise TaxiServiceError(400, "INVALID_CURSOR", "목록 커서가 올바르지 않습니다.") from exc


def list_admin_taxi_parties(
    db: Session,
    *,
    status_filter: str | None,
    departure_location_id: int | None,
    destination_location_id: int | None,
    cursor: str | None,
    limit: int,
) -> tuple[list[AdminTaxiPartySummaryResponse], str | None]:
    query = db.query(TaxiParty).options(
        joinedload(TaxiParty.departure_location),
        joinedload(TaxiParty.destination_location),
    )
    if departure_location_id is not None:
        query = query.filter(TaxiParty.departure_location_id == departure_location_id)
    if destination_location_id is not None:
        query = query.filter(TaxiParty.destination_location_id == destination_location_id)
    now = datetime.now(timezone.utc)
    items: list[AdminTaxiPartySummaryResponse] = []
    scan_cursor = _decode_cursor(cursor) if cursor else None
    batch_size = max(limit * 2, 100)
    while len(items) < limit:
        batch_query = query
        if scan_cursor is not None:
            cursor_time, cursor_id = scan_cursor
            batch_query = batch_query.filter(
                or_(
                    TaxiParty.departure_at < cursor_time,
                    and_(TaxiParty.departure_at == cursor_time, TaxiParty.id < cursor_id),
                )
            )
        rows = (
            batch_query.order_by(TaxiParty.departure_at.desc(), TaxiParty.id.desc())
            .limit(batch_size)
            .all()
        )
        if not rows:
            return items, None
        for index, party in enumerate(rows):
            count = (
                db.query(TaxiPartyMember)
                .filter(TaxiPartyMember.party_id == party.id, TaxiPartyMember.left_at.is_(None))
                .count()
            )
            display_status = recruitment_status(party, count, now=now)
            if status_filter and display_status != status_filter:
                continue
            items.append(
                AdminTaxiPartySummaryResponse(
                    id=party.id,
                    departure_location_name=party.departure_location.name,
                    destination_location_name=party.destination_location.name,
                    departure_summary=party.departure_summary,
                    destination_summary=party.destination_summary,
                    departure_at=as_utc(party.departure_at),
                    current_members=count,
                    max_members=party.max_members,
                    status=display_status,
                    cancellation_reason=party.cancellation_reason,
                    created_at=as_utc(party.created_at),
                )
            )
            if len(items) == limit:
                has_more = index < len(rows) - 1 or len(rows) == batch_size
                return items, _encode_cursor(party) if has_more else None
        if len(rows) < batch_size:
            return items, None
        last = rows[-1]
        scan_cursor = (as_utc(last.departure_at), last.id)
    return items, None
