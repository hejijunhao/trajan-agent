"""add_product_analysis_columns

Revision ID: 4a7b9c2d1e3f
Revises: 3f8a2c1d4e5b
Create Date: 2026-01-09 12:00:00.000000

This migration adds two columns to the products table for AI-powered analysis:
1. analysis_status: Tracks the state of analysis ('analyzing', 'completed', 'failed', NULL)
2. product_overview: JSONB column storing the full AI-generated project overview

The product_overview column stores structured data matching the ProductOverview schema,
including summary, stats, technical/business/features/use_cases content, and architecture
visualization data.
"""

from collections.abc import Sequence

import sqlalchemy as sa
import sqlmodel
from sqlalchemy.dialects.postgresql import JSONB

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "4a7b9c2d1e3f"
down_revision: str | None = "3f8a2c1d4e5b"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # Add analysis_status column for tracking analysis state
    op.add_column(
        "products",
        sa.Column(
            "analysis_status",
            sqlmodel.sql.sqltypes.AutoString(length=20),
            nullable=True,
            comment="Analysis state: 'analyzing' | 'completed' | 'failed' | NULL",
        ),
    )

    # Add product_overview JSONB column for storing AI-generated overview
    op.add_column(
        "products",
        sa.Column(
            "product_overview",
            JSONB(),
            nullable=True,
            comment="AI-generated project overview (ProductOverview schema)",
        ),
    )

    # Optional: Add index for filtering by analysis status
    op.create_index(
        "ix_products_analysis_status",
        "products",
        ["analysis_status"],
        unique=False,
    )


def downgrade() -> None:
    # Remove index
    op.drop_index("ix_products_analysis_status", table_name="products")

    # Remove columns
    op.drop_column("products", "product_overview")
    op.drop_column("products", "analysis_status")
