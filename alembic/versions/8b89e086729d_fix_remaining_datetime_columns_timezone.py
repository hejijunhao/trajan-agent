"""fix_remaining_datetime_columns_timezone

Revision ID: 8b89e086729d
Revises: 99b95dabd2bf
Create Date: 2026-01-14 10:16:38.377970

Fixes remaining datetime columns that were missed by the systemic timestamp fix
(migration 99b95dabd2bf). These columns need TIMESTAMP WITH TIME ZONE to prevent
asyncpg errors when inserting timezone-aware Python datetimes.

Critical fix: organization_members.joined_at (uses datetime.now(UTC) in default_factory)
Consistency fixes: 9 additional datetime columns across 4 tables
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "8b89e086729d"
down_revision: str | None = "99b95dabd2bf"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# Columns to fix: (table, column)
COLUMNS_TO_FIX = [
    # Critical - uses timezone-aware default_factory
    ("organization_members", "joined_at"),
    ("organization_members", "invited_at"),
    # Consistency fixes
    ("subscriptions", "current_period_start"),
    ("subscriptions", "current_period_end"),
    ("subscriptions", "canceled_at"),
    ("subscriptions", "manually_assigned_at"),
    ("referrals", "signed_up_at"),
    ("referrals", "converted_at"),
    ("referrals", "credited_at"),
    ("documents", "last_synced_at"),
]


def upgrade() -> None:
    for table, column in COLUMNS_TO_FIX:
        op.alter_column(
            table,
            column,
            existing_type=postgresql.TIMESTAMP(),
            type_=sa.DateTime(timezone=True),
            existing_nullable=True if column != "joined_at" else False,
        )


def downgrade() -> None:
    for table, column in COLUMNS_TO_FIX:
        op.alter_column(
            table,
            column,
            existing_type=sa.DateTime(timezone=True),
            type_=postgresql.TIMESTAMP(),
            existing_nullable=True if column != "joined_at" else False,
        )
