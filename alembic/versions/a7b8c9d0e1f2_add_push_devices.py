"""Add FCM push device tokens for taxi chat notifications.

Revision ID: a7b8c9d0e1f2
Revises: c3d4e5f6a7b9
Create Date: 2026-10-01 00:00:00.000000
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql


revision: str = "a7b8c9d0e1f2"
down_revision: Union[str, None] = "c3d4e5f6a7b9"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    if op.get_bind().dialect.name != "postgresql":
        return

    op.create_table(
        "push_devices",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("token", sa.String(length=512), nullable=False),
        sa.Column("platform", sa.String(length=20), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.CheckConstraint("platform in ('android', 'ios')", name="ck_push_devices_platform"),
        # 회원 탈퇴로 Supabase 계정이 지워지면 토큰도 함께 지운다.
        sa.ForeignKeyConstraint(["user_id"], ["auth.users.id"], ondelete="CASCADE"),
        sa.UniqueConstraint("token", name="uq_push_devices_token"),
    )
    op.create_index("ix_push_devices_user_id", "push_devices", ["user_id"])
    # 다른 택시 테이블처럼 Supabase 공개 API(PostgREST) 역할에서는 접근할 수 없게 한다.
    op.execute("revoke all on table bus_service.push_devices from public, anon, authenticated")


def downgrade() -> None:
    if op.get_bind().dialect.name != "postgresql":
        return
    op.drop_index("ix_push_devices_user_id", table_name="push_devices")
    op.drop_table("push_devices")
