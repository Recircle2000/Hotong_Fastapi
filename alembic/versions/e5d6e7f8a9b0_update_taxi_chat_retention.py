"""Update taxi chat retention and daily cleanup.

Revision ID: e5d6e7f8a9b0
Revises: e4c5d6e7f8a9
Create Date: 2026-09-18 00:00:00.000000
"""

from typing import Sequence, Union

from alembic import op


revision: str = "e5d6e7f8a9b0"
down_revision: Union[str, None] = "e4c5d6e7f8a9"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    if op.get_bind().dialect.name != "postgresql":
        return
    op.execute("drop function if exists public.cleanup_expired_taxi_messages()")
    op.execute(
        """
        create or replace procedure public.cleanup_expired_taxi_messages()
        language plpgsql
        security invoker
        as $$
        declare
            batch_count integer;
            lock_key constant bigint := 8097214582104;
        begin
            if not pg_catalog.pg_try_advisory_lock(lock_key) then
                return;
            end if;
            loop
                with expired as (
                    select message.id
                      from bus_service.taxi_messages message
                      join bus_service.taxi_parties party on party.id = message.party_id
                     where case
                         when party.status = 'cancelled' and party.cancelled_at is not null
                           then party.cancelled_at <= pg_catalog.now() - interval '48 hours'
                         else party.departure_at <= pg_catalog.now() - interval '48 hours'
                     end
                     order by message.id
                     limit 1000
                     for update of message skip locked
                )
                delete from bus_service.taxi_messages message
                 using expired
                 where message.id = expired.id;
                get diagnostics batch_count = row_count;
                commit;
                exit when batch_count < 1000;
            end loop;
            update bus_service.taxi_parties
               set meeting_code = null
             where meeting_code is not null
               and departure_at <= pg_catalog.now() - interval '30 days';
            commit;
            perform pg_catalog.pg_advisory_unlock(lock_key);
        end;
        $$;
        revoke execute on procedure public.cleanup_expired_taxi_messages()
        from public, anon, authenticated;
        """
    )
    op.execute(
        """
        do $$
        declare job_id bigint;
        begin
            for job_id in select jobid from cron.job where jobname = 'cleanup-expired-taxi-data'
            loop
                perform cron.unschedule(job_id);
            end loop;
            perform cron.schedule(
                'cleanup-expired-taxi-data',
                '0 19 * * *',
                'call public.cleanup_expired_taxi_messages();'
            );
        end;
        $$;
        """
    )


def downgrade() -> None:
    if op.get_bind().dialect.name != "postgresql":
        return
    op.execute(
        """
        do $$
        declare job_id bigint;
        begin
            for job_id in select jobid from cron.job where jobname = 'cleanup-expired-taxi-data'
            loop
                perform cron.unschedule(job_id);
            end loop;
        end;
        $$;
        """
    )
    op.execute("drop procedure if exists public.cleanup_expired_taxi_messages()")
