"""add_contributor_summaries_to_progress_summary

Revision ID: cde3c238696b
Revises: 9f57482e6a14
Create Date: 2026-02-27 07:31:58.002201

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = 'cde3c238696b'
down_revision: Union[str, None] = '9f57482e6a14'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column('progress_summary', sa.Column('contributor_summaries', postgresql.JSONB(astext_type=sa.Text()), nullable=True, comment='Per-contributor AI summaries. Array of {name, summary_text, commit_count, additions, deletions, commit_refs: [{sha, branch}]}'))


def downgrade() -> None:
    op.drop_column('progress_summary', 'contributor_summaries')
