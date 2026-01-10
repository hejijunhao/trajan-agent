"""Sync model structure with database

Revision ID: 919c32e13aa2
Revises: 7d0e1f2a3b4c
Create Date: 2026-01-10 15:35:56.389289

"""
from typing import Sequence, Union

from alembic import op

# revision identifiers, used by Alembic.
revision: str = '919c32e13aa2'
down_revision: Union[str, None] = '7d0e1f2a3b4c'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Consolidate separate unique constraint + index into single unique index
    # This is functionally equivalent but cleaner structure
    op.drop_constraint('organizations_slug_key', 'organizations', type_='unique')
    op.drop_index('ix_organizations_slug', table_name='organizations')
    op.create_index('ix_organizations_slug', 'organizations', ['slug'], unique=True)
    # Note: Column comments are intentionally preserved in the database
    # They provide useful documentation even though models use Pydantic description


def downgrade() -> None:
    # Restore separate unique constraint + index structure
    op.drop_index('ix_organizations_slug', table_name='organizations')
    op.create_index('ix_organizations_slug', 'organizations', ['slug'], unique=False)
    op.create_unique_constraint('organizations_slug_key', 'organizations', ['slug'])
