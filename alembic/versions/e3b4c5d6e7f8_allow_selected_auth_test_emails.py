"""Allow selected external emails for authentication testing.

Revision ID: e3b4c5d6e7f8
Revises: e2a3b4c5d6e7
Create Date: 2026-09-14 00:00:00.000000
"""

from typing import Sequence, Union

from alembic import op


revision: str = "e3b4c5d6e7f8"
down_revision: Union[str, None] = "e2a3b4c5d6e7"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    if op.get_bind().dialect.name != "postgresql":
        return

    op.execute(
        r"""
        create or replace function public.is_allowed_app_auth_email(candidate_email text)
        returns boolean
        language sql
        immutable
        security invoker
        set search_path = ''
        as $$
            select
                lower(btrim(coalesce(candidate_email, '')))
                    ~ '^[^@[:space:]]+@vision[.]hoseo[.]edu$'
                or pg_catalog.encode(
                    extensions.digest(
                        lower(btrim(coalesce(candidate_email, ''))),
                        'sha256'
                    ),
                    'hex'
                ) in (
                    'a13288b045771cf57a27d60e19568832cde3c757a1c053df82d50b8b0a13b844',
                    '847c66464ac2874ad4779a2bd3b56b1bf3fed6c1889dca86a8156199b2c9c3df'
                );
        $$;

        grant execute on function public.is_allowed_app_auth_email(text)
        to supabase_auth_admin;
        revoke execute on function public.is_allowed_app_auth_email(text)
        from public, anon, authenticated;
        """
    )
    _replace_hooks(use_allowlist=True)


def downgrade() -> None:
    if op.get_bind().dialect.name != "postgresql":
        return

    _replace_hooks(use_allowlist=False)
    op.execute("drop function if exists public.is_allowed_app_auth_email(text)")


def _replace_hooks(*, use_allowlist: bool) -> None:
    signup_rejected = (
        "not public.is_allowed_app_auth_email(candidate_email)"
        if use_allowlist
        else "candidate_email !~ '^[^@[:space:]]+@vision[.]hoseo[.]edu$'"
    )
    token_rejected = (
        "not public.is_allowed_app_auth_email(auth_user.email)"
        if use_allowlist
        else "lower(btrim(coalesce(auth_user.email, ''))) "
        "!~ '^[^@[:space:]]+@vision[.]hoseo[.]edu$'"
    )
    new_email_rejected = (
        "not public.is_allowed_app_auth_email(new.email)"
        if use_allowlist
        else "lower(btrim(coalesce(new.email, ''))) "
        "!~ '^[^@[:space:]]+@vision[.]hoseo[.]edu$'"
    )
    changed_email_rejected = (
        "not public.is_allowed_app_auth_email(new.email_change)"
        if use_allowlist
        else "lower(btrim(new.email_change)) "
        "!~ '^[^@[:space:]]+@vision[.]hoseo[.]edu$'"
    )

    op.execute(
        rf"""
        create or replace function public.hook_restrict_school_signup(event jsonb)
        returns jsonb
        language plpgsql
        security invoker
        set search_path = ''
        as $$
        declare
            candidate_email text := lower(btrim(coalesce(event->'user'->>'email', '')));
        begin
            if {signup_rejected} then
                return jsonb_build_object(
                    'error', jsonb_build_object(
                        'http_code', 403,
                        'message', 'Only approved email addresses are allowed.'
                    )
                );
            end if;
            return '{{}}'::jsonb;
        end;
        $$;
        """
    )
    op.execute(
        rf"""
        create or replace function public.hook_restrict_school_token(event jsonb)
        returns jsonb
        language plpgsql
        security invoker
        set search_path = ''
        as $$
        declare
            auth_method text := coalesce(event->>'authentication_method', '');
            original_claims jsonb := coalesce(event->'claims', '{{}}'::jsonb);
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
               or {token_rejected} then
                return jsonb_build_object(
                    'error', jsonb_build_object(
                        'http_code', 403,
                        'message', 'A verified approved email is required.'
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
        rf"""
        create or replace function public.guard_school_email_change()
        returns trigger
        language plpgsql
        security invoker
        set search_path = ''
        as $$
        begin
            if new.email is distinct from old.email
               and {new_email_rejected} then
                raise exception using
                    errcode = '22023',
                    message = 'Only approved email addresses are allowed.';
            end if;

            if coalesce(new.email_change, '') <> ''
               and {changed_email_rejected} then
                raise exception using
                    errcode = '22023',
                    message = 'Only approved email addresses are allowed.';
            end if;

            return new;
        end;
        $$;
        """
    )
