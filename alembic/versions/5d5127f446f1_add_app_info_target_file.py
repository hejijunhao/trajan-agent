"""add_app_info_target_file

Revision ID: 5d5127f446f1
Revises: bcb0ccbadcf8
Create Date: 2026-01-14 12:02:49.522183

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '5d5127f446f1'
down_revision: Union[str, None] = 'bcb0ccbadcf8'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column('app_info', sa.Column('target_file', sa.String(100), nullable=True))


def downgrade() -> None:
    op.drop_column('app_info', 'target_file')
