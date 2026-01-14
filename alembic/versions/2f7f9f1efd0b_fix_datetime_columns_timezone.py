"""fix_datetime_columns_timezone

Revision ID: 2f7f9f1efd0b
Revises: 39440c5add4a
Create Date: 2026-01-14 09:07:29.949646

Fixes last_docs_generated_at to use TIMESTAMP WITH TIME ZONE.
This resolves asyncpg errors when storing timezone-aware Python datetimes.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "2f7f9f1efd0b"
down_revision: str | None = "39440c5add4a"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.alter_column(
        "products",
        "last_docs_generated_at",
        existing_type=postgresql.TIMESTAMP(),
        type_=sa.DateTime(timezone=True),
        existing_comment="Timestamp of last successful doc generation",
        existing_nullable=True,
    )


def downgrade() -> None:
    op.alter_column(
        "products",
        "last_docs_generated_at",
        existing_type=sa.DateTime(timezone=True),
        type_=postgresql.TIMESTAMP(),
        existing_comment="Timestamp of last successful doc generation",
        existing_nullable=True,
    )
