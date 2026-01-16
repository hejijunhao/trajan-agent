"""RLS Phase 2: User-scoped tables

Revision ID: c3e4f5a6b7c8
Revises: b2d3e4f5a6b7
Create Date: 2026-01-16 20:00:00.000000

This migration enables Row-Level Security on user-scoped tables:

1. users - Users can only see/update their own record
2. user_preferences - Users can only access their own preferences
3. feedback - Users see their own + admins see all

These are the simplest RLS policies, validating the infrastructure
before tackling more complex organization and product hierarchies.

Each policy uses app_user_id() from the Phase 1 infrastructure migration.
"""

from typing import Sequence, Union

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "c3e4f5a6b7c8"
down_revision: Union[str, None] = "b2d3e4f5a6b7"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Enable RLS on user-scoped tables with appropriate policies."""

    # =========================================================================
    # 1. USERS TABLE
    # =========================================================================
    # Users can only see and update their own record.
    # Insert is handled by the auth trigger (SECURITY DEFINER bypasses RLS).
    # Delete is not allowed for regular users (admin only via service role).
    # =========================================================================

    # Enable RLS on users table
    op.execute("ALTER TABLE users ENABLE ROW LEVEL SECURITY")

    # Policy: Users can only SELECT their own record
    op.execute("""
        CREATE POLICY users_select_own ON users
            FOR SELECT
            USING (id = app_user_id())
    """)

    # Policy: Users can only UPDATE their own record
    op.execute("""
        CREATE POLICY users_update_own ON users
            FOR UPDATE
            USING (id = app_user_id())
            WITH CHECK (id = app_user_id())
    """)

    # Note: No INSERT policy for regular users - auth trigger handles user creation
    # Note: No DELETE policy - users cannot delete their own accounts (admin only)

    # =========================================================================
    # 2. USER_PREFERENCES TABLE
    # =========================================================================
    # Users have full CRUD on their own preferences.
    # The user_id is the primary key (one-to-one with users).
    # =========================================================================

    # Enable RLS on user_preferences table
    op.execute("ALTER TABLE user_preferences ENABLE ROW LEVEL SECURITY")

    # Policy: Full access to own preferences (SELECT, INSERT, UPDATE, DELETE)
    op.execute("""
        CREATE POLICY user_preferences_own ON user_preferences
            FOR ALL
            USING (user_id = app_user_id())
            WITH CHECK (user_id = app_user_id())
    """)

    # =========================================================================
    # 3. FEEDBACK TABLE
    # =========================================================================
    # Users can see and create their own feedback.
    # System admins (is_admin=true) can see all feedback for review.
    # =========================================================================

    # Enable RLS on feedback table
    op.execute("ALTER TABLE feedback ENABLE ROW LEVEL SECURITY")

    # Policy: Users can SELECT their own feedback
    op.execute("""
        CREATE POLICY feedback_select_own ON feedback
            FOR SELECT
            USING (user_id = app_user_id())
    """)

    # Policy: Users can INSERT feedback (must be their own user_id)
    op.execute("""
        CREATE POLICY feedback_insert_own ON feedback
            FOR INSERT
            WITH CHECK (user_id = app_user_id())
    """)

    # Policy: Users can UPDATE their own feedback (e.g., edit before submission)
    op.execute("""
        CREATE POLICY feedback_update_own ON feedback
            FOR UPDATE
            USING (user_id = app_user_id())
            WITH CHECK (user_id = app_user_id())
    """)

    # Policy: System admins can SELECT all feedback for review
    # This uses a subquery to check the is_admin flag on the users table
    op.execute("""
        CREATE POLICY feedback_admin_select ON feedback
            FOR SELECT
            USING (
                EXISTS (
                    SELECT 1 FROM users
                    WHERE id = app_user_id() AND is_admin = true
                )
            )
    """)

    # Policy: System admins can UPDATE feedback (status, admin_notes)
    op.execute("""
        CREATE POLICY feedback_admin_update ON feedback
            FOR UPDATE
            USING (
                EXISTS (
                    SELECT 1 FROM users
                    WHERE id = app_user_id() AND is_admin = true
                )
            )
    """)

    print("RLS Phase 2 complete - User-scoped tables:")
    print("  - users: SELECT/UPDATE own record only")
    print("  - user_preferences: Full CRUD on own preferences")
    print("  - feedback: Own + admin read/update")


def downgrade() -> None:
    """Remove RLS from user-scoped tables."""

    # Drop policies and disable RLS on feedback
    op.execute("DROP POLICY IF EXISTS feedback_admin_update ON feedback")
    op.execute("DROP POLICY IF EXISTS feedback_admin_select ON feedback")
    op.execute("DROP POLICY IF EXISTS feedback_update_own ON feedback")
    op.execute("DROP POLICY IF EXISTS feedback_insert_own ON feedback")
    op.execute("DROP POLICY IF EXISTS feedback_select_own ON feedback")
    op.execute("ALTER TABLE feedback DISABLE ROW LEVEL SECURITY")

    # Drop policies and disable RLS on user_preferences
    op.execute("DROP POLICY IF EXISTS user_preferences_own ON user_preferences")
    op.execute("ALTER TABLE user_preferences DISABLE ROW LEVEL SECURITY")

    # Drop policies and disable RLS on users
    op.execute("DROP POLICY IF EXISTS users_update_own ON users")
    op.execute("DROP POLICY IF EXISTS users_select_own ON users")
    op.execute("ALTER TABLE users DISABLE ROW LEVEL SECURITY")

    print("RLS Phase 2 removed - User-scoped tables RLS disabled")
