"""RLS Phase 8: Discount codes and discount redemptions

Revision ID: ee4cd3314269
Revises: 46962b59da2e
Create Date: 2026-02-19 01:51:27.948751

Enables Row-Level Security on:
1. discount_codes - Platform-managed discount codes (authenticated read/update, service role creates)
2. discount_redemptions - Org-scoped redemption records (member read, admin insert/delete)

Security Model:
- discount_codes: Any authenticated user can read (needed for validate_code in user session).
  Authenticated users can update (times_redeemed increment, stripe_coupon_id set during redemption).
  No INSERT/DELETE - codes are platform-managed via service role.
- discount_redemptions: Org members can view their org's redemptions.
  Org admins can create and delete redemptions. No UPDATE - redemptions are immutable.
"""

from collections.abc import Sequence

from alembic import op

revision: str = "ee4cd3314269"
down_revision: str | None = "46962b59da2e"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # ==========================================================================
    # DISCOUNT_CODES TABLE
    # ==========================================================================
    # Platform-managed discount codes (percentage-off coupons).
    # No owner column - managed by admins via direct DB or service role.
    # Users: read (validate codes) + update (increment counter, set coupon ID)
    # Creates/deletes: service role only
    # ==========================================================================
    op.execute("ALTER TABLE discount_codes ENABLE ROW LEVEL SECURITY")

    # Any authenticated user can read codes (validate_code runs in user session)
    op.execute("""
        CREATE POLICY discount_codes_authenticated_select ON discount_codes
            FOR SELECT
            USING (app_user_id() IS NOT NULL)
    """)

    # Authenticated users can update (times_redeemed++, stripe_coupon_id set)
    # Table has no organization_id so admin check can't be expressed at RLS level;
    # app layer enforces admin-only access
    op.execute("""
        CREATE POLICY discount_codes_authenticated_update ON discount_codes
            FOR UPDATE
            USING (app_user_id() IS NOT NULL)
            WITH CHECK (app_user_id() IS NOT NULL)
    """)

    # No INSERT/DELETE policies - managed via service role (BYPASSRLS)

    # ==========================================================================
    # DISCOUNT_REDEMPTIONS TABLE
    # ==========================================================================
    # Org-scoped redemption records linking codes to organizations.
    # Immutable audit trail - no updates allowed.
    # Members: read their org's redemptions
    # Admins: create and delete redemptions
    # ==========================================================================
    op.execute("ALTER TABLE discount_redemptions ENABLE ROW LEVEL SECURITY")

    # Org members can see their org's redemptions
    op.execute("""
        CREATE POLICY discount_redemptions_org_member_select ON discount_redemptions
            FOR SELECT
            USING (is_org_member(organization_id))
    """)

    # Org admins can create redemptions (apply discount)
    op.execute("""
        CREATE POLICY discount_redemptions_org_admin_insert ON discount_redemptions
            FOR INSERT
            WITH CHECK (is_org_admin(organization_id))
    """)

    # Org admins can delete redemptions (remove discount)
    op.execute("""
        CREATE POLICY discount_redemptions_org_admin_delete ON discount_redemptions
            FOR DELETE
            USING (is_org_admin(organization_id))
    """)

    print("RLS Phase 8 complete - discount_codes, discount_redemptions")


def downgrade() -> None:
    # === DISCOUNT_REDEMPTIONS ===
    op.execute(
        "DROP POLICY IF EXISTS discount_redemptions_org_admin_delete ON discount_redemptions"
    )
    op.execute(
        "DROP POLICY IF EXISTS discount_redemptions_org_admin_insert ON discount_redemptions"
    )
    op.execute(
        "DROP POLICY IF EXISTS discount_redemptions_org_member_select ON discount_redemptions"
    )
    op.execute("ALTER TABLE discount_redemptions DISABLE ROW LEVEL SECURITY")

    # === DISCOUNT_CODES ===
    op.execute("DROP POLICY IF EXISTS discount_codes_authenticated_update ON discount_codes")
    op.execute("DROP POLICY IF EXISTS discount_codes_authenticated_select ON discount_codes")
    op.execute("ALTER TABLE discount_codes DISABLE ROW LEVEL SECURITY")

    print("RLS Phase 8 removed")
