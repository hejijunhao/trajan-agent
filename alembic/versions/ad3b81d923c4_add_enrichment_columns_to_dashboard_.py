"""add_enrichment_columns_to_dashboard_shipped_summary

Adds merged_prs (int), top_contributors (JSONB), and repositories (JSONB)
columns to the dashboard_shipped_summary table for caching enriched
per-product data alongside AI-generated shipped summaries.

Revision ID: ad3b81d923c4
Revises: j0e1f2g3h4i5
Create Date: 2026-03-04 13:35:15.484377

"""
from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

# revision identifiers, used by Alembic.
revision: str = 'ad3b81d923c4'
down_revision: str | None = 'j0e1f2g3h4i5'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        'dashboard_shipped_summary',
        sa.Column('merged_prs', sa.Integer(), nullable=False, server_default='0'),
    )
    op.add_column(
        'dashboard_shipped_summary',
        sa.Column(
            'top_contributors',
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'[]'::jsonb"),
            nullable=False,
            comment='Top contributors: [{author, avatar_url, additions, deletions}]',
        ),
    )
    op.add_column(
        'dashboard_shipped_summary',
        sa.Column(
            'repositories',
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'[]'::jsonb"),
            nullable=False,
            comment='Linked repos: [{name, full_name, url}]',
        ),
    )


def downgrade() -> None:
    op.drop_column('dashboard_shipped_summary', 'repositories')
    op.drop_column('dashboard_shipped_summary', 'top_contributors')
    op.drop_column('dashboard_shipped_summary', 'merged_prs')
