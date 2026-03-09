"""Add emergency_notices table

Revision ID: c1f8d9a4b2e7
Revises: 62607c543e63
Create Date: 2026-02-16 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "c1f8d9a4b2e7"
down_revision: Union[str, None] = "62607c543e63"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "emergency_notices",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column(
            "category",
            sa.Enum(
                "shuttle",
                "asan_citybus",
                "cheonan_citybus",
                "subway",
                name="emergencynoticecategory",
            ),
            nullable=False,
        ),
        sa.Column("title", sa.String(length=255), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("end_at", sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        op.f("ix_emergency_notices_category"),
        "emergency_notices",
        ["category"],
        unique=False,
    )
    op.create_index(
        op.f("ix_emergency_notices_end_at"),
        "emergency_notices",
        ["end_at"],
        unique=False,
    )
    op.create_index(
        op.f("ix_emergency_notices_id"),
        "emergency_notices",
        ["id"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(op.f("ix_emergency_notices_id"), table_name="emergency_notices")
    op.drop_index(op.f("ix_emergency_notices_end_at"), table_name="emergency_notices")
    op.drop_index(op.f("ix_emergency_notices_category"), table_name="emergency_notices")
    op.drop_table("emergency_notices")
