"""Add taxi sanctions (warning, suspensions) linked from reports.

Revision ID: b2c3d4e5f6a8
Revises: a1b2c3d4e5f7
Create Date: 2026-09-30 18:00:00.000000
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql


revision: str = "b2c3d4e5f6a8"
down_revision: Union[str, None] = "a1b2c3d4e5f7"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    if op.get_bind().dialect.name != "postgresql":
        return

    op.create_table(
        "taxi_sanctions",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("level", sa.String(length=20), nullable=False),
        sa.Column("reason", sa.String(length=300), nullable=False),
        sa.Column("admin_note", sa.Text(), nullable=True),
        sa.Column("starts_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("ends_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_by_admin_id", sa.Integer(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("acknowledged_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("revoked_by_admin_id", sa.Integer(), nullable=True),
        sa.Column("revoke_reason", sa.String(length=300), nullable=True),
        sa.ForeignKeyConstraint(["created_by_admin_id"], ["users.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["revoked_by_admin_id"], ["users.id"], ondelete="SET NULL"),
        sa.CheckConstraint(
            "level in ('warning', 'suspend_3d', 'suspend_7d', 'permanent')",
            name="ck_taxi_sanctions_level",
        ),
    )
    op.create_index("ix_taxi_sanctions_user_id", "taxi_sanctions", ["user_id"])
    # 다른 택시 테이블처럼 Supabase 공개 API(PostgREST) 역할에서는 접근할 수 없게 한다.
    op.execute("revoke all on table bus_service.taxi_sanctions from public, anon, authenticated")

    op.add_column("taxi_reports", sa.Column("sanction_id", sa.Integer(), nullable=True))
    op.create_foreign_key(
        "fk_taxi_reports_sanction_id",
        "taxi_reports",
        "taxi_sanctions",
        ["sanction_id"],
        ["id"],
        ondelete="SET NULL",
    )


def downgrade() -> None:
    if op.get_bind().dialect.name != "postgresql":
        return
    op.drop_constraint("fk_taxi_reports_sanction_id", "taxi_reports", type_="foreignkey")
    op.drop_column("taxi_reports", "sanction_id")
    op.drop_table("taxi_sanctions")
