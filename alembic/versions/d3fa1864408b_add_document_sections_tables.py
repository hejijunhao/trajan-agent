"""add_document_sections_tables

Revision ID: d3fa1864408b
Revises: 8422fdb4f433
Create Date: 2026-01-24 18:12:38.288521

Creates document_sections and document_subsections tables for custom
document organization. Adds section_id and subsection_id FK columns
to documents table.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
import sqlmodel

# revision identifiers, used by Alembic.
revision: str = 'd3fa1864408b'
down_revision: Union[str, None] = '8422fdb4f433'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Create document_sections table
    op.create_table('document_sections',
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('id', sa.Uuid(), server_default=sa.text('gen_random_uuid()'), nullable=False),
        sa.Column('name', sqlmodel.sql.sqltypes.AutoString(length=100), nullable=False),
        sa.Column('slug', sqlmodel.sql.sqltypes.AutoString(length=50), nullable=False),
        sa.Column('position', sa.Integer(), nullable=False),
        sa.Column('color', sqlmodel.sql.sqltypes.AutoString(length=7), nullable=True),
        sa.Column('icon', sqlmodel.sql.sqltypes.AutoString(length=50), nullable=True),
        sa.Column('is_default', sa.Boolean(), nullable=False),
        sa.Column('product_id', sa.Uuid(), nullable=False),
        sa.ForeignKeyConstraint(['product_id'], ['products.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_document_sections_id'), 'document_sections', ['id'], unique=False)
    op.create_index(op.f('ix_document_sections_product_id'), 'document_sections', ['product_id'], unique=False)
    op.create_index(op.f('ix_document_sections_slug'), 'document_sections', ['slug'], unique=False)

    # Create document_subsections table
    op.create_table('document_subsections',
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('id', sa.Uuid(), server_default=sa.text('gen_random_uuid()'), nullable=False),
        sa.Column('name', sqlmodel.sql.sqltypes.AutoString(length=100), nullable=False),
        sa.Column('slug', sqlmodel.sql.sqltypes.AutoString(length=50), nullable=False),
        sa.Column('position', sa.Integer(), nullable=False),
        sa.Column('is_default', sa.Boolean(), nullable=False),
        sa.Column('section_id', sa.Uuid(), nullable=False),
        sa.ForeignKeyConstraint(['section_id'], ['document_sections.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_document_subsections_id'), 'document_subsections', ['id'], unique=False)
    op.create_index(op.f('ix_document_subsections_section_id'), 'document_subsections', ['section_id'], unique=False)
    op.create_index(op.f('ix_document_subsections_slug'), 'document_subsections', ['slug'], unique=False)

    # Add FK columns to documents table
    op.add_column('documents', sa.Column('section_id', sa.Uuid(), nullable=True))
    op.add_column('documents', sa.Column('subsection_id', sa.Uuid(), nullable=True))
    op.create_index(op.f('ix_documents_section_id'), 'documents', ['section_id'], unique=False)
    op.create_index(op.f('ix_documents_subsection_id'), 'documents', ['subsection_id'], unique=False)
    op.create_foreign_key(
        'fk_documents_section_id',
        'documents', 'document_sections',
        ['section_id'], ['id'],
        ondelete='SET NULL'
    )
    op.create_foreign_key(
        'fk_documents_subsection_id',
        'documents', 'document_subsections',
        ['subsection_id'], ['id'],
        ondelete='SET NULL'
    )


def downgrade() -> None:
    # Remove FK constraints from documents
    op.drop_constraint('fk_documents_subsection_id', 'documents', type_='foreignkey')
    op.drop_constraint('fk_documents_section_id', 'documents', type_='foreignkey')
    op.drop_index(op.f('ix_documents_subsection_id'), table_name='documents')
    op.drop_index(op.f('ix_documents_section_id'), table_name='documents')
    op.drop_column('documents', 'subsection_id')
    op.drop_column('documents', 'section_id')

    # Drop document_subsections table
    op.drop_index(op.f('ix_document_subsections_slug'), table_name='document_subsections')
    op.drop_index(op.f('ix_document_subsections_section_id'), table_name='document_subsections')
    op.drop_index(op.f('ix_document_subsections_id'), table_name='document_subsections')
    op.drop_table('document_subsections')

    # Drop document_sections table
    op.drop_index(op.f('ix_document_sections_slug'), table_name='document_sections')
    op.drop_index(op.f('ix_document_sections_product_id'), table_name='document_sections')
    op.drop_index(op.f('ix_document_sections_id'), table_name='document_sections')
    op.drop_table('document_sections')
