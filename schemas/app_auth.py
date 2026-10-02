from uuid import UUID

from pydantic import BaseModel, Field


class CurrentAppUser(BaseModel):
    user_id: UUID


class AppAuthMeResponse(BaseModel):
    user_id: UUID


class ReviewOtpRequest(BaseModel):
    email: str = Field(..., max_length=254)
    code: str = Field(..., max_length=64)


class ReviewOtpResponse(BaseModel):
    otp: str
