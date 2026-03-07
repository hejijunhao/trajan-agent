"""add_on_delete_cascade_product_fk

Revision ID: 123d6d064c69
Revises: 22beb16d16fa
Create Date: 2026-03-07 14:47:19.167583

"""
from typing import Sequence, Union

from alembic import op

# revision identifiers, used by Alembic.
revision: str = '123d6d064c69'
down_revision: Union[str, None] = '22beb16d16fa'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.drop_constraint('dashboard_shipped_summary_product_id_fkey', 'dashboard_shipped_summary', type_='foreignkey')
    op.create_foreign_key('dashboard_shipped_summary_product_id_fkey', 'dashboard_shipped_summary', 'products', ['product_id'], ['id'], ondelete='CASCADE')

    op.drop_constraint('product_api_keys_product_id_fkey', 'product_api_keys', type_='foreignkey')
    op.create_foreign_key('product_api_keys_product_id_fkey', 'product_api_keys', 'products', ['product_id'], ['id'], ondelete='CASCADE')

    op.drop_constraint('progress_summary_product_id_fkey', 'progress_summary', type_='foreignkey')
    op.create_foreign_key('progress_summary_product_id_fkey', 'progress_summary', 'products', ['product_id'], ['id'], ondelete='CASCADE')


def downgrade() -> None:
    op.drop_constraint('progress_summary_product_id_fkey', 'progress_summary', type_='foreignkey')
    op.create_foreign_key('progress_summary_product_id_fkey', 'progress_summary', 'products', ['product_id'], ['id'])

    op.drop_constraint('product_api_keys_product_id_fkey', 'product_api_keys', type_='foreignkey')
    op.create_foreign_key('product_api_keys_product_id_fkey', 'product_api_keys', 'products', ['product_id'], ['id'])

    op.drop_constraint('dashboard_shipped_summary_product_id_fkey', 'dashboard_shipped_summary', type_='foreignkey')
    op.create_foreign_key('dashboard_shipped_summary_product_id_fkey', 'dashboard_shipped_summary', 'products', ['product_id'], ['id'])
