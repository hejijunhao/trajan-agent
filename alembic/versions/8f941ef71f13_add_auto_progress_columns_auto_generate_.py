"""Add auto-progress columns: auto_generate_docs, last_activity_at

Revision ID: 8f941ef71f13
Revises: 4e9cf7146966
Create Date: 2026-02-04 18:16:58.774397

Adds columns needed for auto-progress feature:
1. user_preferences.auto_generate_docs - Toggle for automatic doc generation
2. progress_summary.last_activity_at - Newest commit timestamp for smart-skip logic
3. dashboard_shipped_summary.last_activity_at - Same for dashboard summaries
"""

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = '8f941ef71f13'
down_revision: str = '4e9cf7146966'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        'user_preferences',
        sa.Column('auto_generate_docs', sa.Boolean(), nullable=False, server_default='true'),
    )
    op.add_column(
        'progress_summary',
        sa.Column('last_activity_at', sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        'dashboard_shipped_summary',
        sa.Column('last_activity_at', sa.DateTime(timezone=True), nullable=True),
    )


def downgrade() -> None:
    op.drop_column('dashboard_shipped_summary', 'last_activity_at')
    op.drop_column('progress_summary', 'last_activity_at')
    op.drop_column('user_preferences', 'auto_generate_docs')
