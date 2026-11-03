from datetime import datetime

from pydantic import BaseModel


class BusDataRelease(BaseModel):
    version: str
    # 시간표는 서버 상대 경로(/bus-timetable), 노선도는 Storage 절대 URL이다.
    download_url: str
    effective_from: datetime | None = None
    sha256: str | None = None


class BusDataConfig(BaseModel):
    # 게시본이 없으면 null. 앱은 예전 경로(깃허브)로 넘어간다.
    timetable: BusDataRelease | None = None
    static: BusDataRelease | None = None


class BusDataHistoryItem(BaseModel):
    # 앱 설정의 변경이력 한 줄. 이미 적용된 게시본만 나간다.
    version: str
    effective_at: datetime
    note: str | None = None
    # 이전 게시본과 비교한 자동 요약. 최초 등록이면 null
    changes: list[str] | None = None


class AppConfigResponse(BaseModel):
    taxi_enabled: bool
    bus_data: BusDataConfig = BusDataConfig()
