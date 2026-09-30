from __future__ import annotations

import hashlib
from datetime import datetime
from uuid import UUID

from sqlalchemy import distinct, func
from sqlalchemy.orm import Session, joinedload

from models import TaxiParty, TaxiReport
from schemas.admin_v2 import (
    AdminTaxiReportDetailResponse,
    AdminTaxiReportEvidenceMessage,
    AdminTaxiReportSummaryResponse,
    AdminTaxiReportTargetStats,
    AdminTaxiReportUpdateRequest,
)
from services.taxi import TaxiServiceError, as_utc, utc_now


OTHER_REPORTS_LIMIT = 20


def anonymous_user_key(user_id: UUID) -> str:
    """관리자 화면에서 같은 사용자를 알아볼 수 있는 짧은 익명 ID. 원래 user_id는 알 수 없다."""
    return hashlib.sha256(str(user_id).encode()).hexdigest()[:6]


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
