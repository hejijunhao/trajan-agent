"""schema_drift_cleanup_drop_deprecated_digest_columns

Revision ID: 2af162960e6e
Revises: 123d6d064c69
Create Date: 2026-03-07 14:53:28.812627

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = '2af162960e6e'
down_revision: Union[str, None] = '123d6d064c69'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Drop deprecated digest columns from user_preferences.
    # These were replaced by the org_digest_preferences table in v0.16.18
    # and left in the DB for rollback safety. Now safe to remove.
    op.drop_column('user_preferences', 'digest_timezone')
    op.drop_column('user_preferences', 'email_digest')
    op.drop_column('user_preferences', 'digest_product_ids')
    op.drop_column('user_preferences', 'digest_hour')


def downgrade() -> None:
    op.add_column(
        'user_preferences',
        sa.Column(
            'digest_hour',
            sa.INTEGER(),
            server_default=sa.text('17'),
            autoincrement=False,
            nullable=False,
        ),
    )
    op.add_column(
        'user_preferences',
        sa.Column(
            'digest_product_ids',
            postgresql.JSONB(astext_type=sa.Text()),
            autoincrement=False,
            nullable=True,
            comment='Product UUIDs for per-project digest. NULL = all projects.',
        ),
    )
    op.add_column(
        'user_preferences',
        sa.Column(
            'email_digest',
            sa.VARCHAR(length=20),
            server_default=sa.text("'none'::character varying"),
            autoincrement=False,
            nullable=False,
        ),
    )
    op.add_column(
        'user_preferences',
        sa.Column(
            'digest_timezone',
            sa.VARCHAR(length=50),
            server_default=sa.text("'UTC'::character varying"),
            autoincrement=False,
            nullable=False,
        ),
    )
