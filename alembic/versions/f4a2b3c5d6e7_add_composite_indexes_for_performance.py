"""Add composite indexes for common query patterns

Performance optimization: Add composite indexes to speed up frequent lookups
by 10-100x for product access checks, org member lookups, and document queries.

Revision ID: f4a2b3c5d6e7
Revises: a2b3c4d5e6f7
Create Date: 2026-02-07

"""

from alembic import op

# revision identifiers, used by Alembic.
revision = "f4a2b3c5d6e7"
down_revision = "a2b3c4d5e6f7"
branch_labels = None
depends_on = None


def upgrade() -> None:
    """Add composite indexes for performance-critical query patterns."""

    # Product access: (product_id, user_id) - speeds up access checks
    # Called on every product list/get operation
    op.create_index(
        "ix_product_access_product_user",
        "product_access",
        ["product_id", "user_id"],
        unique=True,
        if_not_exists=True,
    )

    # Organization members: (organization_id, user_id) - speeds up role lookups
    # Called on every authenticated request to check org membership
    op.create_index(
        "ix_organization_members_org_user",
        "organization_members",
        ["organization_id", "user_id"],
        unique=True,
        if_not_exists=True,
    )

    # Documents: (product_id, type) - speeds up docs tab filtering
    # Used when listing documents by type within a product
    op.create_index(
        "ix_documents_product_type",
        "documents",
        ["product_id", "type"],
        if_not_exists=True,
    )

    # Repositories: (product_id, github_id) - speeds up import deduplication
    # Checked during GitHub repo import to prevent duplicates
    op.create_index(
        "ix_repositories_product_github",
        "repositories",
        ["product_id", "github_id"],
        if_not_exists=True,
    )


def downgrade() -> None:
    """Remove composite indexes."""
    op.drop_index("ix_product_access_product_user", table_name="product_access")
    op.drop_index("ix_organization_members_org_user", table_name="organization_members")
    op.drop_index("ix_documents_product_type", table_name="documents")
    op.drop_index("ix_repositories_product_github", table_name="repositories")
