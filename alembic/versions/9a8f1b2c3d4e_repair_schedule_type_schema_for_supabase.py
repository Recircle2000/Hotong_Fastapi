"""Repair missing shuttle schedule type tables for Supabase migration.

Revision ID: 9a8f1b2c3d4e
Revises: d4e5f6a7b8c9
Create Date: 2026-04-09 09:20:00.000000

"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "9a8f1b2c3d4e"
down_revision: Union[str, None] = "d4e5f6a7b8c9"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


DEFAULT_SCHEDULE_TYPES: tuple[tuple[str, str], ...] = (
    ("Weekday", "평일"),
    ("Weekday_friday", "금요일"),
    ("Saturday", "토요일"),
    ("Holiday", "공휴일"),
)


def _get_table_names(inspector: sa.Inspector) -> set[str]:
    return set(inspector.get_table_names())


def _get_column_names(inspector: sa.Inspector, table_name: str) -> set[str]:
    return {column["name"] for column in inspector.get_columns(table_name)}


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    table_names = _get_table_names(inspector)

    if "schedule_types" not in table_names:
        op.create_table(
            "schedule_types",
            sa.Column("id", sa.Integer(), nullable=False),
            sa.Column("schedule_type", sa.String(length=50), nullable=False),
            sa.Column("schedule_type_name", sa.String(length=50), nullable=False),
            sa.Column("is_activate", sa.Boolean(), nullable=True),
            sa.PrimaryKeyConstraint("id"),
            sa.UniqueConstraint("schedule_type"),
            sa.UniqueConstraint("schedule_type_name"),
        )
        op.create_index(op.f("ix_schedule_types_id"), "schedule_types", ["id"], unique=False)
        inspector = sa.inspect(bind)
        table_names = _get_table_names(inspector)
    else:
        schedule_type_columns = _get_column_names(inspector, "schedule_types")
        if "schedule_type_name" not in schedule_type_columns:
            op.add_column("schedule_types", sa.Column("schedule_type_name", sa.String(length=50), nullable=True))
        if "is_activate" not in schedule_type_columns:
            op.add_column("schedule_types", sa.Column("is_activate", sa.Boolean(), nullable=True))

    existing_schedule_types = set(
        bind.execute(sa.text("SELECT schedule_type FROM schedule_types")).scalars()
    )
    for schedule_type, schedule_type_name in DEFAULT_SCHEDULE_TYPES:
        if schedule_type in existing_schedule_types:
            continue
        bind.execute(
            sa.text(
                """
                INSERT INTO schedule_types (schedule_type, schedule_type_name, is_activate)
                VALUES (:schedule_type, :schedule_type_name, :is_activate)
                """
            ),
            {
                "schedule_type": schedule_type,
                "schedule_type_name": schedule_type_name,
                "is_activate": True,
            },
        )

    inspector = sa.inspect(bind)
    table_names = _get_table_names(inspector)

    if "schedule_exceptions" not in table_names:
        op.create_table(
            "schedule_exceptions",
            sa.Column("id", sa.Integer(), nullable=False),
            sa.Column("start_date", sa.Date(), nullable=False),
            sa.Column("end_date", sa.Date(), nullable=False),
            sa.Column("schedule_type", sa.String(length=50), nullable=False),
            sa.Column("reason", sa.String(length=255), nullable=True),
            sa.Column("is_activate", sa.Boolean(), nullable=True),
            sa.Column("include_weekday", sa.Boolean(), nullable=True),
            sa.Column("include_weekday_friday", sa.Boolean(), nullable=True),
            sa.Column("include_saturday", sa.Boolean(), nullable=True),
            sa.Column("include_sunday", sa.Boolean(), nullable=True),
            sa.Column("include_holiday", sa.Boolean(), nullable=True),
            sa.ForeignKeyConstraint(["schedule_type"], ["schedule_types.schedule_type"]),
            sa.PrimaryKeyConstraint("id"),
        )
        op.create_index(op.f("ix_schedule_exceptions_id"), "schedule_exceptions", ["id"], unique=False)
    else:
        schedule_exception_columns = _get_column_names(inspector, "schedule_exceptions")
        if "include_weekday" not in schedule_exception_columns:
            op.add_column("schedule_exceptions", sa.Column("include_weekday", sa.Boolean(), nullable=True))
        if "include_weekday_friday" not in schedule_exception_columns:
            op.add_column("schedule_exceptions", sa.Column("include_weekday_friday", sa.Boolean(), nullable=True))
            bind.execute(
                sa.text(
                    """
                    UPDATE schedule_exceptions
                    SET include_weekday_friday = COALESCE(include_weekday, true)
                    WHERE include_weekday_friday IS NULL
                    """
                )
            )
        if "include_saturday" not in schedule_exception_columns:
            op.add_column("schedule_exceptions", sa.Column("include_saturday", sa.Boolean(), nullable=True))
        if "include_sunday" not in schedule_exception_columns:
            op.add_column("schedule_exceptions", sa.Column("include_sunday", sa.Boolean(), nullable=True))
        if "include_holiday" not in schedule_exception_columns:
            op.add_column("schedule_exceptions", sa.Column("include_holiday", sa.Boolean(), nullable=True))


def downgrade() -> None:
    # This repair migration is intentionally irreversible because it may create
    # missing production tables and backfill default schedule type rows.
    pass
