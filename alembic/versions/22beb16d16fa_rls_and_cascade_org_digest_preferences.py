"""RLS + ON DELETE CASCADE for org_digest_preferences

Revision ID: 22beb16d16fa
Revises: 77caa496e515
Create Date: 2026-03-07 18:00:00.000000

Adds:
1. Row-Level Security: users can only access their own digest preference rows.
   Follows the same user_id = app_user_id() pattern as user_preferences (Phase 2).
   The digest cron job runs with service role and bypasses RLS.

2. ON DELETE CASCADE on both foreign keys so preference rows are automatically
   cleaned up when a user or organization is deleted.
"""

from typing import Sequence, Union

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "22beb16d16fa"
down_revision: Union[str, None] = "77caa496e515"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

TABLE = "org_digest_preferences"


def upgrade() -> None:
    # =========================================================================
    # 1. ON DELETE CASCADE — replace both foreign keys
    # =========================================================================

    # user_id FK
    op.drop_constraint(
        "org_digest_preferences_user_id_fkey", TABLE, type_="foreignkey"
    )
    op.create_foreign_key(
        "org_digest_preferences_user_id_fkey",
        TABLE,
        "users",
        ["user_id"],
        ["id"],
        ondelete="CASCADE",
    )

    # organization_id FK
    op.drop_constraint(
        "org_digest_preferences_organization_id_fkey", TABLE, type_="foreignkey"
    )
    op.create_foreign_key(
        "org_digest_preferences_organization_id_fkey",
        TABLE,
        "organizations",
        ["organization_id"],
        ["id"],
        ondelete="CASCADE",
    )

    # =========================================================================
    # 2. ROW-LEVEL SECURITY — user-scoped (same pattern as user_preferences)
    # =========================================================================

    op.execute(f"ALTER TABLE {TABLE} ENABLE ROW LEVEL SECURITY")

    # Single policy: users have full CRUD on their own preference rows
    op.execute(f"""
        CREATE POLICY org_digest_preferences_own ON {TABLE}
            FOR ALL
            USING (user_id = app_user_id())
            WITH CHECK (user_id = app_user_id())
    """)

    print(f"RLS + CASCADE complete for {TABLE}")


def downgrade() -> None:
    # Remove RLS
    op.execute(f"DROP POLICY IF EXISTS org_digest_preferences_own ON {TABLE}")
    op.execute(f"ALTER TABLE {TABLE} DISABLE ROW LEVEL SECURITY")

    # Restore original FKs without CASCADE
    op.drop_constraint(
        "org_digest_preferences_user_id_fkey", TABLE, type_="foreignkey"
    )
    op.create_foreign_key(
        "org_digest_preferences_user_id_fkey",
        TABLE,
        "users",
        ["user_id"],
        ["id"],
    )

    op.drop_constraint(
        "org_digest_preferences_organization_id_fkey", TABLE, type_="foreignkey"
    )
    op.create_foreign_key(
        "org_digest_preferences_organization_id_fkey",
        TABLE,
        "organizations",
        ["organization_id"],
        ["id"],
    )

    print(f"RLS + CASCADE removed for {TABLE}")
