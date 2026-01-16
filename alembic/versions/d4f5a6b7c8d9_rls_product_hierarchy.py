"""RLS Phase 4: Product hierarchy tables

Revision ID: d4f5a6b7c8d9
Revises: 34919330fd9b
Create Date: 2026-01-16 22:30:00.000000

This migration enables Row-Level Security on product-scoped tables:

1. products - View/update/delete based on product access level
2. repositories - View/edit via product access
3. work_items - View/edit via product access
4. documents - View/edit via product access
5. app_info - Editor+ only (contains secrets)

Helper functions created:
- has_product_access(product_id, min_level) - Comprehensive access check
- can_view_product(product_id) - Shorthand for viewer access
- can_edit_product(product_id) - Shorthand for editor access
- can_admin_product(product_id) - Shorthand for admin access

Access hierarchy:
- Org owners/admins: automatic admin access to all products in their org
- Explicit ProductAccess: viewer/editor/admin grants
- Org members without explicit access: no access (must be explicitly added)
"""

from collections.abc import Sequence

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "d4f5a6b7c8d9"
down_revision: str | None = "34919330fd9b"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Enable RLS on product-scoped tables with appropriate policies."""

    # =========================================================================
    # HELPER FUNCTIONS
    # =========================================================================
    # These functions check product access based on:
    # 1. Organization role (owners/admins get automatic admin access)
    # 2. Explicit ProductAccess grants (viewer/editor/admin)
    #
    # All use SECURITY DEFINER to bypass RLS when querying related tables.
    # =========================================================================

    # Main helper: Comprehensive product access check with level comparison
    op.execute("""
        CREATE OR REPLACE FUNCTION has_product_access(
            p_product_id UUID,
            p_min_level TEXT DEFAULT 'viewer'
        )
        RETURNS BOOLEAN AS $$
        DECLARE
            v_user_id UUID := app_user_id();
            v_org_id UUID;
            v_org_role TEXT;
            v_explicit_level TEXT;
            v_level_rank INTEGER;
            v_min_rank INTEGER;
        BEGIN
            -- Handle NULL user (no context set)
            IF v_user_id IS NULL THEN
                RETURN FALSE;
            END IF;

            -- Rank levels for comparison (higher = more access)
            v_min_rank := CASE p_min_level
                WHEN 'viewer' THEN 1
                WHEN 'editor' THEN 2
                WHEN 'admin' THEN 3
                ELSE 0
            END;

            -- Get product's organization
            SELECT organization_id INTO v_org_id
            FROM products WHERE id = p_product_id;

            IF v_org_id IS NULL THEN
                RETURN FALSE;  -- Product doesn't exist or no org
            END IF;

            -- Check org role (owners/admins get automatic admin access)
            SELECT role INTO v_org_role
            FROM organization_members
            WHERE organization_id = v_org_id AND user_id = v_user_id;

            IF v_org_role IN ('owner', 'admin') THEN
                RETURN TRUE;  -- Org admins have full access to all products
            END IF;

            -- Check explicit product access
            SELECT access_level INTO v_explicit_level
            FROM product_access
            WHERE product_id = p_product_id AND user_id = v_user_id;

            IF v_explicit_level IS NOT NULL THEN
                -- Check for explicit denial
                IF v_explicit_level = 'none' THEN
                    RETURN FALSE;
                END IF;

                v_level_rank := CASE v_explicit_level
                    WHEN 'viewer' THEN 1
                    WHEN 'editor' THEN 2
                    WHEN 'admin' THEN 3
                    ELSE 0
                END;
                RETURN v_level_rank >= v_min_rank;
            END IF;

            -- No explicit access and not an org admin = no access
            RETURN FALSE;
        END;
        $$ LANGUAGE plpgsql STABLE SECURITY DEFINER
    """)

    op.execute("""
        COMMENT ON FUNCTION has_product_access(UUID, TEXT) IS
            'Checks if the current user has at least the specified access level to a product. '
            'Org owners/admins automatically have admin access. Others need explicit ProductAccess.'
    """)

    # Shorthand helpers for common access level checks
    op.execute("""
        CREATE OR REPLACE FUNCTION can_view_product(p_product_id UUID)
        RETURNS BOOLEAN AS $$
            SELECT has_product_access(p_product_id, 'viewer');
        $$ LANGUAGE sql STABLE
    """)

    op.execute("""
        COMMENT ON FUNCTION can_view_product(UUID) IS
            'Shorthand for has_product_access(product_id, ''viewer''). '
            'Returns TRUE if user can view the product.'
    """)

    op.execute("""
        CREATE OR REPLACE FUNCTION can_edit_product(p_product_id UUID)
        RETURNS BOOLEAN AS $$
            SELECT has_product_access(p_product_id, 'editor');
        $$ LANGUAGE sql STABLE
    """)

    op.execute("""
        COMMENT ON FUNCTION can_edit_product(UUID) IS
            'Shorthand for has_product_access(product_id, ''editor''). '
            'Returns TRUE if user can edit the product and access variables.'
    """)

    op.execute("""
        CREATE OR REPLACE FUNCTION can_admin_product(p_product_id UUID)
        RETURNS BOOLEAN AS $$
            SELECT has_product_access(p_product_id, 'admin');
        $$ LANGUAGE sql STABLE
    """)

    op.execute("""
        COMMENT ON FUNCTION can_admin_product(UUID) IS
            'Shorthand for has_product_access(product_id, ''admin''). '
            'Returns TRUE if user can manage product settings and collaborators.'
    """)

    # =========================================================================
    # 1. PRODUCTS TABLE
    # =========================================================================
    # - Viewers can view products they have access to
    # - Editors can update products
    # - Org members can create products in their org
    # - Admins can delete products
    # =========================================================================

    op.execute("ALTER TABLE products ENABLE ROW LEVEL SECURITY")

    # Policy: Users with access can view products
    op.execute("""
        CREATE POLICY products_view ON products
            FOR SELECT
            USING (can_view_product(id))
    """)

    # Policy: Editors can update products
    op.execute("""
        CREATE POLICY products_update ON products
            FOR UPDATE
            USING (can_edit_product(id))
            WITH CHECK (can_edit_product(id))
    """)

    # Policy: Org members can create products in their org
    # The user_id must match current user, and they must be an org member
    op.execute("""
        CREATE POLICY products_insert ON products
            FOR INSERT
            WITH CHECK (
                is_org_member(organization_id)
                AND user_id = app_user_id()
            )
    """)

    # Policy: Admins can delete products
    op.execute("""
        CREATE POLICY products_delete ON products
            FOR DELETE
            USING (can_admin_product(id))
    """)

    # =========================================================================
    # 2. REPOSITORIES TABLE
    # =========================================================================
    # - Viewers can view repos of products they can view
    # - Editors can manage repos (create/update/delete)
    # =========================================================================

    op.execute("ALTER TABLE repositories ENABLE ROW LEVEL SECURITY")

    # Policy: Product viewers can view repos
    op.execute("""
        CREATE POLICY repositories_view ON repositories
            FOR SELECT
            USING (can_view_product(product_id))
    """)

    # Policy: Product editors can insert repos
    op.execute("""
        CREATE POLICY repositories_insert ON repositories
            FOR INSERT
            WITH CHECK (can_edit_product(product_id))
    """)

    # Policy: Product editors can update repos
    op.execute("""
        CREATE POLICY repositories_update ON repositories
            FOR UPDATE
            USING (can_edit_product(product_id))
            WITH CHECK (can_edit_product(product_id))
    """)

    # Policy: Product editors can delete repos
    op.execute("""
        CREATE POLICY repositories_delete ON repositories
            FOR DELETE
            USING (can_edit_product(product_id))
    """)

    # =========================================================================
    # 3. WORK_ITEMS TABLE
    # =========================================================================
    # - Viewers can view work items
    # - Editors can manage work items (create/update/delete)
    # =========================================================================

    op.execute("ALTER TABLE work_items ENABLE ROW LEVEL SECURITY")

    # Policy: Product viewers can view work items
    op.execute("""
        CREATE POLICY work_items_view ON work_items
            FOR SELECT
            USING (can_view_product(product_id))
    """)

    # Policy: Product editors can insert work items
    op.execute("""
        CREATE POLICY work_items_insert ON work_items
            FOR INSERT
            WITH CHECK (can_edit_product(product_id))
    """)

    # Policy: Product editors can update work items
    op.execute("""
        CREATE POLICY work_items_update ON work_items
            FOR UPDATE
            USING (can_edit_product(product_id))
            WITH CHECK (can_edit_product(product_id))
    """)

    # Policy: Product editors can delete work items
    op.execute("""
        CREATE POLICY work_items_delete ON work_items
            FOR DELETE
            USING (can_edit_product(product_id))
    """)

    # =========================================================================
    # 4. DOCUMENTS TABLE
    # =========================================================================
    # - Viewers can view documents
    # - Editors can manage documents (create/update/delete)
    # =========================================================================

    op.execute("ALTER TABLE documents ENABLE ROW LEVEL SECURITY")

    # Policy: Product viewers can view documents
    op.execute("""
        CREATE POLICY documents_view ON documents
            FOR SELECT
            USING (can_view_product(product_id))
    """)

    # Policy: Product editors can insert documents
    op.execute("""
        CREATE POLICY documents_insert ON documents
            FOR INSERT
            WITH CHECK (can_edit_product(product_id))
    """)

    # Policy: Product editors can update documents
    op.execute("""
        CREATE POLICY documents_update ON documents
            FOR UPDATE
            USING (can_edit_product(product_id))
            WITH CHECK (can_edit_product(product_id))
    """)

    # Policy: Product editors can delete documents
    op.execute("""
        CREATE POLICY documents_delete ON documents
            FOR DELETE
            USING (can_edit_product(product_id))
    """)

    # =========================================================================
    # 5. APP_INFO TABLE
    # =========================================================================
    # IMPORTANT: Contains secrets - ONLY editors/admins can access!
    # Viewers are explicitly denied access to protect sensitive data.
    # =========================================================================

    op.execute("ALTER TABLE app_info ENABLE ROW LEVEL SECURITY")

    # Policy: ONLY editors/admins can view app_info (no viewer access)
    # This is intentional for security - secrets should not be visible to viewers
    op.execute("""
        CREATE POLICY app_info_editor_select ON app_info
            FOR SELECT
            USING (can_edit_product(product_id))
    """)

    # Policy: Editors can insert app_info
    op.execute("""
        CREATE POLICY app_info_editor_insert ON app_info
            FOR INSERT
            WITH CHECK (can_edit_product(product_id))
    """)

    # Policy: Editors can update app_info
    op.execute("""
        CREATE POLICY app_info_editor_update ON app_info
            FOR UPDATE
            USING (can_edit_product(product_id))
            WITH CHECK (can_edit_product(product_id))
    """)

    # Policy: Editors can delete app_info
    op.execute("""
        CREATE POLICY app_info_editor_delete ON app_info
            FOR DELETE
            USING (can_edit_product(product_id))
    """)

    print("RLS Phase 4 complete - Product hierarchy tables:")
    print("  - Helper functions: has_product_access(), can_view/edit/admin_product()")
    print("  - products: View/update/insert/delete based on access level")
    print("  - repositories: View for viewers, edit for editors")
    print("  - work_items: View for viewers, edit for editors")
    print("  - documents: View for viewers, edit for editors")
    print("  - app_info: Editor+ only (contains secrets)")


def downgrade() -> None:
    """Remove RLS from product-scoped tables."""

    # Disable RLS and drop policies on app_info
    op.execute("DROP POLICY IF EXISTS app_info_editor_delete ON app_info")
    op.execute("DROP POLICY IF EXISTS app_info_editor_update ON app_info")
    op.execute("DROP POLICY IF EXISTS app_info_editor_insert ON app_info")
    op.execute("DROP POLICY IF EXISTS app_info_editor_select ON app_info")
    op.execute("ALTER TABLE app_info DISABLE ROW LEVEL SECURITY")

    # Disable RLS and drop policies on documents
    op.execute("DROP POLICY IF EXISTS documents_delete ON documents")
    op.execute("DROP POLICY IF EXISTS documents_update ON documents")
    op.execute("DROP POLICY IF EXISTS documents_insert ON documents")
    op.execute("DROP POLICY IF EXISTS documents_view ON documents")
    op.execute("ALTER TABLE documents DISABLE ROW LEVEL SECURITY")

    # Disable RLS and drop policies on work_items
    op.execute("DROP POLICY IF EXISTS work_items_delete ON work_items")
    op.execute("DROP POLICY IF EXISTS work_items_update ON work_items")
    op.execute("DROP POLICY IF EXISTS work_items_insert ON work_items")
    op.execute("DROP POLICY IF EXISTS work_items_view ON work_items")
    op.execute("ALTER TABLE work_items DISABLE ROW LEVEL SECURITY")

    # Disable RLS and drop policies on repositories
    op.execute("DROP POLICY IF EXISTS repositories_delete ON repositories")
    op.execute("DROP POLICY IF EXISTS repositories_update ON repositories")
    op.execute("DROP POLICY IF EXISTS repositories_insert ON repositories")
    op.execute("DROP POLICY IF EXISTS repositories_view ON repositories")
    op.execute("ALTER TABLE repositories DISABLE ROW LEVEL SECURITY")

    # Disable RLS and drop policies on products
    op.execute("DROP POLICY IF EXISTS products_delete ON products")
    op.execute("DROP POLICY IF EXISTS products_insert ON products")
    op.execute("DROP POLICY IF EXISTS products_update ON products")
    op.execute("DROP POLICY IF EXISTS products_view ON products")
    op.execute("ALTER TABLE products DISABLE ROW LEVEL SECURITY")

    # Drop helper functions
    op.execute("DROP FUNCTION IF EXISTS can_admin_product(UUID)")
    op.execute("DROP FUNCTION IF EXISTS can_edit_product(UUID)")
    op.execute("DROP FUNCTION IF EXISTS can_view_product(UUID)")
    op.execute("DROP FUNCTION IF EXISTS has_product_access(UUID, TEXT)")

    print("RLS Phase 4 removed - Product hierarchy tables RLS disabled")
