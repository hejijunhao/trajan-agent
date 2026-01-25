"""add_github_setup_dismissed_column

Revision ID: f6a7b8c9d0e1
Revises: eccd82f7abda
Create Date: 2026-01-25 19:30:00.000000

Adds github_setup_dismissed column to user_preferences table.
This column tracks whether the user has dismissed the GitHub setup banner on the dashboard.
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "f6a7b8c9d0e1"
down_revision: Union[str, None] = "c0306c5e6ad0"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Add github_setup_dismissed column to user_preferences."""
    op.add_column(
        "user_preferences",
        sa.Column("github_setup_dismissed", sa.Boolean(), nullable=False, server_default="false"),
    )


def downgrade() -> None:
    """Remove github_setup_dismissed column from user_preferences."""
    op.drop_column("user_preferences", "github_setup_dismissed")
