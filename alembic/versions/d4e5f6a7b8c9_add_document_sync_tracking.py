"""Add document sync tracking columns for GitHub synchronization

Revision ID: d4e5f6a7b8c9
Revises: c3d4e5f6a7b8
Create Date: 2026-01-10 20:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "d4e5f6a7b8c9"
down_revision: str | None = "c3d4e5f6a7b8"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # Add GitHub sync tracking columns to documents table
    op.add_column(
        "documents",
        sa.Column(
            "github_sha",
            sa.String(40),
            nullable=True,
            comment="Git blob SHA of the file content for change detection",
        ),
    )
    op.add_column(
        "documents",
        sa.Column(
            "github_path",
            sa.String(500),
            nullable=True,
            comment="Path to the file in the GitHub repository (e.g. docs/changelog.md)",
        ),
    )
    op.add_column(
        "documents",
        sa.Column(
            "last_synced_at",
            sa.DateTime(),
            nullable=True,
            comment="Timestamp of last successful sync with GitHub",
        ),
    )
    op.add_column(
        "documents",
        sa.Column(
            "sync_status",
            sa.String(20),
            nullable=True,
            comment="Sync state: synced | local_changes | remote_changes | conflict",
        ),
    )

    # Add index for github_path lookups
    op.create_index(
        "ix_documents_github_path",
        "documents",
        ["github_path"],
        postgresql_using="btree",
    )

    # Add index for sync_status filtering
    op.create_index(
        "ix_documents_sync_status",
        "documents",
        ["sync_status"],
        postgresql_using="btree",
    )


def downgrade() -> None:
    op.drop_index("ix_documents_sync_status", table_name="documents")
    op.drop_index("ix_documents_github_path", table_name="documents")
    op.drop_column("documents", "sync_status")
    op.drop_column("documents", "last_synced_at")
    op.drop_column("documents", "github_path")
    op.drop_column("documents", "github_sha")
