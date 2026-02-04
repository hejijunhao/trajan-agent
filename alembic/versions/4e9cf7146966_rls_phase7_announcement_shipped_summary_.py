"""RLS Phase 7: Announcement, dashboard shipped summary, referral codes

Revision ID: 4e9cf7146966
Revises: 4cd213aad746
Create Date: 2026-02-04 09:51:19.780601

Enables Row-Level Security on:
1. announcement - System-wide banners (authenticated read, service role writes)
2. dashboard_shipped_summary - AI-generated shipped summaries (product-scoped, read-only for users)
3. referral_codes - User-to-user referral codes (owner can view/create, service role manages redemption)

Security Model:
- announcement: Any authenticated user can read active announcements. No user writes.
- dashboard_shipped_summary: Viewers can read summaries for products they can view. System manages writes.
- referral_codes: Users can view and create their own codes. Redemption/conversion managed by service role.
"""

from collections.abc import Sequence

from alembic import op

revision: str = "4e9cf7146966"
down_revision: str | None = "4cd213aad746"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # ==========================================================================
    # ANNOUNCEMENT TABLE
    # ==========================================================================
    # System-wide broadcast banners (info, warning, error).
    # No owner - managed by admins via Supabase dashboard.
    # Users: read-only (any authenticated user)
    # Writes: service role only
    # ==========================================================================
    op.execute("ALTER TABLE announcement ENABLE ROW LEVEL SECURITY")

    # Any authenticated user can read announcements
    op.execute("""
        CREATE POLICY announcement_authenticated_select ON announcement
            FOR SELECT
            USING (app_user_id() IS NOT NULL)
    """)

    # No INSERT/UPDATE/DELETE policies - managed via service role (Supabase dashboard)

    # ==========================================================================
    # DASHBOARD_SHIPPED_SUMMARY TABLE
    # ==========================================================================
    # AI-generated "What Shipped" summaries per product-period. System-managed cache.
    # Users: read-only for products they can view
    # Writes: service role only (background AI jobs)
    # ==========================================================================
    op.execute("ALTER TABLE dashboard_shipped_summary ENABLE ROW LEVEL SECURITY")

    # Viewers can read summaries for products they have access to
    op.execute("""
        CREATE POLICY dashboard_shipped_summary_viewer_select ON dashboard_shipped_summary
            FOR SELECT
            USING (can_view_product(product_id))
    """)

    # No INSERT/UPDATE/DELETE policies - writes go through service role (BYPASSRLS)

    # ==========================================================================
    # REFERRAL_CODES TABLE
    # ==========================================================================
    # User-to-user referral codes. Each user generates codes for friends.
    # Owner can view and create their own codes.
    # Redemption and conversion updates are handled by service role.
    # ==========================================================================
    op.execute("ALTER TABLE referral_codes ENABLE ROW LEVEL SECURITY")

    # Users can view their own referral codes
    op.execute("""
        CREATE POLICY referral_codes_owner_select ON referral_codes
            FOR SELECT
            USING (user_id = app_user_id())
    """)

    # Users can create their own referral codes
    op.execute("""
        CREATE POLICY referral_codes_owner_insert ON referral_codes
            FOR INSERT
            WITH CHECK (user_id = app_user_id())
    """)

    # No UPDATE/DELETE policies - redemption/conversion managed by service role (BYPASSRLS)

    print("RLS Phase 7 complete - announcement, dashboard_shipped_summary, referral_codes")


def downgrade() -> None:
    # === REFERRAL_CODES ===
    op.execute("DROP POLICY IF EXISTS referral_codes_owner_insert ON referral_codes")
    op.execute("DROP POLICY IF EXISTS referral_codes_owner_select ON referral_codes")
    op.execute("ALTER TABLE referral_codes DISABLE ROW LEVEL SECURITY")

    # === DASHBOARD_SHIPPED_SUMMARY ===
    op.execute(
        "DROP POLICY IF EXISTS dashboard_shipped_summary_viewer_select ON dashboard_shipped_summary"
    )
    op.execute("ALTER TABLE dashboard_shipped_summary DISABLE ROW LEVEL SECURITY")

    # === ANNOUNCEMENT ===
    op.execute("DROP POLICY IF EXISTS announcement_authenticated_select ON announcement")
    op.execute("ALTER TABLE announcement DISABLE ROW LEVEL SECURITY")

    print("RLS Phase 7 removed")
