"""Add taxi party MVP tables and message retention.

Revision ID: c8d3e5f7a9b1
Revises: b7c2d4e6f8a0
Create Date: 2026-09-13 00:00:00.000000
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql


revision: str = "c8d3e5f7a9b1"
down_revision: Union[str, None] = "b7c2d4e6f8a0"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    if op.get_bind().dialect.name != "postgresql":
        return

    op.create_table(
        "taxi_locations",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("name", sa.String(length=80), nullable=False),
        sa.Column("category", sa.String(length=20), server_default="other", nullable=False),
        sa.Column("sort_order", sa.Integer(), server_default="0", nullable=False),
        sa.Column("is_active", sa.Boolean(), server_default=sa.text("true"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.CheckConstraint(
            "category in ('campus', 'station', 'terminal', 'other')",
            name="ck_taxi_locations_category",
        ),
        sa.UniqueConstraint("name", name="uq_taxi_locations_name"),
    )

    op.create_table(
        "taxi_parties",
        sa.Column("id", postgresql.UUID(as_uuid=True), server_default=sa.text("gen_random_uuid()"), primary_key=True),
        sa.Column("client_request_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("owner_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("departure_location_id", sa.Integer(), nullable=False),
        sa.Column("destination_location_id", sa.Integer(), nullable=False),
        sa.Column("departure_summary", sa.String(length=80), nullable=False),
        sa.Column("destination_summary", sa.String(length=80), nullable=True),
        sa.Column("member_note", sa.String(length=500), nullable=True),
        sa.Column("departure_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("max_members", sa.Integer(), nullable=False),
        sa.Column("recruitment_open", sa.Boolean(), server_default=sa.text("true"), nullable=False),
        sa.Column("status", sa.String(length=20), server_default="active", nullable=False),
        sa.Column("cancellation_reason", sa.String(length=200), nullable=True),
        sa.Column("cancelled_by_admin_id", sa.Integer(), nullable=True),
        sa.Column("cancelled_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.CheckConstraint("departure_location_id <> destination_location_id", name="ck_taxi_parties_different_locations"),
        sa.CheckConstraint("max_members between 2 and 4", name="ck_taxi_parties_capacity"),
        sa.CheckConstraint("status in ('active', 'cancelled')", name="ck_taxi_parties_status"),
        sa.ForeignKeyConstraint(["owner_id"], ["auth.users.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["departure_location_id"], ["taxi_locations.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["destination_location_id"], ["taxi_locations.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["cancelled_by_admin_id"], ["users.id"], ondelete="SET NULL"),
        sa.UniqueConstraint("owner_id", "client_request_id", name="uq_taxi_party_owner_request"),
    )
    op.create_index("ix_taxi_parties_owner_id", "taxi_parties", ["owner_id"])
    op.create_index("ix_taxi_parties_departure_location_id", "taxi_parties", ["departure_location_id"])
    op.create_index("ix_taxi_parties_destination_location_id", "taxi_parties", ["destination_location_id"])
    op.create_index("ix_taxi_parties_departure_at", "taxi_parties", ["departure_at"])
    op.create_index(
        "ix_taxi_parties_list",
        "taxi_parties",
        ["departure_at", "departure_location_id", "destination_location_id"],
    )

    op.create_table(
        "taxi_party_members",
        sa.Column("id", sa.BigInteger(), sa.Identity(), primary_key=True),
        sa.Column("party_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("anonymous_number", sa.Integer(), nullable=True),
        sa.Column("joined_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("left_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_read_message_id", sa.BigInteger(), nullable=True),
        sa.CheckConstraint("anonymous_number is null or anonymous_number > 0", name="ck_taxi_party_member_number_positive"),
        sa.ForeignKeyConstraint(["party_id"], ["taxi_parties.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["user_id"], ["auth.users.id"], ondelete="CASCADE"),
        sa.UniqueConstraint("party_id", "user_id", name="uq_taxi_party_member_user"),
        sa.UniqueConstraint("party_id", "anonymous_number", name="uq_taxi_party_member_number"),
    )
    op.create_index("ix_taxi_party_members_party_id", "taxi_party_members", ["party_id"])
    op.create_index("ix_taxi_party_members_user_id", "taxi_party_members", ["user_id"])
    op.create_index("ix_taxi_members_user_active", "taxi_party_members", ["user_id", "left_at"])

    op.create_table(
        "taxi_messages",
        sa.Column("id", sa.BigInteger(), sa.Identity(), primary_key=True),
        sa.Column("party_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("sender_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("message_type", sa.String(length=20), server_default="chat", nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("client_message_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.CheckConstraint("message_type in ('chat', 'system')", name="ck_taxi_messages_type"),
        sa.ForeignKeyConstraint(["party_id"], ["taxi_parties.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["sender_id"], ["auth.users.id"], ondelete="SET NULL"),
        sa.UniqueConstraint("sender_id", "client_message_id", name="uq_taxi_message_sender_client_id"),
    )
    op.create_index("ix_taxi_messages_party_id", "taxi_messages", ["party_id"])
    op.create_index("ix_taxi_messages_sender_id", "taxi_messages", ["sender_id"])
    op.create_index("ix_taxi_messages_created_at", "taxi_messages", ["created_at"])
    op.create_index("ix_taxi_messages_party_cursor", "taxi_messages", ["party_id", "id"])

    op.execute(
        """
        create or replace function public.cleanup_expired_taxi_messages()
        returns bigint
        language plpgsql
        security invoker
        set search_path = ''
        as $$
        declare
            deleted_count bigint;
        begin
            delete from bus_service.taxi_messages message
             using bus_service.taxi_parties party
             where message.party_id = party.id
               and party.departure_at < now() - interval '30 days';
            get diagnostics deleted_count = row_count;
            return deleted_count;
        end;
        $$;
        revoke execute on function public.cleanup_expired_taxi_messages()
        from public, anon, authenticated;
        """
    )

    for table_name in (
        "taxi_locations",
        "taxi_parties",
        "taxi_party_members",
        "taxi_messages",
    ):
        op.execute(
            f"revoke all on table bus_service.{table_name} from public, anon, authenticated"
        )


def downgrade() -> None:
    if op.get_bind().dialect.name != "postgresql":
        return

    op.execute("drop function if exists public.cleanup_expired_taxi_messages()")
    op.drop_table("taxi_messages")
    op.drop_table("taxi_party_members")
    op.drop_table("taxi_parties")
    op.drop_table("taxi_locations")
