"""Add app settings for runtime feature switches (taxi on/off).

Revision ID: f6a7b8c9d0e1
Revises: e5d6e7f8a9b0
Create Date: 2026-09-30 00:00:00.000000
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op


revision: str = "f6a7b8c9d0e1"
down_revision: Union[str, None] = "e5d6e7f8a9b0"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    if op.get_bind().dialect.name != "postgresql":
        return

    op.create_table(
        "app_settings",
        sa.Column("key", sa.String(length=64), primary_key=True),
        sa.Column("value", sa.Text(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_by_admin_id", sa.Integer(), nullable=True),
    )
    # 다른 택시 테이블처럼 Supabase 공개 API(PostgREST) 역할에서는 접근할 수 없게 한다.
    op.execute("revoke all on table bus_service.app_settings from public, anon, authenticated")


def downgrade() -> None:
    if op.get_bind().dialect.name != "postgresql":
        return
    op.drop_table("app_settings")
