"""Add description column to shuttle_routes

Revision ID: 8d7d3f2b4c1a
Revises: c1f8d9a4b2e7
Create Date: 2026-03-09 20:05:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "8d7d3f2b4c1a"
down_revision: Union[str, None] = "c1f8d9a4b2e7"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "shuttle_routes",
        sa.Column("description", sa.String(length=500), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("shuttle_routes", "description")
