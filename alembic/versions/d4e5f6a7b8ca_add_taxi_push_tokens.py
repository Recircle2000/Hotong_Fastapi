"""Store FCM device tokens for taxi party push notifications.

Revision ID: d4e5f6a7b8ca
Revises: c3d4e5f6a7b9
Create Date: 2026-10-01 18:00:00.000000
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op


revision: str = "d4e5f6a7b8ca"
down_revision: Union[str, None] = "c3d4e5f6a7b9"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


# 앱은 택시 화면에 들어올 때마다 토큰을 다시 등록한다. 60일 동안 갱신되지 않은 토큰은
# 앱을 지웠거나 쓰지 않는 기기라서 매일 도는 정리 작업에서 함께 지운다.
TOKEN_CLEANUP = """            delete from bus_service.taxi_push_tokens
             where updated_at <= pg_catalog.now() - interval '60 days';
"""


def _purge_procedure(token_cleanup: str) -> str:
    return (
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
"""
        + token_cleanup
        + """            commit;
            perform pg_catalog.pg_advisory_unlock(lock_key);
        end;
        $$;
        revoke execute on procedure public.purge_expired_taxi_records()
        from public, anon, authenticated;
        """
    )


def upgrade() -> None:
    if op.get_bind().dialect.name != "postgresql":
        return

    op.create_table(
        "taxi_push_tokens",
        sa.Column("token", sa.String(length=512), primary_key=True),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("platform", sa.String(length=10), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.CheckConstraint("platform in ('android', 'ios')", name="ck_taxi_push_tokens_platform"),
        # 탈퇴하면 기기 토큰도 함께 지운다.
        sa.ForeignKeyConstraint(["user_id"], ["auth.users.id"], ondelete="CASCADE"),
    )
    op.create_index("ix_taxi_push_tokens_user_id", "taxi_push_tokens", ["user_id"])
    # 다른 택시 테이블처럼 Supabase 공개 API(PostgREST) 역할에서는 접근할 수 없게 한다.
    op.execute("revoke all on table bus_service.taxi_push_tokens from public, anon, authenticated")
    op.execute(_purge_procedure(TOKEN_CLEANUP))


def downgrade() -> None:
    if op.get_bind().dialect.name != "postgresql":
        return
    op.execute(_purge_procedure(""))
    op.drop_index("ix_taxi_push_tokens_user_id", table_name="taxi_push_tokens")
    op.drop_table("taxi_push_tokens")
