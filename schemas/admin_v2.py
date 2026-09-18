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


class AdminTaxiPartyCancelRequest(BaseModel):
    reason: str = Field(..., min_length=1, max_length=200)

    @field_validator("reason")
    @classmethod
    def normalize_reason(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized:
            raise ValueError("cancellation reason is empty")
        return normalized
