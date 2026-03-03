"""Add GitHub App installation tables with RLS

Revision ID: h8c9d0e1f2g3
Revises: 3ac6d22a5104
Create Date: 2026-03-03

Creates:
1. github_app_installations - Tracks GitHub App installs linked to Trajan orgs
2. github_app_installation_repos - Tracks which repos each install can access

RLS:
- Installations: viewable by org members, manageable by org admins
- Installation repos: inherit access from parent installation
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB

revision: str = "h8c9d0e1f2g3"
down_revision: str | None = "3ac6d22a5104"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # ======================================================================
    # GITHUB_APP_INSTALLATIONS TABLE
    # ======================================================================
    op.create_table(
        "github_app_installations",
        sa.Column("id", sa.Uuid(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("installation_id", sa.Integer(), nullable=False),
        sa.Column("organization_id", sa.Uuid(), nullable=False),
        sa.Column("github_account_login", sa.String(length=255), nullable=False),
        sa.Column("github_account_type", sa.String(length=20), nullable=False),
        sa.Column("installed_by_user_id", sa.Uuid(), nullable=False),
        sa.Column("permissions", JSONB(), nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("repository_selection", sa.String(length=20), server_default="all", nullable=False),
        sa.Column("suspended_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["organization_id"], ["organizations.id"]),
        sa.ForeignKeyConstraint(["installed_by_user_id"], ["users.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("installation_id"),
    )
    op.create_index("ix_github_app_installations_installation_id", "github_app_installations", ["installation_id"])
    op.create_index("ix_github_app_installations_organization_id", "github_app_installations", ["organization_id"])

    # ======================================================================
    # GITHUB_APP_INSTALLATION_REPOS TABLE
    # ======================================================================
    op.create_table(
        "github_app_installation_repos",
        sa.Column("id", sa.Uuid(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("installation_id", sa.Uuid(), nullable=False),
        sa.Column("github_repo_id", sa.Integer(), nullable=False),
        sa.Column("full_name", sa.String(length=500), nullable=False),
        sa.ForeignKeyConstraint(["installation_id"], ["github_app_installations.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_github_app_installation_repos_installation_id", "github_app_installation_repos", ["installation_id"])
    op.create_index("ix_github_app_installation_repos_github_repo_id", "github_app_installation_repos", ["github_repo_id"])

    # ======================================================================
    # ROW-LEVEL SECURITY
    # ======================================================================

    # --- github_app_installations ---
    op.execute("ALTER TABLE github_app_installations ENABLE ROW LEVEL SECURITY")

    # Org members can view installations for their org
    op.execute("""
        CREATE POLICY github_app_installations_select ON github_app_installations
            FOR SELECT
            USING (is_org_member(organization_id))
    """)

    # Org admins can manage (insert/update/delete) installations
    op.execute("""
        CREATE POLICY github_app_installations_manage ON github_app_installations
            FOR ALL
            USING (is_org_admin(organization_id))
            WITH CHECK (is_org_admin(organization_id))
    """)

    # --- github_app_installation_repos ---
    op.execute("ALTER TABLE github_app_installation_repos ENABLE ROW LEVEL SECURITY")

    # Viewable if parent installation is viewable (org member)
    op.execute("""
        CREATE POLICY github_app_installation_repos_select ON github_app_installation_repos
            FOR SELECT
            USING (
                EXISTS (
                    SELECT 1 FROM github_app_installations
                    WHERE id = github_app_installation_repos.installation_id
                    AND is_org_member(organization_id)
                )
            )
    """)

    # Manageable if parent installation's org is admin-accessible
    op.execute("""
        CREATE POLICY github_app_installation_repos_manage ON github_app_installation_repos
            FOR ALL
            USING (
                EXISTS (
                    SELECT 1 FROM github_app_installations
                    WHERE id = github_app_installation_repos.installation_id
                    AND is_org_admin(organization_id)
                )
            )
            WITH CHECK (
                EXISTS (
                    SELECT 1 FROM github_app_installations
                    WHERE id = github_app_installation_repos.installation_id
                    AND is_org_admin(organization_id)
                )
            )
    """)


def downgrade() -> None:
    op.execute("DROP POLICY IF EXISTS github_app_installation_repos_manage ON github_app_installation_repos")
    op.execute("DROP POLICY IF EXISTS github_app_installation_repos_select ON github_app_installation_repos")
    op.execute("DROP POLICY IF EXISTS github_app_installations_manage ON github_app_installations")
    op.execute("DROP POLICY IF EXISTS github_app_installations_select ON github_app_installations")
    op.drop_table("github_app_installation_repos")
    op.drop_table("github_app_installations")
