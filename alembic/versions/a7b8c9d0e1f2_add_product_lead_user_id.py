"""add_product_lead_user_id

Revision ID: a7b8c9d0e1f2
Revises: 0631dbf303b9
Create Date: 2026-01-19 18:30:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = 'a7b8c9d0e1f2'
down_revision: Union[str, None] = '0631dbf303b9'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Add lead_user_id column with foreign key to users table
    op.add_column(
        'products',
        sa.Column(
            'lead_user_id',
            postgresql.UUID(as_uuid=True),
            nullable=True,
            comment='Designated project lead (org member responsible for the product)'
        )
    )
    op.create_index('ix_products_lead_user_id', 'products', ['lead_user_id'])
    op.create_foreign_key(
        'fk_products_lead_user_id',
        'products',
        'users',
        ['lead_user_id'],
        ['id'],
        ondelete='SET NULL'
    )


def downgrade() -> None:
    op.drop_constraint('fk_products_lead_user_id', 'products', type_='foreignkey')
    op.drop_index('ix_products_lead_user_id', 'products')
    op.drop_column('products', 'lead_user_id')
