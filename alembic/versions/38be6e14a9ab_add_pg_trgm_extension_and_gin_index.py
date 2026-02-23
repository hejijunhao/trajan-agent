"""Add pg_trgm extension and GIN trigram index for duplicate detection

Revision ID: 38be6e14a9ab
Revises: 0ca91dc1a638
Create Date: 2026-02-23 14:53:49.345964

Adds the pg_trgm extension and a GIN trigram index on work_items.title,
required by the Public Ticket API duplicate detection service (dedup.py).
These were previously only created via init_db() and not tracked in Alembic.

Both statements are idempotent (IF NOT EXISTS) so this is safe to run on
databases where they already exist.
"""

from collections.abc import Sequence

from alembic import op
from sqlalchemy import text

revision: str = "38be6e14a9ab"
down_revision: str | None = "0ca91dc1a638"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute("CREATE EXTENSION IF NOT EXISTS pg_trgm")
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_work_items_title_trgm "
        "ON work_items USING gin (title gin_trgm_ops)"
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS idx_work_items_title_trgm")
    op.execute("DROP EXTENSION IF EXISTS pg_trgm")
