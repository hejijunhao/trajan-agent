"""Rename repository user_id to imported_by_user_id

Revision ID: c9ec2eb3ade1
Revises: c4d5e6f7a8b9
Create Date: 2026-01-19 18:29:38.437956

This migration renames the `user_id` column to `imported_by_user_id` on the
repositories table. This is a semantic clarification:

- OLD: `user_id` implied ownership/visibility control
- NEW: `imported_by_user_id` clarifies this tracks WHO IMPORTED the repo

Visibility is now controlled by Product access (RLS), not by user ownership.
All Product collaborators can see all repos in that Product.
"""

from collections.abc import Sequence

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "c9ec2eb3ade1"
down_revision: str | None = "c4d5e6f7a8b9"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Rename user_id -> imported_by_user_id on repositories table."""

    # Step 1: Rename the column (preserves data)
    op.execute("ALTER TABLE repositories RENAME COLUMN user_id TO imported_by_user_id")

    # Step 2: Rename the index
    op.execute(
        "ALTER INDEX IF EXISTS ix_repositories_user_id "
        "RENAME TO ix_repositories_imported_by_user_id"
    )

    # Step 3: Rename the foreign key constraint (if it has a name)
    # First drop, then recreate with the new column name
    op.execute("ALTER TABLE repositories DROP CONSTRAINT IF EXISTS repositories_user_id_fkey")
    op.execute(
        "ALTER TABLE repositories "
        "ADD CONSTRAINT repositories_imported_by_user_id_fkey "
        "FOREIGN KEY (imported_by_user_id) REFERENCES users(id)"
    )

    print("Migration complete: repositories.user_id -> imported_by_user_id")


def downgrade() -> None:
    """Rename imported_by_user_id -> user_id on repositories table."""

    # Step 1: Rename the column back
    op.execute("ALTER TABLE repositories RENAME COLUMN imported_by_user_id TO user_id")

    # Step 2: Rename the index back
    op.execute(
        "ALTER INDEX IF EXISTS ix_repositories_imported_by_user_id "
        "RENAME TO ix_repositories_user_id"
    )

    # Step 3: Rename the foreign key constraint back
    op.execute(
        "ALTER TABLE repositories DROP CONSTRAINT IF EXISTS repositories_imported_by_user_id_fkey"
    )
    op.execute(
        "ALTER TABLE repositories "
        "ADD CONSTRAINT repositories_user_id_fkey "
        "FOREIGN KEY (user_id) REFERENCES users(id)"
    )

    print("Rollback complete: repositories.imported_by_user_id -> user_id")
