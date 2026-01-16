"""RLS Phase 5: Complex access control tables

Revision ID: 9aca077d5d1d
Revises: d4f5a6b7c8d9
Create Date: 2026-01-16 21:31:52.329502

Enables Row-Level Security on:
1. product_access - Access grants management
2. custom_doc_jobs - Background doc generation jobs
3. referrals - Referral program tracking
"""

from collections.abc import Sequence

from alembic import op

revision: str = "9aca077d5d1d"
down_revision: str | None = "d4f5a6b7c8d9"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # === PRODUCT_ACCESS TABLE ===
    op.execute("ALTER TABLE product_access ENABLE ROW LEVEL SECURITY")

    op.execute("""
        CREATE POLICY product_access_own_select ON product_access
            FOR SELECT USING (user_id = app_user_id())
    """)
    op.execute("""
        CREATE POLICY product_access_admin_select ON product_access
            FOR SELECT USING (can_admin_product(product_id))
    """)
    op.execute("""
        CREATE POLICY product_access_admin_insert ON product_access
            FOR INSERT WITH CHECK (can_admin_product(product_id))
    """)
    op.execute("""
        CREATE POLICY product_access_admin_update ON product_access
            FOR UPDATE
            USING (can_admin_product(product_id))
            WITH CHECK (can_admin_product(product_id))
    """)
    op.execute("""
        CREATE POLICY product_access_admin_delete ON product_access
            FOR DELETE USING (can_admin_product(product_id))
    """)

    # === CUSTOM_DOC_JOBS TABLE ===
    op.execute("ALTER TABLE custom_doc_jobs ENABLE ROW LEVEL SECURITY")

    op.execute("""
        CREATE POLICY custom_doc_jobs_own_select ON custom_doc_jobs
            FOR SELECT USING (user_id = app_user_id())
    """)
    op.execute("""
        CREATE POLICY custom_doc_jobs_product_select ON custom_doc_jobs
            FOR SELECT USING (can_edit_product(product_id))
    """)
    op.execute("""
        CREATE POLICY custom_doc_jobs_insert ON custom_doc_jobs
            FOR INSERT
            WITH CHECK (can_edit_product(product_id) AND user_id = app_user_id())
    """)
    op.execute("""
        CREATE POLICY custom_doc_jobs_own_update ON custom_doc_jobs
            FOR UPDATE
            USING (user_id = app_user_id())
            WITH CHECK (user_id = app_user_id())
    """)
    op.execute("""
        CREATE POLICY custom_doc_jobs_own_delete ON custom_doc_jobs
            FOR DELETE USING (user_id = app_user_id())
    """)

    # === REFERRALS TABLE ===
    op.execute("ALTER TABLE referrals ENABLE ROW LEVEL SECURITY")

    op.execute("""
        CREATE POLICY referrals_referrer_view ON referrals
            FOR SELECT USING (is_org_member(referrer_org_id))
    """)
    op.execute("""
        CREATE POLICY referrals_admin_insert ON referrals
            FOR INSERT WITH CHECK (is_org_admin(referrer_org_id))
    """)

    print("RLS Phase 5 complete - product_access, custom_doc_jobs, referrals")


def downgrade() -> None:
    # Referrals
    op.execute("DROP POLICY IF EXISTS referrals_admin_insert ON referrals")
    op.execute("DROP POLICY IF EXISTS referrals_referrer_view ON referrals")
    op.execute("ALTER TABLE referrals DISABLE ROW LEVEL SECURITY")

    # Custom doc jobs
    op.execute("DROP POLICY IF EXISTS custom_doc_jobs_own_delete ON custom_doc_jobs")
    op.execute("DROP POLICY IF EXISTS custom_doc_jobs_own_update ON custom_doc_jobs")
    op.execute("DROP POLICY IF EXISTS custom_doc_jobs_insert ON custom_doc_jobs")
    op.execute("DROP POLICY IF EXISTS custom_doc_jobs_product_select ON custom_doc_jobs")
    op.execute("DROP POLICY IF EXISTS custom_doc_jobs_own_select ON custom_doc_jobs")
    op.execute("ALTER TABLE custom_doc_jobs DISABLE ROW LEVEL SECURITY")

    # Product access
    op.execute("DROP POLICY IF EXISTS product_access_admin_delete ON product_access")
    op.execute("DROP POLICY IF EXISTS product_access_admin_update ON product_access")
    op.execute("DROP POLICY IF EXISTS product_access_admin_insert ON product_access")
    op.execute("DROP POLICY IF EXISTS product_access_admin_select ON product_access")
    op.execute("DROP POLICY IF EXISTS product_access_own_select ON product_access")
    op.execute("ALTER TABLE product_access DISABLE ROW LEVEL SECURITY")

    print("RLS Phase 5 removed")
