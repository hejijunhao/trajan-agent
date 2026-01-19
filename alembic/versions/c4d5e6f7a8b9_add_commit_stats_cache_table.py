"""Add commit_stats_cache table for GitHub commit statistics caching

Revision ID: c4d5e6f7a8b9
Revises: b8c9d0e1f2a3
Create Date: 2026-01-19 22:00:00.000000

This table caches commit statistics (additions, deletions, files_changed) fetched from
the GitHub API. It's a shared cache (not user-scoped) because:
1. Git SHAs are immutable - stats never change
2. Stats are public - same for all viewers
3. Avoids N duplicate rows for N users viewing same commit
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "c4d5e6f7a8b9"
down_revision: str | None = "b8c9d0e1f2a3"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "commit_stats_cache",
        sa.Column(
            "id",
            sa.UUID(),
            server_default=sa.text("gen_random_uuid()"),
            nullable=False,
        ),
        sa.Column("repository_full_name", sa.String(500), nullable=False),
        sa.Column("commit_sha", sa.String(40), nullable=False),
        sa.Column("additions", sa.Integer(), server_default="0", nullable=False),
        sa.Column("deletions", sa.Integer(), server_default="0", nullable=False),
        sa.Column("files_changed", sa.Integer(), server_default="0", nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id"),
    )

    # Unique composite index for lookups (also enforces uniqueness)
    op.create_index(
        "ix_commit_stats_cache_repo_sha",
        "commit_stats_cache",
        ["repository_full_name", "commit_sha"],
        unique=True,
    )

    # Index for potential cleanup queries
    op.create_index(
        "ix_commit_stats_cache_created_at",
        "commit_stats_cache",
        ["created_at"],
    )


def downgrade() -> None:
    op.drop_index("ix_commit_stats_cache_created_at", table_name="commit_stats_cache")
    op.drop_index("ix_commit_stats_cache_repo_sha", table_name="commit_stats_cache")
    op.drop_table("commit_stats_cache")
