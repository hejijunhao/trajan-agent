"""rename_work_item_user_id_to_created_by

Revision ID: 5817dc60b969
Revises: d5e6f7a8b9c0
Create Date: 2026-01-19 21:55:12.996393

This migration renames the `user_id` column to `created_by_user_id` on the
work_items table. This is a semantic clarification (Phase 3 of product-scoped resources):

- OLD: `user_id` implied ownership/visibility control
- NEW: `created_by_user_id` clarifies this tracks WHO CREATED the work item

Visibility is now controlled by Product access (RLS), not by user ownership.
All Product collaborators can see all work items in that Product.
"""

from collections.abc import Sequence

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "5817dc60b969"
down_revision: str | None = "d5e6f7a8b9c0"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Rename user_id -> created_by_user_id on work_items table."""

    # Step 1: Rename the column (preserves data)
    op.execute("ALTER TABLE work_items RENAME COLUMN user_id TO created_by_user_id")

    # Step 2: Rename the index
    op.execute(
        "ALTER INDEX IF EXISTS ix_work_items_user_id "
        "RENAME TO ix_work_items_created_by_user_id"
    )

    # Step 3: Rename the foreign key constraint (if it has a name)
    # First drop, then recreate with the new column name
    op.execute("ALTER TABLE work_items DROP CONSTRAINT IF EXISTS work_items_user_id_fkey")
    op.execute(
        "ALTER TABLE work_items "
        "ADD CONSTRAINT work_items_created_by_user_id_fkey "
        "FOREIGN KEY (created_by_user_id) REFERENCES users(id)"
    )

    print("Migration complete: work_items.user_id -> created_by_user_id")


def downgrade() -> None:
    """Rename created_by_user_id -> user_id on work_items table."""

    # Step 1: Rename the column back
    op.execute("ALTER TABLE work_items RENAME COLUMN created_by_user_id TO user_id")

    # Step 2: Rename the index back
    op.execute(
        "ALTER INDEX IF EXISTS ix_work_items_created_by_user_id "
        "RENAME TO ix_work_items_user_id"
    )

    # Step 3: Rename the foreign key constraint back
    op.execute(
        "ALTER TABLE work_items DROP CONSTRAINT IF EXISTS work_items_created_by_user_id_fkey"
    )
    op.execute(
        "ALTER TABLE work_items "
        "ADD CONSTRAINT work_items_user_id_fkey "
        "FOREIGN KEY (user_id) REFERENCES users(id)"
    )

    print("Rollback complete: work_items.created_by_user_id -> user_id")
