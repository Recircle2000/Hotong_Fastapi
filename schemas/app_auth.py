from uuid import UUID

from pydantic import BaseModel


class CurrentAppUser(BaseModel):
    user_id: UUID


class AppAuthMeResponse(BaseModel):
    user_id: UUID
