from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, Field, field_validator


TaxiLocationCategory = Literal["campus", "station", "terminal", "other"]
TaxiPartyStatus = Literal[
    "recruiting",
    "full",
    "closed",
    "in_progress",
    "completed",
    "cancelled",
]
TaxiRecruitmentStatus = Literal["recruiting", "full", "closed", "ended", "cancelled"]
TaxiChatStatus = Literal["writable", "read_only", "expired"]


class TaxiLocationResponse(BaseModel):
    id: int
    name: str
    category: TaxiLocationCategory
    sort_order: int
    is_active: bool


class TaxiPartyCreateRequest(BaseModel):
    client_request_id: UUID
    departure_location_id: int
    destination_location_id: int
    departure_summary: str = Field(..., min_length=1, max_length=80)
    destination_summary: str | None = Field(default=None, max_length=80)
    member_note: str | None = Field(default=None, max_length=500)
    departure_at: datetime
    max_members: int = Field(..., ge=2, le=4)

    @field_validator("departure_summary")
    @classmethod
    def normalize_required_text(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized:
            raise ValueError("departure summary is empty")
        return normalized

    @field_validator("destination_summary", "member_note")
    @classmethod
    def normalize_optional_text(cls, value: str | None) -> str | None:
        if value is None:
            return None
        return value.strip() or None


class TaxiPartyUpdateRequest(BaseModel):
    departure_location_id: int | None = None
    destination_location_id: int | None = None
    departure_summary: str | None = Field(default=None, min_length=1, max_length=80)
    destination_summary: str | None = Field(default=None, max_length=80)
    member_note: str | None = Field(default=None, max_length=500)
    departure_at: datetime | None = None
    max_members: int | None = Field(default=None, ge=2, le=4)

    @field_validator("departure_summary", "destination_summary", "member_note")
    @classmethod
    def normalize_text(cls, value: str | None) -> str | None:
        if value is None:
            return None
        normalized = value.strip()
        return normalized or None


class TaxiRecruitmentRequest(BaseModel):
    is_open: bool


class TaxiPartyCancelRequest(BaseModel):
    reason: str | None = Field(default=None, max_length=200)

    @field_validator("reason")
    @classmethod
    def normalize_reason(cls, value: str | None) -> str | None:
        if value is None:
            return None
        normalized = value.strip()
        return normalized or None


class TaxiMemberResponse(BaseModel):
    label: str
    is_owner: bool
    is_me: bool
    joined_at: datetime


class TaxiPartySummaryResponse(BaseModel):
    id: UUID
    meeting_code: str | None
    departure_location: TaxiLocationResponse
    destination_location: TaxiLocationResponse
    departure_summary: str
    destination_summary: str | None
    departure_at: datetime
    max_members: int
    current_members: int
    remaining_seats: int
    status: TaxiPartyStatus
    recruitment_status: TaxiRecruitmentStatus
    chat_status: TaxiChatStatus
    chat_writable_until: datetime
    chat_visible_until: datetime
    is_owner: bool
    is_member: bool
    unread_count: int


class TaxiPartyDetailResponse(TaxiPartySummaryResponse):
    member_note: str | None
    members: list[TaxiMemberResponse]
    cancellation_reason: str | None
    created_at: datetime


class TaxiPartyListResponse(BaseModel):
    items: list[TaxiPartySummaryResponse]
    next_cursor: str | None = None


class TaxiMessageResponse(BaseModel):
    id: int
    party_id: UUID
    message_type: Literal["chat", "system"]
    sender_label: str | None
    is_mine: bool
    content: str
    created_at: datetime
    # 보낸 사람 본인에게만 채워 준다. 앱이 전송 중인 메시지와 짝짓는 데 쓴다.
    client_message_id: UUID | None = None


class TaxiMessageListResponse(BaseModel):
    items: list[TaxiMessageResponse]
    next_before_id: int | None = None


class TaxiMessageSendEvent(BaseModel):
    type: Literal["message.send"]
    party_id: UUID
    client_message_id: UUID
    content: str = Field(..., min_length=1, max_length=500)

    @field_validator("content")
    @classmethod
    def normalize_content(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized:
            raise ValueError("message content is empty")
        return normalized


class TaxiReadRequest(BaseModel):
    last_message_id: int = Field(..., gt=0)


class TaxiReadResponse(BaseModel):
    success: bool = True


class TaxiActionResponse(BaseModel):
    success: bool = True


class TaxiPushTokenRequest(BaseModel):
    token: str = Field(..., min_length=1, max_length=512)
    platform: Literal["android", "ios"]


class TaxiPushTokenDeleteRequest(BaseModel):
    token: str = Field(..., min_length=1, max_length=512)


TaxiReportReason = Literal["no_show", "abuse", "payment", "other"]


class TaxiReportCreateRequest(BaseModel):
    target_label: str = Field(..., min_length=1, max_length=20)
    reason: TaxiReportReason
    detail: str | None = Field(default=None, max_length=500)
    message_id: int | None = None

    @field_validator("target_label")
    @classmethod
    def normalize_label(cls, value: str) -> str:
        return value.strip()

    @field_validator("detail")
    @classmethod
    def normalize_detail(cls, value: str | None) -> str | None:
        if value is None:
            return None
        return value.strip() or None


class TaxiReportResponse(BaseModel):
    id: int
    created_at: datetime


TaxiSanctionLevel = Literal["warning", "suspend_3d", "suspend_7d", "permanent"]


class TaxiSanctionResponse(BaseModel):
    id: int
    level: TaxiSanctionLevel
    reason: str
    starts_at: datetime
    ends_at: datetime | None


class TaxiRestrictionResponse(BaseModel):
    # 이의제기 때 알려줄 내 고유번호(관리자 화면의 익명 ID와 같다)
    user_key: str
    # 지금 적용 중인 정지
    suspension: TaxiSanctionResponse | None = None
    # 아직 확인하지 않은 제재 안내(경고 포함)
    notice: TaxiSanctionResponse | None = None


class TaxiHomeResponse(BaseModel):
    """택시 화면에 들어오거나 돌아올 때 필요한 데이터를 한 번에 내려준다."""

    # 요청한 경우에만 채운다(앱이 잠시 재사용한다).
    locations: list[TaxiLocationResponse] | None = None
    parties: TaxiPartyListResponse
    # 출발 전인 내 팟. 현재팟 화면이 바로 그릴 수 있게 참여자 목록까지 담는다.
    my_parties: list[TaxiPartyDetailResponse]
    recent_chats: list[TaxiPartySummaryResponse]
    # 요청한 경우에만 채운다(내정보 탭).
    history: list[TaxiPartySummaryResponse] | None = None
    restriction: TaxiRestrictionResponse
