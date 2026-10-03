from __future__ import annotations

from datetime import datetime
from uuid import UUID

from sqlalchemy.orm import Session

from models import TaxiTermsAgreement
from services.taxi import TaxiServiceError, as_utc, utc_now


# 약관 내용을 바꾸면 올린다. 앱의 kTaxiTermsVersion과 맞춰야 한다.
TAXI_TERMS_VERSION = 1


def terms_required(db: Session, user_id: UUID) -> bool:
    """아직 동의하지 않았거나 예전 버전에만 동의했으면 True."""
    agreement = db.get(TaxiTermsAgreement, user_id)
    return agreement is None or agreement.version < TAXI_TERMS_VERSION


def agree_terms(db: Session, user_id: UUID, version: int, *, now: datetime | None = None) -> None:
    if version != TAXI_TERMS_VERSION:
        raise TaxiServiceError(409, "TERMS_OUTDATED", "약관이 바뀌었어요. 앱을 업데이트한 뒤 다시 동의해주세요.")
    current = as_utc(now or utc_now())
    agreement = db.get(TaxiTermsAgreement, user_id)
    if agreement is None:
        db.add(TaxiTermsAgreement(user_id=user_id, version=version, agreed_at=current))
    elif agreement.version != version:
        agreement.version = version
        agreement.agreed_at = current
    db.commit()


def ensure_terms_agreed(db: Session, user_id: UUID) -> None:
    if terms_required(db, user_id):
        raise TaxiServiceError(403, "TERMS_REQUIRED", "택시팟 이용약관에 동의한 뒤 이용할 수 있어요.")
