"""Add city bus timetable/route drafts and releases, and the public bus-data bucket.

Revision ID: c9d0e1f2a3b4
Revises: f8a9b0c1d2e3
Create Date: 2026-11-04 00:00:00.000000
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql


revision: str = "c9d0e1f2a3b4"
down_revision: Union[str, None] = "f8a9b0c1d2e3"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    if op.get_bind().dialect.name != "postgresql":
        return

    op.create_table(
        "city_bus_routes",
        sa.Column("route_key", sa.String(length=32), primary_key=True),
        sa.Column("sort_order", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("origin", sa.String(length=100), nullable=False, server_default=""),
        sa.Column("terminus", sa.String(length=100), nullable=False, server_default=""),
        sa.Column("times", postgresql.JSON(), nullable=False, server_default=sa.text("'[]'::json")),
        sa.Column("route_geojson", postgresql.JSON(), nullable=True),
        sa.Column("stops_json", postgresql.JSON(), nullable=True),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_by_admin_id", sa.Integer(), nullable=True),
    )
    op.create_table(
        "city_bus_releases",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("kind", sa.String(length=16), nullable=False),
        sa.Column("version", sa.String(length=32), nullable=False),
        sa.Column("effective_from", sa.DateTime(timezone=True), nullable=True),
        sa.Column("payload", postgresql.JSON(), nullable=True),
        sa.Column("download_url", sa.Text(), nullable=True),
        sa.Column("sha256", sa.String(length=64), nullable=True),
        sa.Column("size_bytes", sa.Integer(), nullable=True),
        sa.Column("published_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("published_by_admin_id", sa.Integer(), nullable=True),
        sa.UniqueConstraint("kind", "version", name="uq_city_bus_releases_kind_version"),
    )
    op.create_index("ix_city_bus_releases_kind", "city_bus_releases", ["kind"])
    # 다른 운영 테이블처럼 Supabase 공개 API(PostgREST) 역할에서는 접근할 수 없게 한다.
    op.execute("revoke all on table bus_service.city_bus_routes from public, anon, authenticated")
    op.execute("revoke all on table bus_service.city_bus_releases from public, anon, authenticated")

    # 앱이 노선도 파일을 받아 가는 공개 버킷. 업로드는 서버가 서비스 롤 키로만 한다.
    op.execute(
        """
        insert into storage.buckets (id, name, public)
        values ('bus-data', 'bus-data', true)
        on conflict (id) do nothing
        """
    )


def downgrade() -> None:
    if op.get_bind().dialect.name != "postgresql":
        return
    # 버킷 안의 파일은 앱이 받아 가는 중일 수 있어 버킷은 지우지 않는다.
    op.drop_index("ix_city_bus_releases_kind", table_name="city_bus_releases")
    op.drop_table("city_bus_releases")
    op.drop_table("city_bus_routes")
