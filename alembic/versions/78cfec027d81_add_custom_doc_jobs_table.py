"""add_custom_doc_jobs_table

Revision ID: 78cfec027d81
Revises: 5d5127f446f1
Create Date: 2026-01-14 22:46:40.509125

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
import sqlmodel

# revision identifiers, used by Alembic.
revision: str = '78cfec027d81'
down_revision: Union[str, None] = '5d5127f446f1'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Create custom_doc_jobs table for persistent job storage
    op.create_table('custom_doc_jobs',
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('id', sa.Uuid(), server_default=sa.text('gen_random_uuid()'), nullable=False),
        sa.Column('product_id', sa.Uuid(), nullable=False),
        sa.Column('user_id', sa.Uuid(), nullable=False),
        sa.Column('status', sqlmodel.sql.sqltypes.AutoString(length=20), nullable=False),
        sa.Column('progress', sqlmodel.sql.sqltypes.AutoString(length=100), nullable=False),
        sa.Column('content', sqlmodel.sql.sqltypes.AutoString(), nullable=True),
        sa.Column('suggested_title', sqlmodel.sql.sqltypes.AutoString(length=500), nullable=True),
        sa.Column('error', sqlmodel.sql.sqltypes.AutoString(length=2000), nullable=True),
        sa.Column('expires_at', sa.DateTime(timezone=True), server_default=sa.text("now() + interval '1 hour'"), nullable=False),
        sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_custom_doc_jobs_id'), 'custom_doc_jobs', ['id'], unique=False)
    op.create_index(op.f('ix_custom_doc_jobs_product_id'), 'custom_doc_jobs', ['product_id'], unique=False)
    op.create_index(op.f('ix_custom_doc_jobs_status'), 'custom_doc_jobs', ['status'], unique=False)
    op.create_index('ix_custom_doc_jobs_status_created', 'custom_doc_jobs', ['status', 'created_at'], unique=False)
    op.create_index(op.f('ix_custom_doc_jobs_user_id'), 'custom_doc_jobs', ['user_id'], unique=False)
    op.create_index('ix_custom_doc_jobs_user_product', 'custom_doc_jobs', ['user_id', 'product_id'], unique=False)


def downgrade() -> None:
    op.drop_index('ix_custom_doc_jobs_user_product', table_name='custom_doc_jobs')
    op.drop_index(op.f('ix_custom_doc_jobs_user_id'), table_name='custom_doc_jobs')
    op.drop_index('ix_custom_doc_jobs_status_created', table_name='custom_doc_jobs')
    op.drop_index(op.f('ix_custom_doc_jobs_status'), table_name='custom_doc_jobs')
    op.drop_index(op.f('ix_custom_doc_jobs_product_id'), table_name='custom_doc_jobs')
    op.drop_index(op.f('ix_custom_doc_jobs_id'), table_name='custom_doc_jobs')
    op.drop_table('custom_doc_jobs')
