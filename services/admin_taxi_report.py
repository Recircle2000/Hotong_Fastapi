from __future__ import annotations

from datetime import datetime
from uuid import UUID

from sqlalchemy import distinct, func, or_
from sqlalchemy.orm import Session, joinedload

from models import TaxiParty, TaxiReport, TaxiSanction
from schemas.admin_v2 import (
    AdminTaxiReportDetailResponse,
    AdminTaxiReportEvidenceMessage,
    AdminTaxiReportSummaryResponse,
    AdminTaxiReportTargetStats,
    AdminTaxiReportUpdateRequest,
    AdminTaxiSanctionResponse,
)
from services.taxi import TaxiServiceError, as_utc, utc_now
from services.taxi_sanction import SUSPENSION_LEVELS, anonymous_user_key, suggested_level


OTHER_REPORTS_LIMIT = 20
TARGET_SANCTIONS_LIMIT = 20


def _target_stats(db: Session, target_ids: set[UUID]) -> dict[UUID, AdminTaxiReportTargetStats]:
    if not target_ids:
        return {}
    rows = (
        db.query(
            TaxiReport.target_id,
            func.count(TaxiReport.id),
            func.count(distinct(TaxiReport.reporter_id)),
        )
        .filter(TaxiReport.target_id.in_(target_ids))
        .group_by(TaxiReport.target_id)
        .all()
    )
    return {
        target_id: AdminTaxiReportTargetStats(total_reports=total, distinct_reporters=reporters)
        for target_id, total, reporters in rows
    }


def _parties(db: Session, party_ids: set[UUID]) -> dict[UUID, TaxiParty]:
    if not party_ids:
        return {}
    parties = (
        db.query(TaxiParty)
        .options(
            joinedload(TaxiParty.departure_location),
            joinedload(TaxiParty.destination_location),
        )
        .filter(TaxiParty.id.in_(party_ids))
        .all()
    )
    return {party.id: party for party in parties}


def _summary_fields(
    report: TaxiReport,
    party: TaxiParty | None,
    stats: AdminTaxiReportTargetStats,
) -> dict:
    snapshot = (report.evidence or {}).get("party") or {}
    departure_at = as_utc(party.departure_at) if party is not None else None
    if departure_at is None and snapshot.get("departure_at"):
        departure_at = datetime.fromisoformat(snapshot["departure_at"])
    return {
        "id": report.id,
        "reason": report.reason,
        "status": report.status,
        "created_at": as_utc(report.created_at),
        "reviewed_at": as_utc(report.reviewed_at) if report.reviewed_at else None,
        "party_id": report.party_id,
        "departure_location_name": (
            party.departure_location.name if party is not None else snapshot.get("departure_location")
        ),
        "destination_location_name": (
            party.destination_location.name if party is not None else snapshot.get("destination_location")
        ),
        "departure_at": departure_at,
        "target_key": anonymous_user_key(report.target_id),
        "target_label": report.target_label,
        "target_stats": stats,
    }


def _serialize_summaries(db: Session, reports: list[TaxiReport]) -> list[AdminTaxiReportSummaryResponse]:
    stats = _target_stats(db, {report.target_id for report in reports})
    parties = _parties(db, {report.party_id for report in reports if report.party_id is not None})
    return [
        AdminTaxiReportSummaryResponse(
            **_summary_fields(report, parties.get(report.party_id), stats[report.target_id])
        )
        for report in reports
    ]


def _target_ids_for_key(db: Session, target_key: str) -> list[UUID]:
    target_ids = [row[0] for row in db.query(distinct(TaxiReport.target_id)).all()]
    return [target_id for target_id in target_ids if anonymous_user_key(target_id) == target_key]


def list_admin_taxi_reports(
    db: Session,
    *,
    status_filter: str | None,
    target_key: str | None,
    cursor: str | None,
    limit: int,
) -> tuple[list[AdminTaxiReportSummaryResponse], str | None]:
    query = db.query(TaxiReport)
    if status_filter:
        query = query.filter(TaxiReport.status == status_filter)
    if target_key:
        target_ids = _target_ids_for_key(db, target_key)
        if not target_ids:
            return [], None
        query = query.filter(TaxiReport.target_id.in_(target_ids))
    if cursor:
        try:
            before_id = int(cursor)
        except ValueError as exc:
            raise TaxiServiceError(400, "INVALID_CURSOR", "목록 커서가 올바르지 않습니다.") from exc
        query = query.filter(TaxiReport.id < before_id)
    rows = query.order_by(TaxiReport.id.desc()).limit(limit + 1).all()
    has_more = len(rows) > limit
    rows = rows[:limit]
    return _serialize_summaries(db, rows), str(rows[-1].id) if has_more else None


def _load_report(db: Session, report_id: int) -> TaxiReport:
    report = db.query(TaxiReport).filter(TaxiReport.id == report_id).first()
    if report is None:
        raise TaxiServiceError(404, "REPORT_NOT_FOUND", "신고를 찾을 수 없습니다.")
    return report


