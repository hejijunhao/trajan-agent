"""Add organizations, organization_members, user.is_admin, and products.organization_id

Revision ID: 7d0e1f2a3b4c
Revises: 6c9d4e5f7a8b
Create Date: 2026-01-10

"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB, UUID

# revision identifiers, used by Alembic.
revision: str = "7d0e1f2a3b4c"
down_revision: Union[str, None] = "6c9d4e5f7a8b"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Create organizations infrastructure for Phase 1 of pricing architecture."""

    # Step 1: Create organizations table
    op.create_table(
        "organizations",
        sa.Column(
            "id",
            UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column("name", sa.String(100), nullable=False),
        sa.Column("slug", sa.String(100), unique=True, nullable=False),
        sa.Column("owner_id", UUID(as_uuid=True), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("settings", JSONB, nullable=True),
        sa.Column("created_at", sa.DateTime, server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime, nullable=True),
    )
    op.create_index("ix_organizations_slug", "organizations", ["slug"])
    op.create_index("ix_organizations_owner_id", "organizations", ["owner_id"])

    # Step 2: Create organization_members table
    op.create_table(
        "organization_members",
        sa.Column(
            "id",
            UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column(
            "organization_id",
            UUID(as_uuid=True),
            sa.ForeignKey("organizations.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "user_id",
            UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("role", sa.String(20), nullable=False, server_default="member"),
        sa.Column("invited_by", UUID(as_uuid=True), sa.ForeignKey("users.id"), nullable=True),
        sa.Column("invited_at", sa.DateTime, nullable=True),
        sa.Column("joined_at", sa.DateTime, server_default=sa.func.now(), nullable=False),
    )
    op.create_index("ix_organization_members_organization_id", "organization_members", ["organization_id"])
    op.create_index("ix_organization_members_user_id", "organization_members", ["user_id"])
    op.create_unique_constraint("uq_org_member", "organization_members", ["organization_id", "user_id"])

    # Step 3: Add is_admin column to users table
    op.add_column(
        "users",
        sa.Column(
            "is_admin",
            sa.Boolean,
            nullable=False,
            server_default=sa.text("false"),
            comment="Admin flag for manual plan assignment and admin operations",
        ),
    )

    # Step 4: Add organization_id column to products table (nullable during migration)
    op.add_column(
        "products",
        sa.Column(
            "organization_id",
            UUID(as_uuid=True),
            sa.ForeignKey("organizations.id"),
            nullable=True,
            comment="Organization that owns this product (nullable during migration)",
        ),
    )
    op.create_index("ix_products_organization_id", "products", ["organization_id"])


def downgrade() -> None:
    """Remove organizations infrastructure."""

    # Step 4: Remove organization_id from products
    op.drop_index("ix_products_organization_id", table_name="products")
    op.drop_column("products", "organization_id")

    # Step 3: Remove is_admin from users
    op.drop_column("users", "is_admin")

    # Step 2: Drop organization_members table
    op.drop_constraint("uq_org_member", "organization_members", type_="unique")
    op.drop_index("ix_organization_members_user_id", table_name="organization_members")
    op.drop_index("ix_organization_members_organization_id", table_name="organization_members")
    op.drop_table("organization_members")

    # Step 1: Drop organizations table
    op.drop_index("ix_organizations_owner_id", table_name="organizations")
    op.drop_index("ix_organizations_slug", table_name="organizations")
    op.drop_table("organizations")
