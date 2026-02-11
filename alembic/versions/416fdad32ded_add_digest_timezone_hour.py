"""add_digest_timezone_hour

Revision ID: 416fdad32ded
Revises: 9e7241e43816
Create Date: 2026-02-11 14:54:40.691834

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '416fdad32ded'
down_revision: Union[str, None] = '9e7241e43816'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column('user_preferences', sa.Column('digest_timezone', sa.String(50), server_default='UTC', nullable=False))
    op.add_column('user_preferences', sa.Column('digest_hour', sa.Integer, server_default='17', nullable=False))


def downgrade() -> None:
    op.drop_column('user_preferences', 'digest_hour')
    op.drop_column('user_preferences', 'digest_timezone')
