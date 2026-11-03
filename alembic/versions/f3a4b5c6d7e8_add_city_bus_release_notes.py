"""Add admin note, change summary and per-route hashes to city bus releases.

Revision ID: f3a4b5c6d7e8
Revises: d0e1f2a3b4c5
Create Date: 2026-11-04 12:00:00.000000
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op


revision: str = "f3a4b5c6d7e8"
down_revision: Union[str, None] = "d0e1f2a3b4c5"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    if op.get_bind().dialect.name != "postgresql":
        return
    op.add_column("city_bus_releases", sa.Column("note", sa.Text(), nullable=True))
    op.add_column("city_bus_releases", sa.Column("changes", sa.JSON(), nullable=True))
    op.add_column("city_bus_releases", sa.Column("route_hashes", sa.JSON(), nullable=True))


def downgrade() -> None:
    if op.get_bind().dialect.name != "postgresql":
        return
    op.drop_column("city_bus_releases", "route_hashes")
    op.drop_column("city_bus_releases", "changes")
    op.drop_column("city_bus_releases", "note")
