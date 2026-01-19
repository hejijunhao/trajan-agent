"""Rename document user_id to created_by_user_id

Revision ID: d5e6f7a8b9c0
Revises: c9ec2eb3ade1
Create Date: 2026-01-19 21:30:00.000000

This migration renames the `user_id` column to `created_by_user_id` on the
documents table. This is a semantic clarification (Phase 2 of product-scoped resources):

- OLD: `user_id` implied ownership/visibility control
- NEW: `created_by_user_id` clarifies this tracks WHO CREATED the document

Visibility is now controlled by Product access (RLS), not by user ownership.
All Product collaborators can see all documents in that Product.
"""

from collections.abc import Sequence

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "d5e6f7a8b9c0"
down_revision: str | None = "c9ec2eb3ade1"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Rename user_id -> created_by_user_id on documents table."""

    # Step 1: Rename the column (preserves data)
    op.execute("ALTER TABLE documents RENAME COLUMN user_id TO created_by_user_id")

    # Step 2: Rename the index
    op.execute(
        "ALTER INDEX IF EXISTS ix_documents_user_id "
        "RENAME TO ix_documents_created_by_user_id"
    )

    # Step 3: Rename the foreign key constraint (if it has a name)
    # First drop, then recreate with the new column name
    op.execute("ALTER TABLE documents DROP CONSTRAINT IF EXISTS documents_user_id_fkey")
    op.execute(
        "ALTER TABLE documents "
        "ADD CONSTRAINT documents_created_by_user_id_fkey "
        "FOREIGN KEY (created_by_user_id) REFERENCES users(id)"
    )

    print("Migration complete: documents.user_id -> created_by_user_id")


def downgrade() -> None:
    """Rename created_by_user_id -> user_id on documents table."""

    # Step 1: Rename the column back
    op.execute("ALTER TABLE documents RENAME COLUMN created_by_user_id TO user_id")

    # Step 2: Rename the index back
    op.execute(
        "ALTER INDEX IF EXISTS ix_documents_created_by_user_id "
        "RENAME TO ix_documents_user_id"
    )

    # Step 3: Rename the foreign key constraint back
    op.execute(
        "ALTER TABLE documents DROP CONSTRAINT IF EXISTS documents_created_by_user_id_fkey"
    )
    op.execute(
        "ALTER TABLE documents "
        "ADD CONSTRAINT documents_user_id_fkey "
        "FOREIGN KEY (user_id) REFERENCES users(id)"
    )

    print("Rollback complete: documents.created_by_user_id -> user_id")
