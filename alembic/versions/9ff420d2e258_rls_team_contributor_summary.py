"""RLS: team_contributor_summary table

Revision ID: 9ff420d2e258
Revises: a176b3184ce7
Create Date: 2026-03-07 11:18:39.044854

This migration enables Row-Level Security on the team_contributor_summary table.
Follows the org-scoped pattern used for usage_snapshots and subscriptions (Phase 3).

Access model:
- SELECT: is_org_member(organization_id)  (any org member)
- INSERT: is_org_member(organization_id)  (members trigger summary generation)
- UPDATE: is_org_member(organization_id)  (upsert from authenticated endpoints)
- DELETE: is_org_admin(organization_id)   (admin-only cleanup)
"""

from collections.abc import Sequence

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "9ff420d2e258"
down_revision: str | None = "a176b3184ce7"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # Enable RLS on the table
    op.execute("ALTER TABLE team_contributor_summary ENABLE ROW LEVEL SECURITY")

    # SELECT: org members can read summaries for their organization
    op.execute("""
        CREATE POLICY team_contrib_summary_select ON team_contributor_summary
            FOR SELECT
            USING (is_org_member(organization_id))
    """)

    # INSERT: org members can create summaries (triggered by viewing team page)
    op.execute("""
        CREATE POLICY team_contrib_summary_insert ON team_contributor_summary
            FOR INSERT
            WITH CHECK (is_org_member(organization_id))
    """)

    # UPDATE: org members can update summaries (upsert on cache refresh)
    op.execute("""
        CREATE POLICY team_contrib_summary_update ON team_contributor_summary
            FOR UPDATE
            USING (is_org_member(organization_id))
            WITH CHECK (is_org_member(organization_id))
    """)

    # DELETE: only admins can delete summaries (cache cleanup)
    op.execute("""
        CREATE POLICY team_contrib_summary_delete ON team_contributor_summary
            FOR DELETE
            USING (is_org_admin(organization_id))
    """)


def downgrade() -> None:
    op.execute("DROP POLICY IF EXISTS team_contrib_summary_delete ON team_contributor_summary")
    op.execute("DROP POLICY IF EXISTS team_contrib_summary_update ON team_contributor_summary")
    op.execute("DROP POLICY IF EXISTS team_contrib_summary_insert ON team_contributor_summary")
    op.execute("DROP POLICY IF EXISTS team_contrib_summary_select ON team_contributor_summary")
    op.execute("ALTER TABLE team_contributor_summary DISABLE ROW LEVEL SECURITY")
