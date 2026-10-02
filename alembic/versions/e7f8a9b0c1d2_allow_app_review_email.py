"""Allow the app review account email.

앱 심사용 계정(서버가 고정 코드로 인증번호를 대신 발급)을 허용 목록에 추가한다.
주소는 다른 테스트 이메일과 마찬가지로 sha256 해시로만 둔다.

Revision ID: e7f8a9b0c1d2
Revises: d4e5f6a7b8ca
Create Date: 2026-10-02 23:30:00.000000
"""

from typing import Sequence, Union

from alembic import op


revision: str = "e7f8a9b0c1d2"
down_revision: Union[str, None] = "d4e5f6a7b8ca"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


TEST_EMAIL_HASHES = (
    "a13288b045771cf57a27d60e19568832cde3c757a1c053df82d50b8b0a13b844",
    "847c66464ac2874ad4779a2bd3b56b1bf3fed6c1889dca86a8156199b2c9c3df",
)
REVIEW_EMAIL_HASH = "0a862fcb497a3672184025c1c8213daeabcf108a7e9b25860643f9e4ec782a7c"


def _replace_allowlist(hashes: Sequence[str]) -> None:
    if op.get_bind().dialect.name != "postgresql":
        return

    hash_list = ",\n                    ".join(f"'{value}'" for value in hashes)
    op.execute(
        rf"""
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
                    {hash_list}
                );
        $$;
        """
    )


def upgrade() -> None:
    _replace_allowlist((*TEST_EMAIL_HASHES, REVIEW_EMAIL_HASH))


def downgrade() -> None:
    _replace_allowlist(TEST_EMAIL_HASHES)
