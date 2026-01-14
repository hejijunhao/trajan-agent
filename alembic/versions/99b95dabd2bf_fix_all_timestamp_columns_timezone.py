"""fix_all_timestamp_columns_timezone

Revision ID: 99b95dabd2bf
Revises: 2f7f9f1efd0b
Create Date: 2026-01-14 09:27:14.557401

Converts all created_at and updated_at columns from TIMESTAMP to TIMESTAMP WITH TIME ZONE.
This fixes asyncpg errors when binding timezone-aware Python datetimes to timezone-naive columns.

See: docs/executing/timestamp-timezone-systemic-fix.md
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "99b95dabd2bf"
down_revision: str | None = "2f7f9f1efd0b"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# Tables with both created_at and updated_at
TABLES_BOTH = [
    "app_info",
    "documents",
    "organizations",
    "products",
    "repositories",
    "subscriptions",
    "user_preferences",
    "users",
    "work_items",
]

# Tables with only created_at
TABLES_CREATED_ONLY = [
    "billing_events",
    "referrals",
    "usage_snapshots",
]


def upgrade() -> None:
    for table in TABLES_BOTH:
        op.alter_column(
            table,
            "created_at",
            existing_type=postgresql.TIMESTAMP(),
            type_=sa.DateTime(timezone=True),
            existing_nullable=False,
        )
        op.alter_column(
            table,
            "updated_at",
            existing_type=postgresql.TIMESTAMP(),
            type_=sa.DateTime(timezone=True),
            existing_nullable=False,
        )

    for table in TABLES_CREATED_ONLY:
        op.alter_column(
            table,
            "created_at",
            existing_type=postgresql.TIMESTAMP(),
            type_=sa.DateTime(timezone=True),
            existing_nullable=False,
        )


def downgrade() -> None:
    for table in TABLES_BOTH:
        op.alter_column(
            table,
            "created_at",
            existing_type=sa.DateTime(timezone=True),
            type_=postgresql.TIMESTAMP(),
            existing_nullable=False,
        )
        op.alter_column(
            table,
            "updated_at",
            existing_type=sa.DateTime(timezone=True),
            type_=postgresql.TIMESTAMP(),
            existing_nullable=False,
        )

    for table in TABLES_CREATED_ONLY:
        op.alter_column(
            table,
            "created_at",
            existing_type=sa.DateTime(timezone=True),
            type_=postgresql.TIMESTAMP(),
            existing_nullable=False,
        )
