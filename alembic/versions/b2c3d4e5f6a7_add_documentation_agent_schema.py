"""Add documentation agent schema (folder column, docs generation fields)

Revision ID: b2c3d4e5f6a7
Revises: a1b2c3d4e5f6
Create Date: 2026-01-10 18:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "b2c3d4e5f6a7"
down_revision: str | None = "a1b2c3d4e5f6"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # === Document model: Add folder column ===
    op.add_column(
        "documents",
        sa.Column(
            "folder",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=True,
            comment="Folder path for document organization (e.g. blueprints, plans, completions)",
        ),
    )

    # Add index for folder path queries
    op.create_index(
        "ix_documents_folder_path",
        "documents",
        [sa.text("(folder->>'path')")],
        postgresql_using="btree",
    )

    # === Product model: Add docs generation fields ===
    op.add_column(
        "products",
        sa.Column(
            "docs_generation_status",
            sa.String(20),
            nullable=True,
            comment="Doc generation state: 'generating' | 'completed' | 'failed' | NULL",
        ),
    )
    op.add_column(
        "products",
        sa.Column(
            "docs_generation_error",
            sa.String(500),
            nullable=True,
            comment="Error message if doc generation failed",
        ),
    )
    op.add_column(
        "products",
        sa.Column(
            "docs_generation_progress",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=True,
            comment="Real-time progress updates during doc generation (ephemeral)",
        ),
    )
    op.add_column(
        "products",
        sa.Column(
            "last_docs_generated_at",
            sa.DateTime(),
            nullable=True,
            comment="Timestamp of last successful doc generation",
        ),
    )


def downgrade() -> None:
    # Remove Product columns
    op.drop_column("products", "last_docs_generated_at")
    op.drop_column("products", "docs_generation_progress")
    op.drop_column("products", "docs_generation_error")
    op.drop_column("products", "docs_generation_status")

    # Remove Document columns
    op.drop_index("ix_documents_folder_path", table_name="documents")
    op.drop_column("documents", "folder")
