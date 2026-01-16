"""RLS Phase 3: Organization tables

Revision ID: 34919330fd9b
Revises: c3e4f5a6b7c8
Create Date: 2026-01-16 21:12:44.393448

This migration enables Row-Level Security on organization-scoped tables:

1. organizations - Members can view, owners can manage
2. organization_members - Members can view, admins can manage
3. subscriptions - Members can view, admins can update
4. usage_snapshots - Members can view only (system managed)
5. billing_events - Admins can view only (system managed)

Helper functions created:
- is_org_member(org_id) - Check if current user is a member of the org
- is_org_admin(org_id) - Check if current user is admin or owner
- is_org_owner(org_id) - Check if current user is the owner

All helper functions use SECURITY DEFINER to avoid recursive RLS checks
when querying organization_members from within RLS policies.
"""

from collections.abc import Sequence

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "34919330fd9b"
down_revision: str | None = "c3e4f5a6b7c8"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Enable RLS on organization-scoped tables with appropriate policies."""

    # =========================================================================
    # HELPER FUNCTIONS
    # =========================================================================
    # These functions are used by RLS policies to check organization membership.
    # They use SECURITY DEFINER to run as the function owner (postgres), which
    # bypasses RLS on organization_members. This prevents infinite recursion
    # when RLS policies on organization_members call these functions.
    # =========================================================================

    # Helper: Check if current user is a member of the organization
    op.execute("""
        CREATE OR REPLACE FUNCTION is_org_member(p_org_id UUID)
        RETURNS BOOLEAN AS $$
            SELECT EXISTS (
                SELECT 1 FROM organization_members
                WHERE organization_id = p_org_id
                AND user_id = app_user_id()
            );
        $$ LANGUAGE sql STABLE SECURITY DEFINER
    """)

    op.execute("""
        COMMENT ON FUNCTION is_org_member(UUID) IS
            'Returns TRUE if the current user (from app_user_id()) is a member of '
            'the specified organization. Used in RLS policies for org-scoped tables.'
    """)

    # Helper: Check if current user is an admin or owner of the organization
    op.execute("""
        CREATE OR REPLACE FUNCTION is_org_admin(p_org_id UUID)
        RETURNS BOOLEAN AS $$
            SELECT EXISTS (
                SELECT 1 FROM organization_members
                WHERE organization_id = p_org_id
                AND user_id = app_user_id()
                AND role IN ('owner', 'admin')
            );
        $$ LANGUAGE sql STABLE SECURITY DEFINER
    """)

    op.execute("""
        COMMENT ON FUNCTION is_org_admin(UUID) IS
            'Returns TRUE if the current user is an admin or owner of the '
            'specified organization. Used for elevated permission checks in RLS.'
    """)

    # Helper: Check if current user is the owner of the organization
    op.execute("""
        CREATE OR REPLACE FUNCTION is_org_owner(p_org_id UUID)
        RETURNS BOOLEAN AS $$
            SELECT EXISTS (
                SELECT 1 FROM organization_members
                WHERE organization_id = p_org_id
                AND user_id = app_user_id()
                AND role = 'owner'
            );
        $$ LANGUAGE sql STABLE SECURITY DEFINER
    """)

    op.execute("""
        COMMENT ON FUNCTION is_org_owner(UUID) IS
            'Returns TRUE if the current user is the owner of the specified '
            'organization. Used for owner-only operations like deleting org.'
    """)

    # =========================================================================
    # 1. ORGANIZATIONS TABLE
    # =========================================================================
    # Members can view their organizations.
    # Only owners can update or delete organizations.
    # Users can create organizations (they become owner via application logic).
    # =========================================================================

    op.execute("ALTER TABLE organizations ENABLE ROW LEVEL SECURITY")

    # Policy: Members can view organizations they belong to
    op.execute("""
        CREATE POLICY organizations_member_select ON organizations
            FOR SELECT
            USING (is_org_member(id))
    """)

    # Policy: Users can create organizations
    # The owner_id must match the current user (enforced by app, validated by RLS)
    op.execute("""
        CREATE POLICY organizations_insert ON organizations
            FOR INSERT
            WITH CHECK (owner_id = app_user_id())
    """)

    # Policy: Only owners can update organization settings
    op.execute("""
        CREATE POLICY organizations_owner_update ON organizations
            FOR UPDATE
            USING (is_org_owner(id))
            WITH CHECK (is_org_owner(id))
    """)

    # Policy: Only owners can delete organizations
    op.execute("""
        CREATE POLICY organizations_owner_delete ON organizations
            FOR DELETE
            USING (is_org_owner(id))
    """)

    # =========================================================================
    # 2. ORGANIZATION_MEMBERS TABLE
    # =========================================================================
    # Members can view the membership list of their organizations.
    # Admins can add and remove members.
    # Admins can update member roles (with app-level restrictions on promotion).
    # =========================================================================

    op.execute("ALTER TABLE organization_members ENABLE ROW LEVEL SECURITY")

    # Policy: Members can view membership list of their organizations
    op.execute("""
        CREATE POLICY org_members_member_select ON organization_members
            FOR SELECT
            USING (is_org_member(organization_id))
    """)

    # Policy: Admins can add new members
    op.execute("""
        CREATE POLICY org_members_admin_insert ON organization_members
            FOR INSERT
            WITH CHECK (is_org_admin(organization_id))
    """)

    # Policy: Admins can update member roles
    # Note: App-level logic prevents admins from promoting above their own level
    op.execute("""
        CREATE POLICY org_members_admin_update ON organization_members
            FOR UPDATE
            USING (is_org_admin(organization_id))
            WITH CHECK (is_org_admin(organization_id))
    """)

    # Policy: Admins can remove members
    # Note: App-level logic prevents removing the last owner
    op.execute("""
        CREATE POLICY org_members_admin_delete ON organization_members
            FOR DELETE
            USING (is_org_admin(organization_id))
    """)

    # Policy: Members can remove themselves (leave org)
    op.execute("""
        CREATE POLICY org_members_self_delete ON organization_members
            FOR DELETE
            USING (user_id = app_user_id())
    """)

    # =========================================================================
    # 3. SUBSCRIPTIONS TABLE
    # =========================================================================
    # Members can view their organization's subscription.
    # Admins can update subscription settings (app-level plan changes).
    # Insert/delete handled by system (triggers, webhooks) with service role.
    # =========================================================================

    op.execute("ALTER TABLE subscriptions ENABLE ROW LEVEL SECURITY")

    # Policy: Members can view their organization's subscription
    op.execute("""
        CREATE POLICY subscriptions_member_select ON subscriptions
            FOR SELECT
            USING (is_org_member(organization_id))
    """)

    # Policy: Admins can update subscription (e.g., cancel, change settings)
    # Note: Plan upgrades/downgrades go through Stripe webhooks with service role
    op.execute("""
        CREATE POLICY subscriptions_admin_update ON subscriptions
            FOR UPDATE
            USING (is_org_admin(organization_id))
            WITH CHECK (is_org_admin(organization_id))
    """)

    # Note: No INSERT/DELETE policies for regular users
    # Subscriptions are created by the system (auth trigger creates default sub)
    # and deleted via cascading delete when organization is deleted

    # =========================================================================
    # 4. USAGE_SNAPSHOTS TABLE
    # =========================================================================
    # Members can view usage snapshots (read-only).
    # Insert/update/delete handled by system jobs with service role.
    # =========================================================================

    op.execute("ALTER TABLE usage_snapshots ENABLE ROW LEVEL SECURITY")

    # Policy: Members can view usage snapshots for their organizations
    op.execute("""
        CREATE POLICY usage_snapshots_member_select ON usage_snapshots
            FOR SELECT
            USING (is_org_member(organization_id))
    """)

    # Note: No INSERT/UPDATE/DELETE policies for regular users
    # Usage snapshots are created by background jobs with service role

    # =========================================================================
    # 5. BILLING_EVENTS TABLE
    # =========================================================================
    # Only admins can view billing history (contains payment info).
    # Insert handled by system (webhooks, triggers) with service role.
    # =========================================================================

    op.execute("ALTER TABLE billing_events ENABLE ROW LEVEL SECURITY")

    # Policy: Admins can view billing history for their organizations
    op.execute("""
        CREATE POLICY billing_events_admin_select ON billing_events
            FOR SELECT
            USING (is_org_admin(organization_id))
    """)

    # Note: No INSERT/UPDATE/DELETE policies for regular users
    # Billing events are created by the system (Stripe webhooks, triggers)

    print("RLS Phase 3 complete - Organization tables:")
    print("  - Helper functions: is_org_member(), is_org_admin(), is_org_owner()")
    print("  - organizations: Member view, owner manage")
    print("  - organization_members: Member view, admin manage")
    print("  - subscriptions: Member view, admin update")
    print("  - usage_snapshots: Member view only")
    print("  - billing_events: Admin view only")


def downgrade() -> None:
    """Remove RLS from organization-scoped tables."""

    # Disable RLS and drop policies on billing_events
    op.execute("DROP POLICY IF EXISTS billing_events_admin_select ON billing_events")
    op.execute("ALTER TABLE billing_events DISABLE ROW LEVEL SECURITY")

    # Disable RLS and drop policies on usage_snapshots
    op.execute("DROP POLICY IF EXISTS usage_snapshots_member_select ON usage_snapshots")
    op.execute("ALTER TABLE usage_snapshots DISABLE ROW LEVEL SECURITY")

    # Disable RLS and drop policies on subscriptions
    op.execute("DROP POLICY IF EXISTS subscriptions_admin_update ON subscriptions")
    op.execute("DROP POLICY IF EXISTS subscriptions_member_select ON subscriptions")
    op.execute("ALTER TABLE subscriptions DISABLE ROW LEVEL SECURITY")

    # Disable RLS and drop policies on organization_members
    op.execute("DROP POLICY IF EXISTS org_members_self_delete ON organization_members")
    op.execute("DROP POLICY IF EXISTS org_members_admin_delete ON organization_members")
    op.execute("DROP POLICY IF EXISTS org_members_admin_update ON organization_members")
    op.execute("DROP POLICY IF EXISTS org_members_admin_insert ON organization_members")
    op.execute("DROP POLICY IF EXISTS org_members_member_select ON organization_members")
    op.execute("ALTER TABLE organization_members DISABLE ROW LEVEL SECURITY")

    # Disable RLS and drop policies on organizations
    op.execute("DROP POLICY IF EXISTS organizations_owner_delete ON organizations")
    op.execute("DROP POLICY IF EXISTS organizations_owner_update ON organizations")
    op.execute("DROP POLICY IF EXISTS organizations_insert ON organizations")
    op.execute("DROP POLICY IF EXISTS organizations_member_select ON organizations")
    op.execute("ALTER TABLE organizations DISABLE ROW LEVEL SECURITY")

    # Drop helper functions
    op.execute("DROP FUNCTION IF EXISTS is_org_owner(UUID)")
    op.execute("DROP FUNCTION IF EXISTS is_org_admin(UUID)")
    op.execute("DROP FUNCTION IF EXISTS is_org_member(UUID)")

    print("RLS Phase 3 removed - Organization tables RLS disabled")
