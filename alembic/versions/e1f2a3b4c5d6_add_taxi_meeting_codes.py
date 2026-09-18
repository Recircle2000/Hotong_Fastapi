"""Add reusable four-character taxi party meeting codes.

Revision ID: e1f2a3b4c5d6
Revises: d9e4f6a8b0c2
Create Date: 2026-09-14 00:00:00.000000
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op


revision: str = "e1f2a3b4c5d6"
down_revision: Union[str, None] = "d9e4f6a8b0c2"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    if op.get_bind().dialect.name != "postgresql":
        return

    op.add_column(
        "taxi_parties",
        sa.Column("meeting_code", sa.String(length=4), nullable=True),
        schema="bus_service",
    )
    op.create_check_constraint(
        "ck_taxi_parties_meeting_code",
        "taxi_parties",
        "meeting_code is null or meeting_code ~ '^[2-9A-HJ-NP-Z]{4}$'",
        schema="bus_service",
    )
    op.create_unique_constraint(
        "uq_taxi_parties_meeting_code",
        "taxi_parties",
        ["meeting_code"],
        schema="bus_service",
    )
    op.execute(
        """
        do $$
        declare
            party_row record;
            alphabet constant text := '23456789ABCDEFGHJKLMNPQRSTUVWXYZ';
            candidate text;
            attempts integer;
            position integer;
        begin
            for party_row in
                select id
                  from bus_service.taxi_parties
                 where meeting_code is null
                   and departure_at > now() - interval '30 days'
                 order by created_at, id
            loop
                attempts := 0;
                loop
                    attempts := attempts + 1;
                    if attempts > 100 then
                        raise exception 'Unable to backfill a unique taxi meeting code';
                    end if;
                    candidate := '';
                    for position in 1..4 loop
                        candidate := candidate || substr(
                            alphabet,
                            floor(random() * length(alphabet))::integer + 1,
                            1
                        );
                    end loop;
                    begin
                        update bus_service.taxi_parties
                           set meeting_code = candidate
                         where id = party_row.id;
                        exit;
                    exception when unique_violation then
                        null;
                    end;
                end loop;
            end loop;
        end;
        $$;
        """
    )
    _replace_cleanup_function(release_codes=True)


def downgrade() -> None:
    if op.get_bind().dialect.name != "postgresql":
        return

    _replace_cleanup_function(release_codes=False)
    op.drop_constraint(
        "uq_taxi_parties_meeting_code",
        "taxi_parties",
        schema="bus_service",
        type_="unique",
    )
    op.drop_constraint(
        "ck_taxi_parties_meeting_code",
        "taxi_parties",
        schema="bus_service",
        type_="check",
    )
    op.drop_column("taxi_parties", "meeting_code", schema="bus_service")


def _replace_cleanup_function(*, release_codes: bool) -> None:
    release_sql = """
            update bus_service.taxi_parties
               set meeting_code = null
             where meeting_code is not null
               and departure_at <= now() - interval '30 days';
    """ if release_codes else ""
    op.execute(
        f"""
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
               and party.departure_at <= now() - interval '30 days';
            get diagnostics deleted_count = row_count;
            {release_sql}
            return deleted_count;
        end;
        $$;
        revoke execute on function public.cleanup_expired_taxi_messages()
        from public, anon, authenticated;
        """
    )
