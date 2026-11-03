from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import JSON, Column, DateTime, Integer, String, Text, UniqueConstraint

from models import Base


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


class CityBusRoute(Base):
    """대시보드에서 편집 중인 시내버스 노선 초안. 게시하기 전까지 앱에는 나가지 않는다."""

    __tablename__ = "city_bus_routes"

    route_key = Column(String(32), primary_key=True)  # 예: 810_UP, 순환5_DOWN
    sort_order = Column(Integer, nullable=False, default=0)
    origin = Column(String(100), nullable=False, default="")  # 시간표 JSON의 "출발지"
    terminus = Column(String(100), nullable=False, default="")  # 시간표 JSON의 "종점"
    times = Column(JSON, nullable=False, default=list)  # ["06:50", ...]
    route_geojson = Column(JSON, nullable=True)  # 노선 선형 FeatureCollection
    stops_json = Column(JSON, nullable=True)  # 공공데이터 정류장 조회 응답 원문
    # 목록 화면이 큰 JSON을 읽지 않도록 업로드할 때 개수를 따로 적어 둔다.
    geojson_feature_count = Column(Integer, nullable=False, default=0)
    stop_count = Column(Integer, nullable=False, default=0)
    updated_at = Column(DateTime(timezone=True), nullable=False, default=utc_now, onupdate=utc_now)
    updated_by_admin_id = Column(Integer, nullable=True)


class CityBusRelease(Base):
    """앱에 내려가는 게시본. 한 번 만들면 고치지 않고 새 버전을 쌓는다."""

    __tablename__ = "city_bus_releases"
    __table_args__ = (UniqueConstraint("kind", "version", name="uq_city_bus_releases_kind_version"),)

    id = Column(Integer, primary_key=True, autoincrement=True)
    kind = Column(String(16), nullable=False, index=True)  # timetable | static
    version = Column(String(32), nullable=False)
    # 이 시각부터 앱에 내려간다. 비어 있으면 게시 즉시 적용한다.
    effective_from = Column(DateTime(timezone=True), nullable=True)
    # 시간표는 앱이 받는 JSON 전체를 담는다. 노선도는 Storage 파일로 내려가므로 비운다.
    payload = Column(JSON, nullable=True)
    download_url = Column(Text, nullable=True)
    sha256 = Column(String(64), nullable=True)
    size_bytes = Column(Integer, nullable=True)
    published_at = Column(DateTime(timezone=True), nullable=False, default=utc_now)
    published_by_admin_id = Column(Integer, nullable=True)
    # 앱 설정의 변경이력에 나간다. note는 관리자가 쓴 한 줄, changes는 이전 게시본과 비교한 자동 요약.
    note = Column(Text, nullable=True)
    changes = Column(JSON, nullable=True)  # ["810 상행: 07:10 추가", ...], 비교할 이전 게시본이 없으면 null
    # 노선도 게시본만: {route_key: {"geojson": sha256, "stops": sha256}}. 다음 게시 때 비교에 쓴다.
    route_hashes = Column(JSON, nullable=True)
