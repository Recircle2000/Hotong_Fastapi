"""Schedule daily taxi retention cleanup.

Revision ID: e2a3b4c5d6e7
Revises: e1f2a3b4c5d6
Create Date: 2026-09-14 00:00:00.000000
"""

from typing import Sequence, Union

from alembic import op


revision: str = "e2a3b4c5d6e7"
down_revision: Union[str, None] = "e1f2a3b4c5d6"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    if op.get_bind().dialect.name != "postgresql":
        return

    op.execute("create extension if not exists pg_cron")
    op.execute(
        """
        do $$
        declare
            existing_job_id bigint;
        begin
            select jobid
              into existing_job_id
              from cron.job
             where jobname = 'cleanup-expired-taxi-data'
             order by jobid
             limit 1;

            if existing_job_id is not null then
                perform cron.unschedule(existing_job_id);
            end if;

            perform cron.schedule(
                'cleanup-expired-taxi-data',
                '10 18 * * *',
                'select public.cleanup_expired_taxi_messages();'
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
        declare
            existing_job_id bigint;
        begin
            for existing_job_id in
                select jobid
                  from cron.job
                 where jobname = 'cleanup-expired-taxi-data'
            loop
                perform cron.unschedule(existing_job_id);
            end loop;
        end;
        $$;
        """
    )
