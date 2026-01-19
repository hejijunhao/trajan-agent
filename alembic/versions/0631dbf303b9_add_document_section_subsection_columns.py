"""add_document_section_subsection_columns

Revision ID: 0631dbf303b9
Revises: 9aca077d5d1d
Create Date: 2026-01-19 15:02:37.196484

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = '0631dbf303b9'
down_revision: Union[str, None] = '9aca077d5d1d'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column('documents', sa.Column('section', sa.String(length=50), nullable=True))
    op.add_column('documents', sa.Column('subsection', sa.String(length=50), nullable=True))


def downgrade() -> None:
    op.drop_column('documents', 'subsection')
    op.drop_column('documents', 'section')
