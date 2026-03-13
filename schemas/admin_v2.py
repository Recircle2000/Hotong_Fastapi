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
