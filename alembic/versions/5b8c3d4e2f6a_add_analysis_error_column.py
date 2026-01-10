"""Add analysis_error column to products

Revision ID: 5b8c3d4e2f6a
Revises: 4a7b9c2d1e3f
Create Date: 2025-01-09

"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = "5b8c3d4e2f6a"
down_revision: Union[str, None] = "4a7b9c2d1e3f"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Add analysis_error column to products table."""
    op.add_column(
        "products",
        sa.Column(
            "analysis_error",
            sa.VARCHAR(500),
            nullable=True,
            comment="Error message if analysis failed",
        ),
    )


def downgrade() -> None:
    """Remove analysis_error column from products table."""
    op.drop_column("products", "analysis_error")
