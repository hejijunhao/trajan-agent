"""add_app_info_tags_column

Revision ID: b8b11986d8db
Revises: 5817dc60b969
Create Date: 2026-01-22 15:07:05.665775

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = 'b8b11986d8db'
down_revision: Union[str, None] = '5817dc60b969'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Add tags column as PostgreSQL ARRAY of strings
    op.add_column(
        'app_info',
        sa.Column('tags', postgresql.ARRAY(sa.String(length=50)), server_default='{}', nullable=False)
    )
    # Add GIN index for efficient array containment queries (e.g. tags @> ARRAY['production'])
    op.create_index(
        'ix_app_info_tags',
        'app_info',
        ['tags'],
        unique=False,
        postgresql_using='gin'
    )


def downgrade() -> None:
    op.drop_index('ix_app_info_tags', table_name='app_info')
    op.drop_column('app_info', 'tags')
