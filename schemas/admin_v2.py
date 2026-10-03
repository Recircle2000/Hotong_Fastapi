from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, Field, field_validator


class AdminLoginRequest(BaseModel):
    email: str
    password: str


class AdminLogoutResponse(BaseModel):
    success: bool = True


class AdminSessionUser(BaseModel):
    id: int
    email: str
    is_admin: bool


class AdminSessionResponse(BaseModel):
    authenticated: bool = True
    user: AdminSessionUser


class AdminNoticePayload(BaseModel):
    title: str = Field(..., min_length=1, max_length=255)
    content: str = Field(..., min_length=1)
    notice_type: str = Field(default="App")
    is_pinned: bool = False


class AdminNoticeResponse(BaseModel):
    id: int
    title: str
    content: str
    notice_type: str
    is_pinned: bool
    created_at: datetime | None


class AdminEmergencyNoticePayload(BaseModel):
    category: str = Field(..., min_length=1)
    title: str = Field(..., min_length=1, max_length=255)
    content: str = Field(..., min_length=1)
    created_at: datetime
    end_at: datetime


class AdminEmergencyNoticeResponse(BaseModel):
    id: int
    category: str
    category_label: str
    title: str
    content: str
    created_at: datetime
    end_at: datetime
    status: str


class AdminShuttleStationPayload(BaseModel):
    name: str = Field(..., min_length=1, max_length=255)
    latitude: float = Field(..., ge=-90, le=90)
    longitude: float = Field(..., ge=-180, le=180)
    description: str | None = Field(default=None, max_length=500)
    image_url: str | None = Field(default=None, max_length=500)
    is_active: bool = True


class AdminShuttleStationResponse(BaseModel):
    id: int
    name: str
    latitude: float
    longitude: float
    description: str | None
    image_url: str | None
    is_active: bool


class AdminTaxiLocationPayload(BaseModel):
    name: str = Field(..., min_length=1, max_length=80)
    category: Literal["campus", "station", "terminal", "other"] = "other"
    sort_order: int = Field(default=0, ge=0, le=10000)
    is_active: bool = True

    @field_validator("name")
    @classmethod
    def normalize_name(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized:
            raise ValueError("location name is empty")
        return normalized


class AdminTaxiLocationResponse(AdminTaxiLocationPayload):
    id: int


class AdminTaxiPartySummaryResponse(BaseModel):
    id: UUID
    departure_location_name: str
    destination_location_name: str
    departure_summary: str
    destination_summary: str | None
    departure_at: datetime
    current_members: int
    max_members: int
    status: str
    cancellation_reason: str | None
    created_at: datetime


class AdminTaxiPartyListResponse(BaseModel):
    items: list[AdminTaxiPartySummaryResponse]
    next_cursor: str | None = None


class AdminAppSettingsResponse(BaseModel):
    taxi_enabled: bool
    taxi_updated_at: datetime | None = None


class AdminAppSettingsUpdateRequest(BaseModel):
    taxi_enabled: bool


class AdminTaxiPartyCancelRequest(BaseModel):
    reason: str = Field(..., min_length=1, max_length=200)

    @field_validator("reason")
    @classmethod
    def normalize_reason(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized:
            raise ValueError("cancellation reason is empty")
        return normalized


AdminTaxiReportStatus = Literal["pending", "resolved", "dismissed"]


class AdminTaxiReportTargetStats(BaseModel):
    total_reports: int
    distinct_reporters: int


class AdminTaxiReportSummaryResponse(BaseModel):
    id: int
    reason: str
    status: AdminTaxiReportStatus
    created_at: datetime
    reviewed_at: datetime | None
    party_id: UUID | None
    departure_location_name: str | None
    destination_location_name: str | None
    departure_at: datetime | None
    # user_id 대신 해시 앞자리로 만든 익명 ID만 내려준다.
    target_key: str
    target_label: str
    target_stats: AdminTaxiReportTargetStats


class AdminTaxiReportListResponse(BaseModel):
    items: list[AdminTaxiReportSummaryResponse]
    next_cursor: str | None = None


class AdminTaxiReportEvidenceMessage(BaseModel):
    id: int
    type: str
    label: str | None
    content: str
    created_at: datetime
    is_target: bool


AdminTaxiSanctionLevel = Literal["warning", "suspend_3d", "suspend_7d", "permanent"]


class AdminTaxiSanctionResponse(BaseModel):
    id: int
    level: AdminTaxiSanctionLevel
    reason: str
    admin_note: str | None
    starts_at: datetime
    ends_at: datetime | None
    created_at: datetime
    acknowledged_at: datetime | None
    revoked_at: datetime | None
    revoke_reason: str | None
    is_active: bool
    target_key: str
    report_count: int


class AdminTaxiSanctionListResponse(BaseModel):
    items: list[AdminTaxiSanctionResponse]
    next_cursor: str | None = None


class AdminTaxiSanctionCreateRequest(BaseModel):
    level: AdminTaxiSanctionLevel
    reason: str = Field(..., min_length=1, max_length=300)
    admin_note: str | None = Field(default=None, max_length=1000)
    resolve_pending_reports: bool = True

    @field_validator("reason")
    @classmethod
    def normalize_reason(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized:
            raise ValueError("sanction reason is empty")
        return normalized

    @field_validator("admin_note")
    @classmethod
    def normalize_note(cls, value: str | None) -> str | None:
        if value is None:
            return None
        return value.strip() or None


class AdminTaxiSanctionRevokeRequest(BaseModel):
    reason: str = Field(..., min_length=1, max_length=300)

    @field_validator("reason")
    @classmethod
    def normalize_reason(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized:
            raise ValueError("revoke reason is empty")
        return normalized


class AdminTaxiReportDetailResponse(AdminTaxiReportSummaryResponse):
    detail: str | None
    admin_note: str | None
    reporter_key: str
    reported_message_id: int | None
    departure_summary: str | None
    messages: list[AdminTaxiReportEvidenceMessage]
    evidence_purged: bool
    other_reports: list[AdminTaxiReportSummaryResponse]
    sanction_id: int | None
    target_sanctions: list[AdminTaxiSanctionResponse]
    suggested_level: AdminTaxiSanctionLevel


class AdminTaxiReportUpdateRequest(BaseModel):
    status: AdminTaxiReportStatus
    admin_note: str | None = Field(default=None, max_length=1000)

    @field_validator("admin_note")
    @classmethod
    def normalize_note(cls, value: str | None) -> str | None:
        if value is None:
            return None
        return value.strip() or None
class AdminShuttleTimetableStation(BaseModel):
    station_id: int
    station_name: str
    stop_order: int


class AdminShuttleTimetableRow(BaseModel):
    number: int
    schedule_id: int
    times: list[str]


class AdminShuttleTimetableRoute(BaseModel):
    route_id: int
    route_name: str
    direction: str
    stations: list[AdminShuttleTimetableStation]
    rows: list[AdminShuttleTimetableRow]
    schedule_count: int


class AdminShuttleTimetableSection(BaseModel):
    anchor_id: str
    schedule_type: str
    schedule_type_name: str
    is_active: bool
    routes: list[AdminShuttleTimetableRoute]
    route_count: int
    schedule_count: int
