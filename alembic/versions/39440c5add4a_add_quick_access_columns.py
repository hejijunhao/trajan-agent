"""add_quick_access_columns

Revision ID: 39440c5add4a
Revises: 47d1a6ab3d20
Create Date: 2026-01-14 08:49:42.115152

Adds Quick Access feature columns to products table.
These allow password-protected shareable links to App Info.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "39440c5add4a"
down_revision: str | None = "47d1a6ab3d20"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # Add quick access columns to products table
    op.add_column(
        "products",
        sa.Column(
            "quick_access_enabled",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("false"),
            comment="Whether quick access link is active",
        ),
    )
    op.add_column(
        "products",
        sa.Column(
            "quick_access_token",
            sa.String(64),
            nullable=True,
            comment="URL-safe token for quick access link",
        ),
    )
    op.add_column(
        "products",
        sa.Column(
            "quick_access_created_at",
            sa.DateTime(timezone=True),
            nullable=True,
            comment="When quick access was enabled",
        ),
    )
    op.add_column(
        "products",
        sa.Column(
            "quick_access_created_by",
            sa.UUID(),
            nullable=True,
            comment="User who enabled quick access",
        ),
    )

    # Create unique index on quick_access_token for fast lookups
    op.create_index(
        "ix_products_quick_access_token",
        "products",
        ["quick_access_token"],
        unique=True,
    )

    # Add foreign key constraint
    op.create_foreign_key(
        "fk_products_quick_access_created_by",
        "products",
        "users",
        ["quick_access_created_by"],
        ["id"],
    )


def downgrade() -> None:
    op.drop_constraint("fk_products_quick_access_created_by", "products", type_="foreignkey")
    op.drop_index("ix_products_quick_access_token", table_name="products")
    op.drop_column("products", "quick_access_created_by")
    op.drop_column("products", "quick_access_created_at")
    op.drop_column("products", "quick_access_token")
    op.drop_column("products", "quick_access_enabled")
