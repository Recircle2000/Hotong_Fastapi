"""Add school email restrictions for Supabase Auth.

Revision ID: b7c2d4e6f8a0
Revises: 9a8f1b2c3d4e
Create Date: 2026-09-13 00:00:00.000000

The functions are installed by this migration, but the Before User Created and
Custom Access Token hooks must still be selected in the Supabase Dashboard.
"""

from typing import Sequence, Union

from alembic import op


revision: str = "b7c2d4e6f8a0"
down_revision: Union[str, None] = "9a8f1b2c3d4e"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    if op.get_bind().dialect.name != "postgresql":
        return

    op.execute(
        r"""
        create or replace function public.hook_restrict_school_signup(event jsonb)
        returns jsonb
        language plpgsql
        security invoker
        set search_path = ''
        as $$
        declare
            candidate_email text := lower(btrim(coalesce(event->'user'->>'email', '')));
        begin
            if candidate_email !~ '^[^@[:space:]]+@vision[.]hoseo[.]edu$' then
                return jsonb_build_object(
                    'error', jsonb_build_object(
                        'http_code', 403,
                        'message', 'Only vision.hoseo.edu email addresses are allowed.'
                    )
                );
            end if;

            return '{}'::jsonb;
        end;
        $$;
        """
    )

    op.execute(
        r"""
        create or replace function public.hook_restrict_school_token(event jsonb)
        returns jsonb
        language plpgsql
        security invoker
        set search_path = ''
        as $$
        declare
            auth_method text := coalesce(event->>'authentication_method', '');
            original_claims jsonb := coalesce(event->'claims', '{}'::jsonb);
            auth_user auth.users%rowtype;
            has_otp_method boolean := false;
        begin
            select *
              into auth_user
              from auth.users
             where id = (event->>'user_id')::uuid;

            if not found
               or auth_user.email_confirmed_at is null
               or coalesce(auth_user.is_anonymous, false)
               or lower(btrim(coalesce(auth_user.email, '')))
                    !~ '^[^@[:space:]]+@vision[.]hoseo[.]edu$' then
                return jsonb_build_object(
                    'error', jsonb_build_object(
                        'http_code', 403,
                        'message', 'A verified Hoseo University email is required.'
                    )
                );
            end if;

            select exists (
                select 1
                  from jsonb_array_elements(coalesce(original_claims->'amr', '[]'::jsonb)) entry
                 where entry->>'method' = 'otp'
            ) into has_otp_method;

            if auth_method not in ('otp', 'token_refresh')
               or not has_otp_method then
                return jsonb_build_object(
                    'error', jsonb_build_object(
                        'http_code', 403,
                        'message', 'Email OTP authentication is required.'
                    )
                );
            end if;

            return jsonb_build_object('claims', original_claims);
        exception
            when invalid_text_representation then
                return jsonb_build_object(
                    'error', jsonb_build_object(
                        'http_code', 403,
                        'message', 'Invalid authentication user identifier.'
                    )
                );
        end;
        $$;
        """
    )

    op.execute(
        r"""
        create or replace function public.guard_school_email_change()
        returns trigger
        language plpgsql
        security invoker
        set search_path = ''
        as $$
        begin
            if new.email is distinct from old.email
               and lower(btrim(coalesce(new.email, '')))
                    !~ '^[^@[:space:]]+@vision[.]hoseo[.]edu$' then
                raise exception using
                    errcode = '22023',
                    message = 'Only vision.hoseo.edu email addresses are allowed.';
            end if;

            if coalesce(new.email_change, '') <> ''
               and lower(btrim(new.email_change))
                    !~ '^[^@[:space:]]+@vision[.]hoseo[.]edu$' then
                raise exception using
                    errcode = '22023',
                    message = 'Only vision.hoseo.edu email addresses are allowed.';
            end if;

            return new;
        end;
        $$;

        drop trigger if exists guard_school_email_change on auth.users;
        create trigger guard_school_email_change
        before update of email, email_change on auth.users
        for each row
        execute function public.guard_school_email_change();
        """
    )

    op.execute(
        "grant usage on schema public to supabase_auth_admin"
    )
    op.execute(
        "grant execute on function public.hook_restrict_school_signup(jsonb) "
        "to supabase_auth_admin"
    )
    op.execute(
        "grant execute on function public.hook_restrict_school_token(jsonb) "
        "to supabase_auth_admin"
    )
    op.execute(
        "revoke execute on function public.hook_restrict_school_signup(jsonb) "
        "from public, anon, authenticated"
    )
    op.execute(
        "revoke execute on function public.hook_restrict_school_token(jsonb) "
        "from public, anon, authenticated"
    )
    op.execute(
        "revoke execute on function public.guard_school_email_change() "
        "from public, anon, authenticated"
    )


def downgrade() -> None:
    if op.get_bind().dialect.name != "postgresql":
        return

    op.execute("drop trigger if exists guard_school_email_change on auth.users")
    op.execute("drop function if exists public.guard_school_email_change()")
    op.execute("drop function if exists public.hook_restrict_school_token(jsonb)")
    op.execute("drop function if exists public.hook_restrict_school_signup(jsonb)")
