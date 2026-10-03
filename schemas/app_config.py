from pydantic import BaseModel


class AppConfigResponse(BaseModel):
    taxi_enabled: bool
