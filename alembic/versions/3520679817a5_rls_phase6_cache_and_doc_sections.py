"""RLS Phase 6: Cache tables and document sections

Revision ID: 3520679817a5
Revises: g7b8c9d0e1f2
Create Date: 2026-01-26 09:18:34.652075

Enables Row-Level Security on:
1. progress_summary - AI-generated progress narratives (product-scoped, read-only for users)
2. document_sections - Document organization structure (product-scoped)
3. document_subsections - Nested document structure (inherits from parent section)
4. commit_stats_cache - Git commit statistics cache (system-wide read, service role writes)

Security Model:
- progress_summary: Viewers can read summaries for products they can view. System manages writes.
- document_sections: Viewers can read, editors can manage sections.
- document_subsections: Access inherited from parent section's product.
- commit_stats_cache: Public read (immutable Git data), writes restricted to service role.
"""

from collections.abc import Sequence

from alembic import op

revision: str = "3520679817a5"
down_revision: str | None = "g7b8c9d0e1f2"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # ==========================================================================
    # PROGRESS_SUMMARY TABLE
    # ==========================================================================
    # AI-generated progress summaries per product-period. System-managed cache.
    # Users: read-only for products they can view
    # Writes: service role only (background jobs)
    # ==========================================================================
    op.execute("ALTER TABLE progress_summary ENABLE ROW LEVEL SECURITY")

    # Viewers can read summaries for products they have access to
    op.execute("""
        CREATE POLICY progress_summary_viewer_select ON progress_summary
            FOR SELECT
            USING (can_view_product(product_id))
    """)

    # No INSERT/UPDATE/DELETE policies - writes go through service role (BYPASSRLS)

    # ==========================================================================
    # DOCUMENT_SECTIONS TABLE
    # ==========================================================================
    # Top-level document organization (e.g., "Getting Started", "API Reference").
    # Product-scoped: sections belong to a product.
    # ==========================================================================
    op.execute("ALTER TABLE document_sections ENABLE ROW LEVEL SECURITY")

    # Viewers can see sections for products they can view
    op.execute("""
        CREATE POLICY document_sections_viewer_select ON document_sections
            FOR SELECT
            USING (can_view_product(product_id))
    """)

    # Editors can create new sections
    op.execute("""
        CREATE POLICY document_sections_editor_insert ON document_sections
            FOR INSERT
            WITH CHECK (can_edit_product(product_id))
    """)

    # Editors can update sections (rename, reorder, change icon/color)
    op.execute("""
        CREATE POLICY document_sections_editor_update ON document_sections
            FOR UPDATE
            USING (can_edit_product(product_id))
            WITH CHECK (can_edit_product(product_id))
    """)

    # Editors can delete sections
    op.execute("""
        CREATE POLICY document_sections_editor_delete ON document_sections
            FOR DELETE
            USING (can_edit_product(product_id))
    """)

    # ==========================================================================
    # DOCUMENT_SUBSECTIONS TABLE
    # ==========================================================================
    # Nested under document_sections. Access inherited via parent section.
    # Requires JOIN to document_sections to resolve product_id.
    # ==========================================================================
    op.execute("ALTER TABLE document_subsections ENABLE ROW LEVEL SECURITY")

    # Viewers can see subsections for sections they can view
    op.execute("""
        CREATE POLICY document_subsections_viewer_select ON document_subsections
            FOR SELECT
            USING (
                EXISTS (
                    SELECT 1 FROM document_sections ds
                    WHERE ds.id = document_subsections.section_id
                    AND can_view_product(ds.product_id)
                )
            )
    """)

    # Editors can create subsections
    op.execute("""
        CREATE POLICY document_subsections_editor_insert ON document_subsections
            FOR INSERT
            WITH CHECK (
                EXISTS (
                    SELECT 1 FROM document_sections ds
                    WHERE ds.id = section_id
                    AND can_edit_product(ds.product_id)
                )
            )
    """)

    # Editors can update subsections
    op.execute("""
        CREATE POLICY document_subsections_editor_update ON document_subsections
            FOR UPDATE
            USING (
                EXISTS (
                    SELECT 1 FROM document_sections ds
                    WHERE ds.id = document_subsections.section_id
                    AND can_edit_product(ds.product_id)
                )
            )
            WITH CHECK (
                EXISTS (
                    SELECT 1 FROM document_sections ds
                    WHERE ds.id = section_id
                    AND can_edit_product(ds.product_id)
                )
            )
    """)

    # Editors can delete subsections
    op.execute("""
        CREATE POLICY document_subsections_editor_delete ON document_subsections
            FOR DELETE
            USING (
                EXISTS (
                    SELECT 1 FROM document_sections ds
                    WHERE ds.id = document_subsections.section_id
                    AND can_edit_product(ds.product_id)
                )
            )
    """)

    # ==========================================================================
    # COMMIT_STATS_CACHE TABLE
    # ==========================================================================
    # System-wide cache of Git commit statistics. Keyed by (repo, SHA).
    # Data is immutable and not user-specific - same stats for everyone.
    # Read: permissive (any authenticated user)
    # Write: service role only (background sync jobs)
    # ==========================================================================
    op.execute("ALTER TABLE commit_stats_cache ENABLE ROW LEVEL SECURITY")

    # Any authenticated user can read cached commit stats
    # This is safe because Git commit data is public within the org context,
    # and the stats themselves don't contain sensitive information.
    op.execute("""
        CREATE POLICY commit_stats_cache_authenticated_select ON commit_stats_cache
            FOR SELECT
            USING (app_user_id() IS NOT NULL)
    """)

    # No INSERT/UPDATE/DELETE policies - writes go through service role (BYPASSRLS)
    # This ensures only background jobs can populate the cache.

    print(
        "RLS Phase 6 complete - progress_summary, document_sections, "
        "document_subsections, commit_stats_cache"
    )


def downgrade() -> None:
    # === COMMIT_STATS_CACHE ===
    op.execute(
        "DROP POLICY IF EXISTS commit_stats_cache_authenticated_select ON commit_stats_cache"
    )
    op.execute("ALTER TABLE commit_stats_cache DISABLE ROW LEVEL SECURITY")

    # === DOCUMENT_SUBSECTIONS ===
    op.execute("DROP POLICY IF EXISTS document_subsections_editor_delete ON document_subsections")
    op.execute("DROP POLICY IF EXISTS document_subsections_editor_update ON document_subsections")
    op.execute("DROP POLICY IF EXISTS document_subsections_editor_insert ON document_subsections")
    op.execute("DROP POLICY IF EXISTS document_subsections_viewer_select ON document_subsections")
    op.execute("ALTER TABLE document_subsections DISABLE ROW LEVEL SECURITY")

    # === DOCUMENT_SECTIONS ===
    op.execute("DROP POLICY IF EXISTS document_sections_editor_delete ON document_sections")
    op.execute("DROP POLICY IF EXISTS document_sections_editor_update ON document_sections")
    op.execute("DROP POLICY IF EXISTS document_sections_editor_insert ON document_sections")
    op.execute("DROP POLICY IF EXISTS document_sections_viewer_select ON document_sections")
    op.execute("ALTER TABLE document_sections DISABLE ROW LEVEL SECURITY")

    # === PROGRESS_SUMMARY ===
    op.execute("DROP POLICY IF EXISTS progress_summary_viewer_select ON progress_summary")
    op.execute("ALTER TABLE progress_summary DISABLE ROW LEVEL SECURITY")

    print("RLS Phase 6 removed")
