"""Seed the initial administrator-editable taxi locations.

Revision ID: d9e4f6a8b0c2
Revises: c8d3e5f7a9b1
Create Date: 2026-09-13 00:00:00.000000
"""

from typing import Sequence, Union

from alembic import op


revision: str = "d9e4f6a8b0c2"
down_revision: Union[str, None] = "c8d3e5f7a9b1"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    if op.get_bind().dialect.name != "postgresql":
        return

    op.execute(
        """
        insert into bus_service.taxi_locations
            (name, category, sort_order, is_active)
        values
            ('아산캠퍼스', 'campus', 10, true),
            ('천안캠퍼스', 'campus', 20, true),
            ('천안아산역', 'station', 30, true),
            ('두정역', 'station', 40, true),
            ('천안터미널', 'terminal', 50, true),
            ('천안역', 'station', 60, true)
        on conflict (name) do nothing;
        """
    )


def downgrade() -> None:
    if op.get_bind().dialect.name != "postgresql":
        return

    op.execute(
        """
        delete from bus_service.taxi_locations location
         where location.name in (
            '아산캠퍼스', '천안캠퍼스', '천안아산역',
            '두정역', '천안터미널', '천안역'
         )
           and not exists (
               select 1
                 from bus_service.taxi_parties party
                where party.departure_location_id = location.id
                   or party.destination_location_id = location.id
           );
        """
    )
