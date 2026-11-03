"""Store city bus map feature/stop counts so route lists skip the large JSON columns.

Revision ID: d0e1f2a3b4c5
Revises: c9d0e1f2a3b4
Create Date: 2026-11-04 01:00:00.000000
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op


revision: str = "d0e1f2a3b4c5"
down_revision: Union[str, None] = "c9d0e1f2a3b4"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    if op.get_bind().dialect.name != "postgresql":
        return

    op.add_column(
        "city_bus_routes",
        sa.Column("geojson_feature_count", sa.Integer(), nullable=False, server_default="0"),
    )
    op.add_column(
        "city_bus_routes",
        sa.Column("stop_count", sa.Integer(), nullable=False, server_default="0"),
    )
    # 이미 올라간 노선은 원본에서 개수를 채운다. 정류장 응답은 item이 배열이거나 한 건이면 객체다.
    op.execute(
        """
        update city_bus_routes set
            geojson_feature_count = case
                when json_typeof(route_geojson -> 'features') = 'array'
                    then json_array_length(route_geojson -> 'features')
                else 0
            end,
            stop_count = case
                when json_typeof(stops_json -> 'response' -> 'body' -> 'items' -> 'item') = 'array'
                    then json_array_length(stops_json -> 'response' -> 'body' -> 'items' -> 'item')
                when json_typeof(stops_json -> 'response' -> 'body' -> 'items' -> 'item') = 'object'
                    then 1
                when json_typeof(stops_json -> 'response' -> 'body' -> 'items') = 'array'
                    then json_array_length(stops_json -> 'response' -> 'body' -> 'items')
                else 0
            end
        """
    )


def downgrade() -> None:
    if op.get_bind().dialect.name != "postgresql":
        return
    op.drop_column("city_bus_routes", "stop_count")
    op.drop_column("city_bus_routes", "geojson_feature_count")
