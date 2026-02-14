"""add_first_subscribed_at_to_subscriptions

Revision ID: b3c4d5e6f7a8
Revises: ca55440f0ab9
Create Date: 2026-02-15 12:00:00.000000

Adds first_subscribed_at column to subscriptions table.
Used to determine free trial eligibility — only first-time subscribers get the trial.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'b3c4d5e6f7a8'
down_revision: Union[str, None] = 'ca55440f0ab9'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        'subscriptions',
        sa.Column('first_subscribed_at', sa.DateTime(timezone=True), nullable=True,
                   comment='When this org first subscribed — used to determine trial eligibility'),
    )

    # Backfill: any subscription that already has a stripe_subscription_id has subscribed before
    op.execute(
        "UPDATE subscriptions SET first_subscribed_at = created_at "
        "WHERE stripe_subscription_id IS NOT NULL AND first_subscribed_at IS NULL"
    )


def downgrade() -> None:
    op.drop_column('subscriptions', 'first_subscribed_at')
