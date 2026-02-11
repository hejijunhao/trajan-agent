"""add_digest_product_ids_to_user_preferences

Revision ID: 9e7241e43816
Revises: 4c2d6eab7d4b
Create Date: 2026-02-11 13:41:54.312867

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = '9e7241e43816'
down_revision: Union[str, None] = '4c2d6eab7d4b'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column('user_preferences', sa.Column('digest_product_ids', postgresql.JSONB(astext_type=sa.Text()), nullable=True, comment='Product UUIDs for per-project digest. NULL = all projects.'))


def downgrade() -> None:
    op.drop_column('user_preferences', 'digest_product_ids')
