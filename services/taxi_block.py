from __future__ import annotations

from datetime import datetime
from uuid import UUID

from sqlalchemy import or_
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from models import TaxiBlock
from services.taxi import TaxiServiceError, _load_party, _membership, as_utc, utc_now
from services.taxi_report import _resolve_target


BLOCK_LIMIT = 100


def block_member(
    db: Session,
    party_id: UUID,
    blocker_id: UUID,
    target_label: str,
    *,
    now: datetime | None = None,
) -> TaxiBlock:
    """같은 팟에 있던 사람을 앱에 보이는 익명 라벨로 차단한다. 상대에게는 알리지 않는다."""
    party = _load_party(db, party_id)
    if _membership(db, party.id, blocker_id) is None:
        raise TaxiServiceError(403, "NOT_PARTY_MEMBER", "이 택시팟에 참여한 사람만 차단할 수 있어요.")
    try:
        blocked_id = _resolve_target(db, party, target_label)
    except TaxiServiceError as exc:
        raise TaxiServiceError(404, "BLOCK_TARGET_NOT_FOUND", "차단할 참여자를 찾을 수 없어요.") from exc
    if blocked_id == blocker_id:
        raise TaxiServiceError(400, "CANNOT_BLOCK_SELF", "자기 자신은 차단할 수 없어요.")

    existing = _find(db, blocker_id, blocked_id)
    if existing is not None:
        return existing
    count = db.query(TaxiBlock.id).filter(TaxiBlock.blocker_id == blocker_id).count()
    if count >= BLOCK_LIMIT:
        raise TaxiServiceError(409, "BLOCK_LIMIT", "차단은 100명까지 할 수 있어요. 차단 목록에서 정리해주세요.")

    block = TaxiBlock(
        blocker_id=blocker_id,
        blocked_id=blocked_id,
        party_id=party.id,
        target_label=target_label,
        departure_name=party.departure_location.name,
        destination_name=party.destination_location.name,
        departure_at=party.departure_at,
        created_at=as_utc(now or utc_now()),
    )
    db.add(block)
    try:
        db.commit()
    except IntegrityError:
        # 같은 요청이 겹친 경우. 먼저 저장된 차단을 돌려준다.
        db.rollback()
        existing = _find(db, blocker_id, blocked_id)
        if existing is None:
            raise
        return existing
    db.refresh(block)
    return block


def _find(db: Session, blocker_id: UUID, blocked_id: UUID) -> TaxiBlock | None:
    return (
        db.query(TaxiBlock)
        .filter(TaxiBlock.blocker_id == blocker_id, TaxiBlock.blocked_id == blocked_id)
        .first()
    )


def list_blocks(db: Session, blocker_id: UUID) -> list[TaxiBlock]:
    return (
        db.query(TaxiBlock)
        .filter(TaxiBlock.blocker_id == blocker_id)
        .order_by(TaxiBlock.created_at.desc(), TaxiBlock.id.desc())
        .all()
    )


def unblock(db: Session, blocker_id: UUID, block_id: int) -> None:
    block = db.get(TaxiBlock, block_id)
    if block is None or block.blocker_id != blocker_id:
        raise TaxiServiceError(404, "BLOCK_NOT_FOUND", "차단 기록을 찾을 수 없어요.")
    db.delete(block)
    db.commit()


def related_user_ids(db: Session, user_id: UUID) -> set[UUID]:
    """내가 차단했거나 나를 차단한 사람. 서로의 팟에서 다시 만나지 않게 하는 데 쓴다."""
    rows = (
        db.query(TaxiBlock.blocker_id, TaxiBlock.blocked_id)
        .filter(or_(TaxiBlock.blocker_id == user_id, TaxiBlock.blocked_id == user_id))
        .all()
    )
    return {blocked if blocker == user_id else blocker for blocker, blocked in rows}


def blocked_by(db: Session, viewer_ids: list[UUID]) -> dict[UUID, set[UUID]]:
    """보는 사람마다 그 사람이 차단한 사람들. 여러 명을 한 번에 조회한다."""
    result: dict[UUID, set[UUID]] = {}
    if not viewer_ids:
        return result
    rows = (
        db.query(TaxiBlock.blocker_id, TaxiBlock.blocked_id)
        .filter(TaxiBlock.blocker_id.in_(viewer_ids))
        .all()
    )
    for blocker, blocked in rows:
        result.setdefault(blocker, set()).add(blocked)
    return result
