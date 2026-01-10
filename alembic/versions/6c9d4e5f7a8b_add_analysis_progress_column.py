"""Add analysis_progress column to products

Revision ID: 6c9d4e5f7a8b
Revises: 5b8c3d4e2f6a
Create Date: 2026-01-10

"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB

# revision identifiers, used by Alembic.
revision: str = "6c9d4e5f7a8b"
down_revision: Union[str, None] = "5b8c3d4e2f6a"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Add analysis_progress JSONB column to products table."""
    op.add_column(
        "products",
        sa.Column(
            "analysis_progress",
            JSONB,
            nullable=True,
            comment="Real-time progress updates during analysis (ephemeral)",
        ),
    )


def downgrade() -> None:
    """Remove analysis_progress column from products table."""
    op.drop_column("products", "analysis_progress")
