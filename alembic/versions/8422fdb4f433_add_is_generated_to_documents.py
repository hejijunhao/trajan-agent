"""add_is_generated_to_documents

Revision ID: 8422fdb4f433
Revises: b8b11986d8db
Create Date: 2026-01-23 08:21:21.383277

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = '8422fdb4f433'
down_revision: Union[str, None] = 'b8b11986d8db'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Add is_generated column with server default (allows NOT NULL on existing rows)
    op.add_column(
        'documents',
        sa.Column('is_generated', sa.Boolean(), server_default='false', nullable=False)
    )

    # Create index for efficient filtering
    op.create_index(
        op.f('ix_documents_is_generated'),
        'documents',
        ['is_generated'],
        unique=False
    )

    # Backfill: docs without github_path are AI-generated (created in Trajan)
    # docs with github_path are imported from repository
    op.execute("""
        UPDATE documents
        SET is_generated = (github_path IS NULL)
    """)


def downgrade() -> None:
    op.drop_index(op.f('ix_documents_is_generated'), table_name='documents')
    op.drop_column('documents', 'is_generated')
