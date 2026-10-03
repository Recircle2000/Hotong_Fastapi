"""Record taxi terms agreements and blocks between members.

Revision ID: f8a9b0c1d2e3
Revises: e7f8a9b0c1d2
Create Date: 2026-10-03 12:00:00.000000
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op


revision: str = "f8a9b0c1d2e3"
down_revision: Union[str, None] = "e7f8a9b0c1d2"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    if op.get_bind().dialect.name != "postgresql":
        return

    op.create_table(
        "taxi_terms_agreements",
        sa.Column("user_id", sa.Uuid(), primary_key=True),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("agreed_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        # 탈퇴하면 동의 기록도 함께 지운다.
        sa.ForeignKeyConstraint(["user_id"], ["auth.users.id"], ondelete="CASCADE"),
    )

    op.create_table(
        "taxi_blocks",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("blocker_id", sa.Uuid(), nullable=False),
        sa.Column("blocked_id", sa.Uuid(), nullable=False),
        sa.Column("party_id", sa.Uuid(), nullable=True),
        sa.Column("target_label", sa.String(length=20), nullable=False),
        sa.Column("departure_name", sa.String(length=80), nullable=False),
        sa.Column("destination_name", sa.String(length=80), nullable=False),
        sa.Column("departure_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        # 어느 쪽이든 탈퇴하면 차단 기록을 지운다.
        sa.ForeignKeyConstraint(["blocker_id"], ["auth.users.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["blocked_id"], ["auth.users.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["party_id"], ["taxi_parties.id"], ondelete="SET NULL"),
        sa.UniqueConstraint("blocker_id", "blocked_id", name="uq_taxi_blocks_pair"),
    )
    op.create_index("ix_taxi_blocks_blocker_id", "taxi_blocks", ["blocker_id"])
    op.create_index("ix_taxi_blocks_blocked_id", "taxi_blocks", ["blocked_id"])

    # 다른 택시 테이블처럼 Supabase 공개 API(PostgREST) 역할에서는 접근할 수 없게 한다.
    op.execute("revoke all on table bus_service.taxi_terms_agreements from public, anon, authenticated")
    op.execute("revoke all on table bus_service.taxi_blocks from public, anon, authenticated")


def downgrade() -> None:
    if op.get_bind().dialect.name != "postgresql":
        return
    op.drop_index("ix_taxi_blocks_blocked_id", table_name="taxi_blocks")
    op.drop_index("ix_taxi_blocks_blocker_id", table_name="taxi_blocks")
    op.drop_table("taxi_blocks")
    op.drop_table("taxi_terms_agreements")
