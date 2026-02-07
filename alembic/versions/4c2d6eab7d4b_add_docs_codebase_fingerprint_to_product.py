"""Add docs_codebase_fingerprint to Product

Revision ID: 4c2d6eab7d4b
Revises: f4a2b3c5d6e7
Create Date: 2026-02-07 10:39:52.084863

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
import sqlmodel

# revision identifiers, used by Alembic.
revision: str = '4c2d6eab7d4b'
down_revision: Union[str, None] = 'f4a2b3c5d6e7'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Add fingerprint column for skip-if-unchanged optimization
    op.add_column(
        'products',
        sa.Column(
            'docs_codebase_fingerprint',
            sqlmodel.sql.sqltypes.AutoString(length=32),
            nullable=True,
            comment='Hash of codebase state at last doc generation (for skip-if-unchanged)'
        )
    )


def downgrade() -> None:
    op.drop_column('products', 'docs_codebase_fingerprint')
