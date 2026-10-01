"""Add taxi member reports with chat evidence and yearly evidence cleanup.

Revision ID: a1b2c3d4e5f7
Revises: f6a7b8c9d0e1
Create Date: 2026-09-30 12:00:00.000000
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql


revision: str = "a1b2c3d4e5f7"
down_revision: Union[str, None] = "f6a7b8c9d0e1"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    if op.get_bind().dialect.name != "postgresql":
        return

    op.create_table(
        "taxi_reports",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("party_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("reporter_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("target_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("target_label", sa.String(length=20), nullable=False),
        sa.Column("reason", sa.String(length=20), nullable=False),
        sa.Column("detail", sa.String(length=500), nullable=True),
        sa.Column("message_id", sa.Integer(), nullable=True),
        sa.Column("evidence", postgresql.JSONB(), nullable=True),
        sa.Column("status", sa.String(length=20), server_default="pending", nullable=False),
        sa.Column("admin_note", sa.Text(), nullable=True),
        sa.Column("reviewed_by_admin_id", sa.Integer(), nullable=True),
        sa.Column("reviewed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("evidence_purged_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(["party_id"], ["taxi_parties.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["reviewed_by_admin_id"], ["users.id"], ondelete="SET NULL"),
        sa.UniqueConstraint("party_id", "reporter_id", "target_id", name="uq_taxi_reports_once_per_target"),
        sa.CheckConstraint(
            "reason in ('no_show', 'abuse', 'payment', 'other')",
            name="ck_taxi_reports_reason",
        ),
        sa.CheckConstraint(
            "status in ('pending', 'resolved', 'dismissed')",
            name="ck_taxi_reports_status",
        ),
    )
    op.create_index("ix_taxi_reports_reporter_id", "taxi_reports", ["reporter_id"])
    op.create_index("ix_taxi_reports_target_id", "taxi_reports", ["target_id"])
    op.create_index("ix_taxi_reports_status_created", "taxi_reports", ["status", "created_at"])
    # 다른 택시 테이블처럼 Supabase 공개 API(PostgREST) 역할에서는 접근할 수 없게 한다.
    op.execute("revoke all on table bus_service.taxi_reports from public, anon, authenticated")

    # 처리·기각 후 1년이 지난 신고는 증거 채팅과 상세 내용을 지운다.
    # 행은 남겨 누적 신고 횟수 집계에 계속 쓴다.
    op.execute(
        """
        create or replace procedure public.purge_expired_taxi_report_evidence()
        language plpgsql
        security invoker
        as $$
        begin
            update bus_service.taxi_reports
               set evidence = null,
                   detail = null,
                   evidence_purged_at = pg_catalog.now()
             where evidence_purged_at is null
               and status in ('resolved', 'dismissed')
               and reviewed_at <= pg_catalog.now() - interval '1 year';
        end;
        $$;
        revoke execute on procedure public.purge_expired_taxi_report_evidence()
        from public, anon, authenticated;
        """
    )
    op.execute(
        """
        do $$
        declare job_id bigint;
        begin
            for job_id in select jobid from cron.job where jobname = 'purge-taxi-report-evidence'
            loop
                perform cron.unschedule(job_id);
            end loop;
            perform cron.schedule(
                'purge-taxi-report-evidence',
                '10 19 * * *',
                'call public.purge_expired_taxi_report_evidence();'
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
            for job_id in select jobid from cron.job where jobname = 'purge-taxi-report-evidence'
            loop
                perform cron.unschedule(job_id);
            end loop;
        end;
        $$;
        """
    )
    op.execute("drop procedure if exists public.purge_expired_taxi_report_evidence()")
    op.drop_table("taxi_reports")
