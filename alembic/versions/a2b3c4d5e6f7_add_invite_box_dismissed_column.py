"""add_invite_box_dismissed_column

Revision ID: a2b3c4d5e6f7
Revises: 8f941ef71f13
Create Date: 2026-02-05 12:00:00.000000

Adds invite_box_dismissed column to user_preferences table.
This column tracks whether the user has dismissed the referral invite box on the dashboard.
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "a2b3c4d5e6f7"
down_revision: Union[str, None] = "8f941ef71f13"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Add invite_box_dismissed column to user_preferences."""
    op.add_column(
        "user_preferences",
        sa.Column("invite_box_dismissed", sa.Boolean(), nullable=False, server_default="false"),
    )


def downgrade() -> None:
    """Remove invite_box_dismissed column from user_preferences."""
    op.drop_column("user_preferences", "invite_box_dismissed")
