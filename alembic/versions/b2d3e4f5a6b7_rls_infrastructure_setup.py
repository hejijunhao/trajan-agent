"""RLS infrastructure setup

Revision ID: b2d3e4f5a6b7
Revises: a1cd5082aa4a
Create Date: 2026-01-16 18:00:00.000000

This migration sets up the infrastructure for Row-Level Security (RLS):

1. Creates the app_user_id() helper function that RLS policies will use
   to get the current authenticated user from the session context.

2. Documents the app.current_user_id session variable convention.

3. Verifies that service_role has BYPASSRLS (Supabase default).

The app.current_user_id variable is set via SET LOCAL in the application
layer (backend/app/core/rls.py) on each request. RLS policies then use
app_user_id() to check row ownership.

Example usage in RLS policy:
    CREATE POLICY users_select_own ON users
        FOR SELECT
        USING (id = app_user_id());
"""

from typing import Sequence, Union

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "b2d3e4f5a6b7"
down_revision: Union[str, None] = "a1cd5082aa4a"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Set up RLS infrastructure components."""
    # Create helper function for getting current user from session context
    # This function is called by RLS policies to identify the authenticated user
    #
    # Key details:
    # - Uses current_setting() with true flag to return NULL instead of error if not set
    # - STABLE volatility allows PostgreSQL to cache within a transaction
    # - No SECURITY DEFINER needed - runs as current role (which is fine for reading settings)
    #
    # Note: Each statement must be in a separate op.execute() for asyncpg compatibility
    op.execute("""
        CREATE OR REPLACE FUNCTION app_user_id()
        RETURNS UUID AS $$
            SELECT NULLIF(current_setting('app.current_user_id', true), '')::uuid;
        $$ LANGUAGE sql STABLE
    """)

    op.execute("""
        COMMENT ON FUNCTION app_user_id() IS
            'Returns the current authenticated user ID from session context. '
            'Set via SET LOCAL app.current_user_id = uuid in the application layer. '
            'Returns NULL if not set. Used in RLS policies for row filtering.'
    """)

    # Verify service_role has BYPASSRLS for admin/migration operations
    # In Supabase, service_role has this by default, but we verify to be safe
    op.execute("""
        DO $$
        BEGIN
            IF EXISTS (
                SELECT 1 FROM pg_roles
                WHERE rolname = 'service_role' AND rolbypassrls = false
            ) THEN
                ALTER ROLE service_role BYPASSRLS;
                RAISE NOTICE 'Granted BYPASSRLS to service_role';
            END IF;
        END $$
    """)

    print("RLS infrastructure setup complete:")
    print("  - Created app_user_id() helper function")
    print("  - Verified service_role BYPASSRLS")


def downgrade() -> None:
    """Remove RLS infrastructure components."""
    # Drop the helper function
    op.execute("DROP FUNCTION IF EXISTS app_user_id()")

    print("RLS infrastructure removed")
