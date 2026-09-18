"""Grant Auth Hooks access to the digest extension schema.

Revision ID: e4c5d6e7f8a9
Revises: e3b4c5d6e7f8
Create Date: 2026-09-14 00:00:00.000000
"""

from typing import Sequence, Union

from alembic import op


revision: str = "e4c5d6e7f8a9"
down_revision: Union[str, None] = "e3b4c5d6e7f8"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    if op.get_bind().dialect.name != "postgresql":
        return

    op.execute("grant usage on schema extensions to supabase_auth_admin")


def downgrade() -> None:
    if op.get_bind().dialect.name != "postgresql":
        return

    op.execute("revoke usage on schema extensions from supabase_auth_admin")
