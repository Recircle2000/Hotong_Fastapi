"""Purge taxi parties and sanctions after a year; keep suspensions across account deletion.

Revision ID: c3d4e5f6a7b9
Revises: b2c3d4e5f6a8
Create Date: 2026-09-30 23:00:00.000000
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op


revision: str = "c3d4e5f6a7b9"
down_revision: Union[str, None] = "b2c3d4e5f6a8"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    if op.get_bind().dialect.name != "postgresql":
        return

    op.create_table(
        "taxi_sanction_holds",
        sa.Column("email_hash", sa.String(length=64), primary_key=True),
        sa.Column("level", sa.String(length=20), nullable=False),
        sa.Column("reason", sa.String(length=300), nullable=False),
        sa.Column("ends_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    # 다른 택시 테이블처럼 Supabase 공개 API(PostgREST) 역할에서는 접근할 수 없게 한다.
    op.execute("revoke all on table bus_service.taxi_sanction_holds from public, anon, authenticated")

    # 개인정보처리방침의 보관 기간: 팟 기록은 출발(취소) 후 1년, 제재 기록은 종료 후 1년.
    # 철회되지 않은 영구 정지와 아직 끝나지 않은 탈퇴자 정지는 남긴다.
    op.execute(
        """
        create or replace procedure public.purge_expired_taxi_records()
        language plpgsql
        security invoker
        as $$
        declare
            batch_count integer;
            lock_key constant bigint := 8097214582105;
        begin
            if not pg_catalog.pg_try_advisory_lock(lock_key) then
                return;
            end if;
            loop
                with expired as (
                    select party.id
                      from bus_service.taxi_parties party
                     where coalesce(party.cancelled_at, party.departure_at)
                           <= pg_catalog.now() - interval '1 year'
                     order by party.departure_at
                     limit 1000
                     for update skip locked
                )
                delete from bus_service.taxi_parties party
                 using expired
                 where party.id = expired.id;
                get diagnostics batch_count = row_count;
                commit;
                exit when batch_count < 1000;
            end loop;

            delete from bus_service.taxi_sanctions
             where revoked_at <= pg_catalog.now() - interval '1 year'
                or (level = 'warning' and created_at <= pg_catalog.now() - interval '1 year')
                or (ends_at is not null and ends_at <= pg_catalog.now() - interval '1 year');
            delete from bus_service.taxi_sanction_holds
             where ends_at is not null and ends_at <= pg_catalog.now();
            commit;
            perform pg_catalog.pg_advisory_unlock(lock_key);
        end;
        $$;
        revoke execute on procedure public.purge_expired_taxi_records()
        from public, anon, authenticated;
        """
    )
    op.execute(
        """
        do $$
        declare job_id bigint;
        begin
            for job_id in select jobid from cron.job where jobname = 'purge-taxi-records'
            loop
                perform cron.unschedule(job_id);
            end loop;
            perform cron.schedule(
                'purge-taxi-records',
                '20 19 * * *',
                'call public.purge_expired_taxi_records();'
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
            for job_id in select jobid from cron.job where jobname = 'purge-taxi-records'
            loop
                perform cron.unschedule(job_id);
            end loop;
        end;
        $$;
        """
    )
    op.execute("drop procedure if exists public.purge_expired_taxi_records()")
    op.drop_table("taxi_sanction_holds")