def get_admin_taxi_report(db: Session, report_id: int) -> AdminTaxiReportDetailResponse:
    report = _load_report(db, report_id)
    others = (
        db.query(TaxiReport)
        .filter(TaxiReport.target_id == report.target_id, TaxiReport.id != report.id)
        .order_by(TaxiReport.id.desc())
        .limit(OTHER_REPORTS_LIMIT)
        .all()
    )
    party = _parties(db, {report.party_id} if report.party_id is not None else set()).get(report.party_id)
    stats = _target_stats(db, {report.target_id})[report.target_id]
    evidence = report.evidence or {}
    snapshot = evidence.get("party") or {}
    return AdminTaxiReportDetailResponse(
        **_summary_fields(report, party, stats),
        detail=report.detail,
        admin_note=report.admin_note,
        reporter_key=anonymous_user_key(report.reporter_id),
        reported_message_id=report.message_id,
        departure_summary=party.departure_summary if party is not None else snapshot.get("departure_summary"),
        messages=[AdminTaxiReportEvidenceMessage(**message) for message in evidence.get("messages", [])],
        evidence_purged=report.evidence_purged_at is not None,
        other_reports=_serialize_summaries(db, others),
        sanction_id=report.sanction_id,
        target_sanctions=serialize_admin_sanctions(
            db,
            db.query(TaxiSanction)
            .filter(TaxiSanction.user_id == report.target_id)
            .order_by(TaxiSanction.id.desc())
            .limit(TARGET_SANCTIONS_LIMIT)
            .all(),
        ),
        suggested_level=suggested_level(db, report.target_id),
    )


def update_admin_taxi_report(
    db: Session,
    report_id: int,
    payload: AdminTaxiReportUpdateRequest,
    *,
    admin_id: int,
    now: datetime | None = None,
) -> AdminTaxiReportDetailResponse:
    report = _load_report(db, report_id)
    report.status = payload.status
    report.admin_note = payload.admin_note
    if payload.status == "pending":
        report.reviewed_at = None
        report.reviewed_by_admin_id = None
    else:
        # 증거 보관 기한(처리 후 1년)은 이 시각부터 센다.
        report.reviewed_at = as_utc(now or utc_now())
        report.reviewed_by_admin_id = admin_id
    db.commit()
    return get_admin_taxi_report(db, report_id)


def _is_active_sanction(sanction: TaxiSanction, now: datetime) -> bool:
    return (
        sanction.level in SUSPENSION_LEVELS
        and sanction.revoked_at is None
        and as_utc(sanction.starts_at) <= now
        and (sanction.ends_at is None or as_utc(sanction.ends_at) > now)
    )


def serialize_admin_sanctions(
    db: Session,
    sanctions: list[TaxiSanction],
    now: datetime | None = None,
) -> list[AdminTaxiSanctionResponse]:
    current = as_utc(now or utc_now())
    ids = [sanction.id for sanction in sanctions]
    report_counts = (
        dict(
            db.query(TaxiReport.sanction_id, func.count(TaxiReport.id))
            .filter(TaxiReport.sanction_id.in_(ids))
            .group_by(TaxiReport.sanction_id)
            .all()
        )
        if ids
        else {}
    )
    return [
        AdminTaxiSanctionResponse(
            id=sanction.id,
            level=sanction.level,
            reason=sanction.reason,
            admin_note=sanction.admin_note,
            starts_at=as_utc(sanction.starts_at),
            ends_at=as_utc(sanction.ends_at) if sanction.ends_at else None,
            created_at=as_utc(sanction.created_at),
            acknowledged_at=as_utc(sanction.acknowledged_at) if sanction.acknowledged_at else None,
            revoked_at=as_utc(sanction.revoked_at) if sanction.revoked_at else None,
            revoke_reason=sanction.revoke_reason,
            is_active=_is_active_sanction(sanction, current),
            target_key=anonymous_user_key(sanction.user_id),
            report_count=report_counts.get(sanction.id, 0),
        )
        for sanction in sanctions
    ]


def list_admin_taxi_sanctions(
    db: Session,
    *,
    active_only: bool,
    target_key: str | None,
    cursor: str | None,
    limit: int,
    now: datetime | None = None,
) -> tuple[list[AdminTaxiSanctionResponse], str | None]:
    current = as_utc(now or utc_now())
    query = db.query(TaxiSanction)
    if active_only:
        query = query.filter(
            TaxiSanction.level.in_(SUSPENSION_LEVELS),
            TaxiSanction.revoked_at.is_(None),
            TaxiSanction.starts_at <= current,
            or_(TaxiSanction.ends_at.is_(None), TaxiSanction.ends_at > current),
        )
    if target_key:
        user_ids = [
            row[0]
            for row in db.query(distinct(TaxiSanction.user_id)).all()
            if anonymous_user_key(row[0]) == target_key
        ]
        if not user_ids:
            return [], None
        query = query.filter(TaxiSanction.user_id.in_(user_ids))
    if cursor:
        try:
            before_id = int(cursor)
        except ValueError as exc:
            raise TaxiServiceError(400, "INVALID_CURSOR", "목록 커서가 올바르지 않습니다.") from exc
        query = query.filter(TaxiSanction.id < before_id)
    rows = query.order_by(TaxiSanction.id.desc()).limit(limit + 1).all()
    has_more = len(rows) > limit
    rows = rows[:limit]
    return serialize_admin_sanctions(db, rows, current), str(rows[-1].id) if has_more else None
