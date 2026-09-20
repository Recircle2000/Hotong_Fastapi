from datetime import datetime

from pydantic import BaseModel, Field


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
