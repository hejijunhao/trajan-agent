"""Sync subscription base_repo_limit with plan configurations.

This data migration updates non-manually-assigned subscriptions to have
their base_repo_limit match the current plan configuration values.

Revision ID: c0306c5e6ad0
Revises: eccd82f7abda
Create Date: 2026-01-25 18:31:17.851562

"""

from collections.abc import Sequence

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "c0306c5e6ad0"
down_revision: str | None = "eccd82f7abda"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# Plan configuration (matches plans.py)
PLAN_LIMITS = {
    "indie": 5,
    "pro": 10,
    "scale": 50,
    # Legacy tier mapping
    "observer": 1,
    "foundations": 5,
    "core": 10,
    "autonomous": 50,
}


def upgrade() -> None:
    # Update non-manually-assigned subscriptions to match their plan limits
    for tier, limit in PLAN_LIMITS.items():
        op.execute(f"""
            UPDATE subscriptions
            SET base_repo_limit = {limit}
            WHERE plan_tier = '{tier}'
            AND is_manually_assigned = false
        """)


def downgrade() -> None:
    # No downgrade — data migration only
    pass
