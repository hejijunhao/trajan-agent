"""add_user_onboarding_completed_at

Revision ID: bcb0ccbadcf8
Revises: 8b89e086729d
Create Date: 2026-01-14 11:06:54.329548

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'bcb0ccbadcf8'
down_revision: Union[str, None] = '8b89e086729d'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        'users',
        sa.Column('onboarding_completed_at', sa.DateTime(timezone=True), nullable=True)
    )


def downgrade() -> None:
    op.drop_column('users', 'onboarding_completed_at')
