"""add_discount_codes_and_redemptions_tables

Revision ID: 46962b59da2e
Revises: b3c4d5e6f7a8
Create Date: 2026-02-16 18:07:08.304850

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
import sqlmodel


# revision identifiers, used by Alembic.
revision: str = '46962b59da2e'
down_revision: Union[str, None] = 'b3c4d5e6f7a8'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table('discount_codes',
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('id', sa.Uuid(), server_default=sa.text('gen_random_uuid()'), nullable=False),
    sa.Column('code', sa.String(length=50), nullable=False),
    sa.Column('description', sqlmodel.sql.sqltypes.AutoString(length=500), nullable=True),
    sa.Column('discount_percent', sa.Integer(), nullable=False),
    sa.Column('max_redemptions', sa.Integer(), nullable=True),
    sa.Column('times_redeemed', sa.Integer(), nullable=False),
    sa.Column('is_active', sa.Boolean(), nullable=False),
    sa.Column('stripe_coupon_id', sqlmodel.sql.sqltypes.AutoString(length=255), nullable=True),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index('ix_discount_codes_code', 'discount_codes', ['code'], unique=True)
    op.create_index(op.f('ix_discount_codes_id'), 'discount_codes', ['id'], unique=False)
    op.create_table('discount_redemptions',
    sa.Column('id', sa.Uuid(), server_default=sa.text('gen_random_uuid()'), nullable=False),
    sa.Column('discount_code_id', sa.UUID(), nullable=False),
    sa.Column('organization_id', sa.UUID(), nullable=False),
    sa.Column('redeemed_by', sa.UUID(), nullable=True),
    sa.Column('redeemed_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.ForeignKeyConstraint(['discount_code_id'], ['discount_codes.id'], ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['organization_id'], ['organizations.id'], ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['redeemed_by'], ['users.id'], ondelete='SET NULL'),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index('ix_discount_redemptions_code', 'discount_redemptions', ['discount_code_id'], unique=False)
    op.create_index(op.f('ix_discount_redemptions_id'), 'discount_redemptions', ['id'], unique=False)
    op.create_index('ix_discount_redemptions_org', 'discount_redemptions', ['organization_id'], unique=False)


def downgrade() -> None:
    op.drop_index('ix_discount_redemptions_org', table_name='discount_redemptions')
    op.drop_index(op.f('ix_discount_redemptions_id'), table_name='discount_redemptions')
    op.drop_index('ix_discount_redemptions_code', table_name='discount_redemptions')
    op.drop_table('discount_redemptions')
    op.drop_index(op.f('ix_discount_codes_id'), table_name='discount_codes')
    op.drop_index('ix_discount_codes_code', table_name='discount_codes')
    op.drop_table('discount_codes')
